import logging
import threading
from config import BAMBU_EMAIL, BAMBU_PASSWORD, BAMBU_TOKEN, BAMBU_REGION

logger = logging.getLogger(__name__)


class BambuCloudManager:
    """
    Обёртка для bambu-lab-cloud-api.
    Позволяет получать список принтеров, статус печати и данные о катушках (AMS).
    Импорт библиотеки обёрнут в try/except, чтобы приложение не падало,
    если библиотека не установлена или её API изменился.
    """

    def __init__(self):
        self.client = None
        self._lock = threading.Lock()
        self._init_client()

    def _init_client(self):
        try:
            # Импорт внутри функции, чтобы при отсутствии библиотеки приложение не падало
            from bambulab import BambuClient, BambuAuthenticator
        except ImportError as e:
            logger.warning(f"bambu-lab-cloud-api не установлен или импорт не удался: {e}")
            self.client = None
            return
        except Exception as e:
            logger.error(f"Ошибка импорта bambu-lab-cloud-api: {e}")
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
            else:
                logger.warning("Bambu Cloud токен не получен. Проверьте BAMBU_TOKEN или BAMBU_EMAIL/BAMBU_PASSWORD.")
        except Exception as e:
            logger.error(f"Ошибка инициализации Bambu Cloud: {e}")
            self.client = None

    def get_printers(self):
        with self._lock:
            if not self.client:
                return []
            try:
                devices = self.client.get_devices()
                printers = []
                for d in devices:
                    device_id = d.get("dev_id")
                    ams_info = {}
                    try:
                        ams_info = self.client.get_ams_filaments(device_id)
                    except Exception as e:
                        logger.warning(f"Не удалось получить AMS для {device_id}: {e}")

                    trays = []
                    for unit in ams_info.get("ams_units", []):
                        for tray in unit.get("trays", []):
                            trays.append({
                                "tray_id": tray.get("tray_id"),
                                "type": tray.get("filament_type", "—"),
                                "color": tray.get("filament_color", "#000000"),
                                "remaining_mm": tray.get("remaining", 0),
                                "nozzle_temp_min": tray.get("nozzle_temp_min"),
                                "nozzle_temp_max": tray.get("nozzle_temp_max"),
                            })

                    printers.append({
                        "id": device_id,
                        "name": d.get("name"),
                        "status": d.get("print_status"),
                        "progress": d.get("print_progress", 0),
                        "model": d.get("dev_model_name"),
                        "remaining_time": d.get("remaining_time"),
                        "ams": {
                            "has_ams": ams_info.get("has_ams", False),
                            "total_trays": ams_info.get("total_trays", 0),
                            "trays": trays,
                        }
                    })
                return printers
            except Exception as e:
                logger.error(f"Ошибка получения принтеров: {e}")
                return []

    def get_printer_status(self, device_id):
        with self._lock:
            if not self.client:
                return {}
            try:
                status = self.client.get_print_status()
                if isinstance(status, list):
                    for s in status:
                        if s.get("dev_id") == device_id:
                            return s
                elif isinstance(status, dict) and status.get("dev_id") == device_id:
                    return status
                return {}
            except Exception as e:
                logger.error(f"Ошибка получения статуса: {e}")
                return {}
