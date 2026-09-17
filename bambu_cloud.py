import logging
import threading
import time
import json
import ssl
import paho.mqtt.client as mqtt
from config import BAMBU_EMAIL, BAMBU_PASSWORD, BAMBU_TOKEN, BAMBU_REGION

logger = logging.getLogger(__name__)

MQTT_HOST = "us.mqtt.bambulab.com"
MQTT_PORT = 8883


class BambuCloudManager:
    """
    Обёртка для Bambu Lab Cloud API.
    REST — список принтеров, MQTT (paho) — телеметрия и данные AMS.
    Одно MQTT-соединение на все принтеры через подписку на device/+/report.
    """

    def __init__(self):
        self.client = None
        self.mqtt_client = None
        self.ams_cache = {}          # device_id -> список катушек
        self.ams_timestamp = {}
        self._status_cache = {}      # device_id -> полный статус
        self._lock = threading.Lock()
        self._mqtt_thread = None
        self._running = False
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
            logger.error(f"UID не найден в user_info: {user_info}")
            return None, None

        token = str(getattr(self.client, "token", "")).strip()
        return str(uid).strip(), token

    def _mqtt_loop(self):
        while self._running:
            uid_str, token_str = self._get_credentials()
            if not uid_str or not token_str:
                time.sleep(30)
                continue

            try:
                client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"bambu_{uid_str}",
                    clean_session=True
                )
                client.username_pw_set(f"u_{uid_str}", token_str)
                client.tls_set(cert_reqs=ssl.CERT_NONE)
                client.tls_insecure_set(True)

                client.on_connect = self._on_connect
                client.on_message = self._on_paho_message
                client.on_disconnect = self._on_disconnect

                logger.info(f"MQTT подключение: uid={uid_str}, host={MQTT_HOST}:{MQTT_PORT}")
                client.connect(MQTT_HOST, MQTT_PORT, 60)
                client.loop_forever()
            except Exception as e:
                logger.error(f"Ошибка MQTT: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(30)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("MQTT подключён. Подписываемся на device/+/report")
            client.subscribe("device/+/report")
        else:
            logger.error(f"MQTT ошибка подключения: reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning(f"MQTT отключён: reason_code={reason_code}. Переподключение...")

    def _on_paho_message(self, client, userdata, msg):
        try:
            parts = msg.topic.split("/")
            if len(parts) < 3:
                return
            device_id = parts[1]
            data = json.loads(msg.payload.decode("utf-8"))

            # ✅ Диагностика: логируем первые 800 символов каждого сообщения
            # Уберите, когда увидите нужные поля
            logger.info(f"[MQTT RAW] {device_id}: {json.dumps(data)[:800]}")

            self._process_mqtt_data(device_id, data)
        except Exception as e:
            logger.error(f"Ошибка разбора MQTT сообщения: {e}")

    def _process_mqtt_data(self, device_id, data):
        """Извлекает телеметрию и AMS из сообщения принтера."""
        try:
            if not data or "print" not in data:
                return
            print_data = data["print"]

            with self._lock:
                # ---------- Основной статус ----------
                status = self._status_cache.get(device_id, {})
                if "gcode_state" in print_data:
                    status["gcode_state"] = print_data.get("gcode_state")
                if "mc_percent" in print_data:
                    status["mc_percent"] = print_data.get("mc_percent", 0)
                if "mc_remaining_time" in print_data:
                    status["mc_remaining_time"] = print_data.get("mc_remaining_time")
                if "subtask_name" in print_data:
                    status["subtask_name"] = print_data.get("subtask_name", "")
                if "nozzle_temper" in print_data:
                    status["nozzle_temper"] = print_data.get("nozzle_temper")
                if "nozzle_target_temper" in print_data:
                    status["nozzle_target_temper"] = print_data.get("nozzle_target_temper")
                if "bed_temper" in print_data:
                    status["bed_temper"] = print_data.get("bed_temper")
                if "bed_target_temper" in print_data:
                    status["bed_target_temper"] = print_data.get("bed_target_temper")
                self._status_cache[device_id] = status

                # ---------- AMS ----------
                if "ams" in print_data:
                    ams = print_data["ams"]
                    trays = []
                    for unit in ams.get("ams", []):
                        for tray in unit.get("tray", []):
                            state = tray.get("state", 0)
                            tray_type = tray.get("tray_type", "")
                            # Пропускаем пустые слоты: state=0 или type=Empty
                            if state == 0 or tray_type in (None, "", "Empty"):
                                continue
                            trays.append({
                                "tray_id": tray.get("id"),
                                "type": tray_type,
                                "color": tray.get("tray_color", "00000000"),
                                "remaining": tray.get("remain", 0),
                                "nozzle_temp_min": tray.get("nozzle_temp_min"),
                                "nozzle_temp_max": tray.get("nozzle_temp_max"),
                            })
                    if trays:
                        self.ams_cache[device_id] = trays
                        self.ams_timestamp[device_id] = time.time()
                        logger.info(f"✅ AMS обновлены для {device_id}: {len(trays)} катушек")
                    else:
                        logger.debug(f"AMS пустой для {device_id} (нет активных катушек)")

                # ---------- Внешняя катушка (external spool) ----------
                if "vt_tray" in print_data:
                    vt = print_data["vt_tray"]
                    vt_type = vt.get("tray_type", "")
                    if vt_type and vt_type != "Empty":
                        vt_tray = {
                            "tray_id": 254,
                            "type": vt_type,
                            "color": vt.get("tray_color", "00000000"),
                            "remaining": vt.get("remain", 0),
                        }
                        # Добавляем внешнюю катушку к списку
                        existing = self.ams_cache.get(device_id, [])
                        # Удаляем старую внешнюю катушку, если была
                        existing = [t for t in existing if t.get("tray_id") != 254]
                        existing.append(vt_tray)
                        self.ams_cache[device_id] = existing
                        logger.info(f"✅ Внешняя катушка обновлена для {device_id}: {vt_type}")
        except Exception as e:
            logger.error(f"Ошибка обработки MQTT данных от {device_id}: {e}")

    def get_printers(self):
        """Возвращает список принтеров с полной телеметрией и AMS."""
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

                # Fallback через REST, если MQTT-данных ещё нет
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
                model_map = {
                    "N2S": "A1",
                    "N1": "A1 mini",
                    "C11": "P1P",
                    "C12": "P1S",
                    "BL-P001": "X1 Carbon",
                    "BL-P002": "X1",
                }
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
