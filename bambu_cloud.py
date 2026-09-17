import logging
import threading
import time
from config import BAMBU_EMAIL, BAMBU_PASSWORD, BAMBU_TOKEN, BAMBU_REGION

logger = logging.getLogger(__name__)


class BambuCloudManager:
    """
    Обёртка для bambu-lab-cloud-api с поддержкой MQTT.
    Получает список принтеров через REST и данные AMS через MQTT в реальном времени.
    """

    def __init__(self):
        self.client = None
        self.mqtt = None
        self.ams_cache = {}          # device_id -> данные AMS
        self.ams_timestamp = {}      # device_id -> время последнего обновления
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
                self.client = BambuClient(token=token)
                logger.info("Bambu Cloud client успешно инициализирован")
                self._start_mqtt()
            else:
                logger.warning("Bambu Cloud токен не получен. Проверьте BAMBU_TOKEN.")
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
        """Постоянное подключение к MQTT с переподключением."""
        while self._running:
            try:
                from bambulab import MQTTClient

                user_info = self.client.get_user_info()
                uid = user_info.get("uid")
                if not uid:
                    logger.error("Не удалось получить UID пользователя для MQTT")
                    time.sleep(30)
                    continue

                mqtt = MQTTClient(
                    username=uid,
                    access_token=self.client.token,
                    device_id=None,
                    on_message=self._on_mqtt_message
                )
                logger.info("Подключаемся к MQTT Bambu Lab...")
                mqtt.connect(blocking=True)
            except Exception as e:
                logger.error(f"Ошибка MQTT: {e}. Переподключение через 30 сек...")
                time.sleep(30)

    def _on_mqtt_message(self, device_id, data):
        """Обрабатывает входящие MQTT-сообщения и сохраняет данные AMS."""
        try:
            if not data or "print" not in data:
                return
            print_data = data["print"]

            # Основные поля статуса
            with self._lock:
                if "ams" in print_data:
                    ams = print_data["ams"]
                    trays = []
                    for unit in ams.get("ams", []):
                        for tray in unit.get("tray", []):
                            # Пропускаем пустые слоты
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
                    self.ams_cache[device_id] = trays
                    self.ams_timestamp[device_id] = time.time()

                # Обновляем статус печати, если пришёл
                if "gcode_state" in print_data:
                    if not hasattr(self, "_status_cache"):
                        self._status_cache = {}
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
            now = time.time()
            for d in devices:
                device_id = d.get("dev_id")
                name = d.get("name")

                # Данные AMS из MQTT-кэша
                with self._lock:
                    trays = self.ams_cache.get(device_id, [])
                    last_update = self.ams_timestamp.get(device_id, 0)
                    status_cache = getattr(self, "_status_cache", {}).get(device_id, {})

                # Если данные MQTT ещё не пришли, берём из REST (базовые)
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

                # Определяем статус (из MQTT или из REST)
                status = status_cache.get("gcode_state") or d.get("print_status", "UNKNOWN")
                progress = status_cache.get("mc_percent") or d.get("print_progress", 0)
                remaining = status_cache.get("mc_remaining_time")

                printers.append({
                    "id": device_id,
                    "name": name,
                    "status": status,
                    "progress": progress,
                    "model": d.get("dev_model_name"),
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
