import logging
import threading
import time
from config import BAMBU_EMAIL, BAMBU_PASSWORD, BAMBU_TOKEN, BAMBU_REGION

logger = logging.getLogger(__name__)


class BambuCloudManager:
    """
    Обёртка для bambu-lab-cloud-api с поддержкой облачного MQTT.
    Получает список принтеров через REST и данные AMS через MQTT в реальном времени.
    Не требует LAN-режима и локального сервера — работает через облако Bambu Lab.
    """

    def __init__(self):
        self.client = None
        self.mqtt = None
        self.ams_cache = {}          # device_id -> список катушек
        self.ams_timestamp = {}      # device_id -> время последнего обновления
        self._status_cache = {}      # device_id -> статус печати из MQTT
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
                # ✅ Приводим токен к строке (может прийти int)
                self.client = BambuClient(token=str(token))
                logger.info("Bambu Cloud client успешно инициализирован")
                self._start_mqtt()
            else:
                logger.warning("Bambu Cloud токен не получен. Проверьте BAMBU_TOKEN или BAMBU_EMAIL/BAMBU_PASSWORD.")
        except Exception as e:
            logger.error(f"Ошибка инициализации Bambu Cloud: {e}")
            self.client = None

    def _start_mqtt(self):
        """Запускает фоновый поток с MQTT-подпиской."""
        if not self.client:
            return
        self._running = True
        self._mqtt_thread = threading.Thread(target=self._mqtt_loop, daemon=True)
        self._mqtt_thread.start()
        logger.info("MQTT поток запущен")

    def _mqtt_loop(self):
        """Постоянное подключение к облачному MQTT Bambu Lab с переподключением."""
        while self._running:
            try:
                from bambulab import MQTTClient

                # Получаем данные пользователя
                try:
                    user_info = self.client.get_user_info()
                except Exception as e:
                    logger.error(f"Не удалось получить user_info: {e}")
                    time.sleep(30)
                    continue

                # Достаём uid надёжно
                if isinstance(user_info, dict):
                    uid = user_info.get("uid") or user_info.get("user_id") or user_info.get("id")
                else:
                    uid = getattr(user_info, "uid", None)

                if not uid:
                    logger.error(f"UID не найден в user_info: {user_info}")
                    time.sleep(30)
                    continue

                # ✅ Приводим все параметры к строкам
                uid_str = str(uid).strip()
                token_str = str(getattr(self.client, "token", "")).strip()

                logger.info(f"MQTT подключение: uid={uid_str}, token_len={len(token_str)}")

                mqtt = MQTTClient(
                    username=uid_str,
                    access_token=token_str,
                    on_message=self._on_mqtt_message
                )
                logger.info("Подключаемся к MQTT Bambu Lab...")
                mqtt.connect(blocking=True)
            except Exception as e:
                logger.error(f"Ошибка MQTT: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(30)

    def _on_mqtt_message(self, device_id, data):
        """Обрабатывает входящие MQTT-сообщения и сохраняет данные AMS."""
        try:
            if not data or "print" not in data:
                return
            print_data = data["print"]

            with self._lock:
                # AMS данные
                if "ams" in print_data:
                    ams = print_data["ams"]
                    trays = []
                    for unit in ams.get("ams", []):
                        for tray in unit.get("tray", []):
                            if tray.get("state") == 0 or tray.get("tray_type") == "Empty":
                                continue
                            trays.append({
                                "tray_id": tray.get("id"),
                                "type": tray.get("tray_type", "—"),
                                "color": tray.get("tray_color", "00000000"),
                                "remaining": tray.get("remain", 0),
                                "nozzle_temp_min": tray.get("nozzle_temp_min"),
                                "nozzle_temp_max": tray.get("nozzle_temp_max"),
                            })
                    if trays:
                        self.ams_cache[device_id] = trays
                        self.ams_timestamp[device_id] = time.time()
                        logger.debug(f"AMS обновлены для {device_id}: {len(trays)} катушек")

                # Статус печати
                if "gcode_state" in print_data:
                    self._status_cache[device_id] = {
                        "gcode_state": print_data.get("gcode_state"),
                        "mc_percent": print_data.get("mc_percent", 0),
                        "mc_remaining_time": print_data.get("mc_remaining_time"),
                        "subtask_name": print_data.get("subtask_name", ""),
                    }
        except Exception as e:
            logger.error(f"Ошибка обработки MQTT сообщения: {e}")

    def get_printers(self):
        """Возвращает список принтеров с данными AMS из кэша MQTT."""
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

                # Если данных AMS из MQTT ещё нет, пробуем REST (базовые)
                if not trays:
                    try:
                        ams_info = self.client.get_ams_filaments(device_id)
                        trays = []
                        for unit in ams_info.get("ams_units", []):
                            for tray in unit.get("trays", []):
                                trays.append({
                                    "tray_id": tray.get("tray_id"),
                                    "type": tray.get("filament_type", "—"),
                                    "color": tray.get("filament_color", "00000000"),
                                    "remaining": tray.get("remaining", 0),
                                })
                    except Exception:
                        trays = []

                # Статус из MQTT или REST
                status = status_cache.get("gcode_state") or d.get("print_status", "UNKNOWN")
                progress = status_cache.get("mc_percent") or d.get("print_progress", 0)
                remaining = status_cache.get("mc_remaining_time")

                # Сопоставление кодов моделей с человеческими именами
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
                    "status": status,
                    "progress": progress,
                    "model": model_name,
                    "remaining_time": remaining,
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
        """Возвращает детальный статус печати для одного принтера."""
        if not self.client:
            return {}
        with self._lock:
            return self._status_cache.get(device_id, {})
