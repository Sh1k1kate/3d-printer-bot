import logging
import threading
import time
import json
import ssl
import paho.mqtt.client as mqtt
from config import BAMBU_EMAIL, BAMBU_PASSWORD, BAMBU_TOKEN, BAMBU_REGION

logger = logging.getLogger(__name__)

# Список брокеров по регионам — попробуем по очереди
MQTT_HOSTS = [
    "us.mqtt.bambulab.com",
    "eu.mqtt.bambulab.com",
    "cn.mqtt.bambulab.com",
]
MQTT_PORT = 8883


class BambuCloudManager:
    def __init__(self):
        self.client = None
        self.mqtt_client = None
        self.ams_cache = {}
        self.ams_timestamp = {}
        self._status_cache = {}
        self._lock = threading.Lock()
        self._mqtt_thread = None
        self._running = False
        self._device_ids = []
        self._pushall_sent = False
        self._received_topics = set()
        self._init_client()

    def _init_client(self):
        try:
            from bambulab import BambuClient, BambuAuthenticator
        except ImportError as e:
            logger.warning(f"bambu-lab-cloud-api не установлен: {e}")
            self.client = None
            return

        try:
            token = BAMBU_TOKEN
            if not token and BAMBU_EMAIL and BAMBU_PASSWORD:
                auth = BambuAuthenticator(region=BAMBU_REGION)
                token = auth.get_or_create_token(
                    username=BAMBU_EMAIL,
                    password=BAMBU_PASSWORD
                )
            if token:
                self.client = BambuClient(token=str(token))
                logger.info("Bambu Cloud client успешно инициализирован")
                try:
                    devices = self.client.get_devices()
                    self._device_ids = [d.get("dev_id") for d in devices if d.get("dev_id")]
                    logger.info(f"Загружено {len(self._device_ids)} device_id")
                except Exception as e:
                    logger.error(f"Не удалось получить устройства: {e}")
                self._start_mqtt()
            else:
                logger.warning("Bambu Cloud токен не получен.")
        except Exception as e:
            logger.error(f"Ошибка инициализации Bambu Cloud: {e}")
            self.client = None

    def _start_mqtt(self):
        if not self.client:
            return
        self._running = True
        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()
        logger.info("MQTT поток запущен")

    def _get_credentials(self):
        try:
            user_info = self.client.get_user_info()
        except Exception as e:
            logger.error(f"Не удалось получить user_info: {e}")
            return None, None

        if isinstance(user_info, dict):
            uid = user_info.get("uid") or user_info.get("user_id") or user_info.get("id")
        else:
            uid = getattr(user_info, "uid", None)

        if not uid:
            logger.error(f"UID не найден: {user_info}")
            return None, None

        token = str(getattr(self.client, "token", "")).strip()
        return str(uid).strip(), token

    def _mqtt_loop(self):
        """Перебирает брокеры по регионам, если не удаётся подключиться."""
        host_index = 0
        while self._running:
            uid_str, token_str = self._get_credentials()
            if not uid_str or not token_str:
                time.sleep(30)
                continue

            host = MQTT_HOSTS[host_index]
            try:
                client_id = f"bambu_{uid_str}_{int(time.time())}"
                client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=client_id,
                    clean_session=True
                )
                client.username_pw_set(f"u_{uid_str}", token_str)
                client.tls_set(cert_reqs=ssl.CERT_NONE)
                client.tls_insecure_set(True)

                client.on_connect = self._on_connect
                client.on_message = self._on_paho_message
                client.on_disconnect = self._on_disconnect
                client.on_log = self._on_log

                self.mqtt_client = client
                logger.info(f"MQTT подключение: uid={uid_str}, host={host}:{MQTT_PORT}")
                client.connect(host, MQTT_PORT, 60)
                client.loop_forever()
            except Exception as e:
                logger.error(f"Ошибка MQTT на {host}: {e}")
                # Следующий брокер
                host_index = (host_index + 1) % len(MQTT_HOSTS)
                logger.info(f"Переключаюсь на {MQTT_HOSTS[host_index]}")
                time.sleep(10)

    def _on_log(self, client, userdata, level, buf):
        if level in (mqtt.MQTT_LOG_ERR, mqtt.MQTT_LOG_WARNING):
            logger.warning(f"[paho] {buf}")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("MQTT подключён.")
            # ✅ Подписка на ВСЕ топики — диагностика
            client.subscribe("#", qos=1)
            logger.info("Подписка на # (все топики) + device/+/report")

            if not self._pushall_sent:
                self._pushall_sent = True
                threading.Thread(target=self._delayed_pushall, daemon=True).start()
        else:
            logger.error(f"MQTT ошибка подключения: reason_code={reason_code}")

    def _delayed_pushall(self):
        logger.info("Подготовка pushall через 5 секунд...")
        time.sleep(5)

        for i, device_id in enumerate(self._device_ids):
            if not self._running:
                return
            try:
                if self.mqtt_client and self.mqtt_client.is_connected():
                    topic = f"device/{device_id}/request"
                    # ✅ Правильный формат для облака
                    payload = json.dumps({
                        "pushing": {
                            "sequence_id": str(i + 1),
                            "command": "pushall",
                            "version": 1,
                            "push_target": 1
                        }
                    })
                    self.mqtt_client.publish(topic, payload, qos=1)
                    logger.info(f"→ pushall {device_id}")
                else:
                    logger.warning("MQTT отключён, прерываю pushall")
                    return
            except Exception as e:
                logger.error(f"Ошибка pushall {device_id}: {e}")
            time.sleep(0.5)

        logger.info("✅ pushall отправлен всем принтерам")

        # ⏳ Через 15 секунд — отчёт о принятых топиках
        time.sleep(15)
        logger.info(f"📊 Принято топиков: {len(self._received_topics)}")
        for t in list(self._received_topics)[:10]:
            logger.info(f"   📥 {t}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning(f"MQTT отключён: reason_code={reason_code}. Пауза 15 сек...")
        time.sleep(15)

    def _on_paho_message(self, client, userdata, msg):
        try:
            # ✅ Логируем КАЖДЫЙ полученный топик (диагностика)
            self._received_topics.add(msg.topic)
            logger.info(f"[MQTT TOPIC] {msg.topic}")

            parts = msg.topic.split("/")
            if len(parts) < 3 or parts[0] != "device":
                return
            device_id = parts[1]
            data = json.loads(msg.payload.decode("utf-8"))

            # Показываем первые 500 символов
            logger.info(f"[MQTT RAW] {device_id}: {json.dumps(data)[:500]}")
            self._process_mqtt_data(device_id, data)
        except Exception as e:
            logger.error(f"Ошибка разбора MQTT сообщения: {e}")

    def _process_mqtt_data(self, device_id, data):
        try:
            if not data or "print" not in data:
                return
            print_data = data["print"]

            with self._lock:
                status = self._status_cache.get(device_id, {})
                for key in ("gcode_state", "mc_percent", "mc_remaining_time",
                            "subtask_name", "nozzle_temper", "nozzle_target_temper",
                            "bed_temper", "bed_target_temper"):
                    if key in print_data:
                        status[key] = print_data.get(key)
                self._status_cache[device_id] = status

                if "ams" in print_data:
                    ams = print_data["ams"]
                    trays = []
                    for unit in ams.get("ams", []):
                        for tray in unit.get("tray", []):
                            state = tray.get("state", 0)
                            tray_type = tray.get("tray_type", "")
                            if state == 0 or tray_type in (None, "", "Empty"):
                                continue
                            trays.append({
                                "tray_id": tray.get("id"),
                                "type": tray_type,
                                "color": tray.get("tray_color", "00000000"),
                                "remaining": tray.get("remain", 0),
                            })
                    if trays:
                        self.ams_cache[device_id] = trays
                        logger.info(f"✅ AMS обновлены для {device_id}: {len(trays)}")

                if "vt_tray" in print_data:
                    vt = print_data["vt_tray"]
                    vt_type = vt.get("tray_type", "")
                    if vt_type and vt_type != "Empty":
                        existing = self.ams_cache.get(device_id, [])
                        existing = [t for t in existing if t.get("tray_id") != 254]
                        existing.append({
                            "tray_id": 254,
                            "type": vt_type,
                            "color": vt.get("tray_color", "00000000"),
                            "remaining": vt.get("remain", 0),
                        })
                        self.ams_cache[device_id] = existing
        except Exception as e:
            logger.error(f"Ошибка обработки MQTT данных от {device_id}: {e}")

    def get_printers(self):
        if not self.client:
            return []
        try:
            devices = self.client.get_devices()
            printers = []
            for d in devices:
                device_id = d.get("dev_id")
                name = d.get("name")

                with self._lock:
                    trays = self.ams_cache.get(device_id, [])
                    status_cache = self._status_cache.get(device_id, {})

                if not trays:
                    try:
                        ams_info = self.client.get_ams_filaments(device_id)
                        trays = []
                        for unit in ams_info.get("ams_units", []):
                            for tray in unit.get("trays", []):
                                if not tray.get("filament_type"):
                                    continue
                                trays.append({
                                    "tray_id": tray.get("tray_id"),
                                    "type": tray.get("filament_type", "—"),
                                    "color": tray.get("filament_color", "00000000"),
                                    "remaining": tray.get("remaining", 0),
                                })
                    except Exception:
                        trays = []

                model_code = d.get("dev_model_name", "")
                model_map = {"N2S": "A1", "N1": "A1 mini",
                             "C11": "P1P", "C12": "P1S",
                             "BL-P001": "X1 Carbon", "BL-P002": "X1"}
                model_name = model_map.get(model_code, model_code)

                printers.append({
                    "id": device_id,
                    "name": name,
                    "status": status_cache.get("gcode_state") or d.get("print_status", "UNKNOWN"),
                    "progress": status_cache.get("mc_percent") or d.get("print_progress", 0),
                    "model": model_name,
                    "remaining_time": status_cache.get("mc_remaining_time"),
                    "subtask_name": status_cache.get("subtask_name", ""),
                    "nozzle_temper": status_cache.get("nozzle_temper"),
                    "nozzle_target_temper": status_cache.get("nozzle_target_temper"),
                    "bed_temper": status_cache.get("bed_temper"),
                    "bed_target_temper": status_cache.get("bed_target_temper"),
                    "ams": {
                        "has_ams": len(trays) > 0,
                        "total_trays": len(trays),
                        "trays": trays,
                    }
                })
            return printers
        except Exception as e:
            logger.error(f"Ошибка получения принтеров: {e}")
            return []

    def get_printer_status(self, device_id):
        if not self.client:
            return {}
        with self._lock:
            return self._status_cache.get(device_id, {})
