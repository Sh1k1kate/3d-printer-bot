import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, CREDENTIALS_FILE
from datetime import datetime, timezone, timedelta
import time
import re
import os
import json
import threading
import functools
import logging
from production import normalize_position, distribute_printed, plan_set_ordered

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))


def moscow_now():
    return datetime.now(MOSCOW_TZ)


PRICE_COLUMNS = ["Название", "Описание", "Фото (URL)", "Розница", "Опт", "Опт от (шт)", "Категория", "ID"]
PRICE_ID_COL = 8   # столбец H: постоянный ID товара (не зависит от номера строки)

# Запись в таблицу идёт «прочитал → изменил → записал», поэтому параллельные запросы
# (потоки FastAPI + бот) сериализуем одним блокирующим замком.
_WRITE_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _WRITE_LOCK:
            return fn(*args, **kwargs)
    return wrapper
PROMO_COLUMNS = ["code", "discount_percent", "valid_until", "max_uses", "used_count", "active"]
REVIEW_COLUMNS = ["id", "product_row", "name", "rating", "text", "created", "status"]
SHIPMENT_COLUMNS = ["Позиция", "Точка", "Отправлено"]


class SheetManager:
    _instance = None
    _cache = {}
    _cache_ttl = 10

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        if creds_json:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(creds_json), scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        self.client = gspread.authorize(creds)
        self.sheet = self.client.open_by_key(SPREADSHEET_ID)

        self.sheet_models = self._ensure_worksheet(
            "Время печати", rows=1000, cols=6,
            header=["Название", "Детали", "Кол-во на палете", "Нужно на шт.", "Время палета (мин)", "Грамм на палет"],
        )
        self.sheet_orders = self._ensure_worksheet(
            "Заказы", rows=1000, cols=8,
            header=["Номер заказа", "Позиция", "Кол-во заказано", "Кол-во напечатано",
                    "Срок заказа", "Дата последнего изменения", "Выполнен", "Заказчик"],
        )
        self.sheet_kits = self._ensure_worksheet(
            "Наборы", rows=100, cols=4,
            header=["Название", "Состав", "Цена", "Описание"],
        )
        self.sheet_log = self._ensure_worksheet(
            "Лог", rows=1000, cols=4,
            header=["Время", "Пользователь", "Действие", "Детали"],
        )
        self.sheet_settings = self._ensure_worksheet(
            "Настройки", rows=100, cols=3,
            header=["user_id", "morning_time", "interval"],
        )
        self.sheet_tasks = self._ensure_worksheet(
            "Задачи", rows=1000, cols=13,
            header=[
                "ID", "Название", "Срок", "Время", "Исполнитель (user_id)",
                "Статус", "Создана", "notified_60", "notified_30", "notified_15",
                "notified_0", "notified_morning", "notified_day",
            ],
        )
        self.sheet_subscribers = self._ensure_worksheet(
            "Подписчики", rows=1000, cols=2,
            header=["user_id", "name"],
        )
        self.sheet_price = self._ensure_worksheet(
            "Прайс", rows=1000, cols=8,
            header=PRICE_COLUMNS,
        )
        try:
            self._migrate_price_ids()
        except Exception as e:
            logger.error(f"Миграция ID прайса не удалась: {e}")
        self.sheet_system = self._ensure_worksheet(
            "Настройки системы", rows=100, cols=2,
            header=["key", "value"],
        )
        self.sheet_promos = self._ensure_worksheet(
            "Промокоды", rows=500, cols=6,
            header=PROMO_COLUMNS,
        )
        self.sheet_reviews = self._ensure_worksheet(
            "Отзывы", rows=2000, cols=7,
            header=REVIEW_COLUMNS,
        )
        self.sheet_shipments = self._ensure_worksheet(
            "Отправки", rows=1000, cols=3,
            header=SHIPMENT_COLUMNS,
        )

    def _ensure_worksheet(self, title, rows, cols, header):
        try:
            return self.sheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            pass
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                time.sleep(2)
                try:
                    return self.sheet.worksheet(title)
                except gspread.exceptions.WorksheetNotFound:
                    pass
            else:
                raise
        try:
            ws = self.sheet.add_worksheet(title=title, rows=rows, cols=cols)
            try:
                ws.append_row(header)
            except Exception as e:
                logger.warning(f"header write '{title}': {e}")
            logger.info(f"Создан лист '{title}'")
            return ws
        except gspread.exceptions.APIError as e:
            if "already exists" in str(e):
                return self.sheet.worksheet(title)
            raise

    @staticmethod
    def _make_cache_key(key, args, kwargs):
        if not args and not kwargs:
            return key
        suffix = [str(a) for a in args]
        suffix += [f"{k}={v}" for k, v in sorted(kwargs.items())]
        return f"{key}({','.join(suffix)})"

    def _get_cached(self, key, fetch_func, *args, **kwargs):
        now = time.time()
        cache_key = self._make_cache_key(key, args, kwargs)
        cache = self._cache.get(cache_key)
        if cache and cache["data"] is not None and (now - cache["timestamp"]) < self._cache_ttl:
            return cache["data"]
        try:
            data = fetch_func(*args, **kwargs)
            self._cache[cache_key] = {"data": data, "timestamp": now}
            return data
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                logger.warning(f"Quota exceeded, using cache for {cache_key}")
                if cache and cache["data"] is not None:
                    return cache["data"]
            raise

    def _invalidate_cache(self, key=None):
        if key:
            for k in list(self._cache.keys()):
                if k == key or k.startswith(f"{key}("):
                    self._cache[k] = {"data": None, "timestamp": 0}
        else:
            self._cache.clear()

    def _fetch_setting(self, key):
        try:
            cell = self.sheet_system.find(str(key), in_column=1)
            if cell:
                row = self.sheet_system.row_values(cell.row)
                if len(row) > 1:
                    return row[1]
        except Exception as e:
            logger.warning(f"get_setting({key}): {e}")
        return ""

    def get_setting(self, key, default=""):
        val = self._get_cached(f"setting:{key}", self._fetch_setting, key)
        return val if val else default

    def set_setting(self, key, value):
        try:
            cell = self.sheet_system.find(str(key), in_column=1)
            if cell:
                self.sheet_system.update_cell(cell.row, 2, str(value))
            else:
                self.sheet_system.append_row([str(key), str(value)])
            self._invalidate_cache(f"setting:{key}")
            return True
        except Exception as e:
            logger.error(f"set_setting({key}): {e}")
            return False

    def delete_setting(self, key):
        try:
            cell = self.sheet_system.find(str(key), in_column=1)
            if cell:
                self.sheet_system.delete_rows(cell.row)
                self._invalidate_cache(f"setting:{key}")
                return True
        except Exception as e:
            logger.error(f"delete_setting({key}): {e}")
        return False

    def log_action(self, user_id, action, details=""):
        try:
            now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet_log.append_row([now_str, user_id, action, details])
        except Exception as e:
            logger.error(f"log: {e}")

    # ---------- Настройки пользователя ----------
    def get_user_settings(self, user_id):
        return self._get_cached(f"user_settings:{user_id}", self._fetch_user_settings, user_id)

    def _fetch_user_settings(self, user_id):
        try:
            cell = self.sheet_settings.find(str(user_id), in_column=1)
            if cell:
                row = self.sheet_settings.row_values(cell.row)
                return {
                    "morning_time": row[1] if len(row) > 1 else "09:00",
                    "interval": row[2] if len(row) > 2 else "60",
                }
        except Exception:
            pass
        return {"morning_time": "09:00", "interval": "60"}

    def set_user_settings(self, user_id, morning_time=None, interval=None):
        try:
            cell = self.sheet_settings.find(str(user_id), in_column=1)
            if cell:
                if morning_time:
                    self.sheet_settings.update_cell(cell.row, 2, morning_time)
                if interval:
                    self.sheet_settings.update_cell(cell.row, 3, interval)
            else:
                self.sheet_settings.append_row([user_id, morning_time or "09:00", interval or "60"])
            self._invalidate_cache(f"user_settings:{user_id}")
            return True
        except Exception as e:
            logger.error(f"set_user_settings: {e}")
            return False

    # ---------- Модели ----------
    def _normalize_rows_with_index(self):
        records = self.sheet_models.get_all_values()
        if len(records) <= 1:
            return []
        result = []
        current_model = None
        for idx, row in enumerate(records[1:], start=2):
            if row and row[0] and row[0].strip():
                current_model = row[0].strip()
            while len(row) < 6:
                row.append("")
            new_row = [current_model] + row[1:6]
            result.append((idx, new_row))
        return result

    def get_all_models(self):
        rows = self._normalize_rows_with_index()
        return sorted({row[0] for _, row in rows if row[0]})

    def get_model_details_with_rows(self, model_name):
        rows = self._normalize_rows_with_index()
        details = []
        for row_idx, row in rows:
            if row[0] == model_name:
                det_name = row[1] if len(row) > 1 else ""
                if not det_name:
                    continue
                try: on_pallet = int(float(row[2])) if row[2] else 0
                except: on_pallet = 0
                try: per_unit = int(float(row[3])) if row[3] else 0
                except: per_unit = 0
                try: time_pp = int(float(row[4])) if row[4] else 0
                except: time_pp = 0
                try: grams_pp = int(float(row[5])) if len(row) > 5 and row[5] else 0
                except: grams_pp = 0
                details.append((row_idx, det_name, on_pallet, per_unit, time_pp, grams_pp))
        return details

    def get_model_details(self, model_name):
        return [(d, op, pu, tp, gp) for (_, d, op, pu, tp, gp) in self.get_model_details_with_rows(model_name)]

    def get_part_row_and_data(self, model_name, det_name):
        for row_idx, d_name, on_pallet, per_unit, time_pp, grams_pp in self.get_model_details_with_rows(model_name):
            if d_name == det_name:
                return row_idx, on_pallet, per_unit, time_pp, grams_pp
        return None

    def update_part_field(self, row_index, field, new_value):
        col_map = {'name': 2, 'on_pallet': 3, 'per_unit': 4, 'time': 5, 'grams': 6}
        col = col_map.get(field)
        if not col:
            return False
        try:
            self.sheet_models.update_cell(row_index, col, str(new_value))
            self._invalidate_cache()
            return True
        except Exception as e:
            logger.error(f"update_part_field: {e}")
            return False

    def add_model(self, model_name, details):
        all_rows = self.sheet_models.get_all_values()
        start_row = len(all_rows) + 1
        rows_to_add = []
        for i, (det_name, on_pallet, per_unit, time_pp, grams_pp) in enumerate(details):
            row = [""] * 6
            if i == 0:
                row[0] = model_name
            row[1] = det_name
            row[2] = on_pallet
            row[3] = per_unit
            row[4] = time_pp
            row[5] = grams_pp
            rows_to_add.append(row)
        end_row = start_row + len(rows_to_add) - 1
        self.sheet_models.update(f"A{start_row}:F{end_row}", rows_to_add, value_input_option="RAW")
        self._invalidate_cache()
        self.log_action("system", "Добавление модели", model_name)

    @_locked
    def delete_part(self, model_name, det_name):
        records = self.sheet_models.get_all_values()
        for row_idx, row in self._normalize_rows_with_index():
            if row[0] == model_name and row[1] == det_name:
                raw = records[row_idx - 1]
                owns_name = bool(raw and raw[0] and raw[0].strip())
                if owns_name and row_idx < len(records):
                    nxt = records[row_idx]
                    # у следующей детали пустое имя модели — оно «наследуется» от удаляемой строки,
                    # поэтому переносим название модели вниз, иначе остальные детали осиротеют
                    if not (nxt and nxt[0] and nxt[0].strip()) and any((c or "").strip() for c in nxt[1:]):
                        self.sheet_models.update_cell(row_idx + 1, 1, model_name)
                self.sheet_models.delete_rows(row_idx)
                self._invalidate_cache()
                return True
        return False

    # ---------- Наборы ----------
    def get_all_kits(self):
        records = self.sheet_kits.get_all_values()
        if len(records) <= 1:
            return []
        return [row[0] for row in records[1:] if row and row[0]]

    def get_kit_details(self, kit_name):
        for row in self.sheet_kits.get_all_values()[1:]:
            if row and row[0] == kit_name:
                return (row[0], row[1] if len(row) > 1 else "",
                        row[2] if len(row) > 2 else "",
                        row[3] if len(row) > 3 else "")
        return None

    def add_kit(self, kit_name, items_text, price, description):
        self.sheet_kits.append_row([kit_name, items_text, price, description])
        self._invalidate_cache()
        self.log_action("system", "Добавление набора", kit_name)

    def update_kit_field(self, kit_name, field, new_value):
        col_map = {'name': 1, 'items': 2, 'price': 3, 'desc': 4}
        col = col_map.get(field)
        if not col:
            return False
        cell = self.sheet_kits.find(kit_name, in_column=1)
        if not cell:
            return False
        self.sheet_kits.update_cell(cell.row, col, str(new_value))
        self._invalidate_cache()
        return True

    def delete_kit(self, kit_name):
        cell = self.sheet_kits.find(kit_name, in_column=1)
        if cell:
            self.sheet_kits.delete_rows(cell.row)
            self._invalidate_cache()
            return True
        return False

    def parse_kit_items(self, kit_name):
        kit_data = self.get_kit_details(kit_name)
        if not kit_data:
            return []
        items_str = kit_data[1]
        if not items_str:
            return []
        items = []
        for part in items_str.split(','):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(.*?)\s*[xXхХ×]\s*(\d+)$", part)
            if m:
                name, qty_str = m.group(1), m.group(2)
            else:
                space_idx = part.rfind(' ')
                if space_idx == -1:
                    continue
                name = part[:space_idx]
                qty_str = part[space_idx + 1:]
            try:
                qty = int(qty_str.strip())
            except:
                continue
            items.append((name.strip(), qty))
        return items

    # ---------- Заказы ----------
    def get_next_order_number(self):
        records = self.sheet_orders.get_all_values()
        if len(records) <= 1:
            return 1
        max_num = 0
        for row in records[1:]:
            try:
                num = int(row[0])
                if num > max_num:
                    max_num = num
            except:
                continue
        return max_num + 1

    @_locked
    def add_order(self, position, quantity, deadline_str, customer=""):
        order_num = self.get_next_order_number()
        now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
        self.sheet_orders.append_row([order_num, position, quantity, 0, deadline_str, now_str, "Нет", customer])
        self._invalidate_cache("orders")
        self.log_action("system", f"Создание заказа №{order_num}", f"{position} x{quantity} для {customer}")
        return order_num

    def _fetch_orders(self):
        records = self.sheet_orders.get_all_values()
        if len(records) <= 1:
            return []
        result = []
        for row in records[1:]:
            while len(row) < 8:
                row.append("")
            result.append(row)
        return result

    def get_user_orders(self):
        return self._get_cached("orders", self._fetch_orders)

    def get_active_orders(self):
        return [o for o in self.get_user_orders() if len(o) >= 7 and o[6].strip().lower() != 'да']

    @_locked
    def update_order_printed(self, order_num, printed_qty):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            self.sheet_orders.update_cell(cell.row, 4, printed_qty)
            self.sheet_orders.update_cell(cell.row, 6, moscow_now().strftime("%Y-%m-%d %H:%M:%S"))
            self._invalidate_cache("orders")
            self.log_action("system", f"Обновление печати заказа №{order_num}", f"Напечатано {printed_qty}")
            return True
        return False

    @_locked
    def mark_order_completed(self, order_num):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            self.sheet_orders.update_cell(cell.row, 7, "Да")
            self.sheet_orders.update_cell(cell.row, 6, moscow_now().strftime("%Y-%m-%d %H:%M:%S"))
            self._invalidate_cache("orders")
            self.log_action("system", f"Заказ №{order_num} выполнен", "")
            return True
        return False

    def get_order_by_number(self, order_num):
        for order in self.get_user_orders():
            if order[0] == str(order_num):
                return order
        return None

    # ---------- Задачи ----------
    def get_next_task_id(self):
        records = self.sheet_tasks.get_all_values()
        if len(records) <= 1:
            return 1
        max_id = 0
        for row in records[1:]:
            try:
                tid = int(row[0])
                if tid > max_id:
                    max_id = tid
            except:
                continue
        return max_id + 1

    @_locked
    def add_task(self, title, deadline, time_str, assignee_user_id=None):
        task_id = self.get_next_task_id()
        now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
        row = [task_id, title, deadline, time_str, assignee_user_id if assignee_user_id else "",
               "active", now_str, "0", "0", "0", "0", "0", "0"]
        self.sheet_tasks.append_row(row)
        self._invalidate_cache("tasks")
        self.log_action("system", f"Создание задачи #{task_id}", title)
        return task_id

    def _fetch_tasks(self, user_id=None):
        records = self.sheet_tasks.get_all_values()
        if len(records) <= 1:
            return []
        tasks = []
        for row in records[1:]:
            if len(row) < 7:
                continue
            try:
                task_id = int(row[0])
            except:
                continue
            title = row[1]
            deadline = row[2]
            time_str = row[3] if len(row) > 3 else ""
            assignee = row[4] if row[4] else None
            status = row[5]
            if status != "active":
                continue
            if user_id is not None:
                if assignee is not None and assignee.isdigit() and int(assignee) == user_id:
                    tasks.append((task_id, title, deadline, time_str, assignee, status))
                elif assignee is None:
                    tasks.append((task_id, title, deadline, time_str, assignee, status))
            else:
                tasks.append((task_id, title, deadline, time_str, assignee, status))
        return tasks

    def get_active_tasks(self, user_id=None):
        return self._get_cached("tasks", self._fetch_tasks, user_id)

    def get_task_by_id(self, task_id):
        cell = self.sheet_tasks.find(str(task_id), in_column=1)
        if not cell:
            return None
        row = self.sheet_tasks.row_values(cell.row)
        return {
            "id": int(row[0]), "title": row[1], "deadline": row[2],
            "time": row[3] if len(row) > 3 else "",
            "assignee": row[4] if row[4] else None,
            "status": row[5], "created": row[6],
            "notified_60": row[7] if len(row) > 7 else "0",
            "notified_30": row[8] if len(row) > 8 else "0",
            "notified_15": row[9] if len(row) > 9 else "0",
            "notified_0": row[10] if len(row) > 10 else "0",
            "notified_morning": row[11] if len(row) > 11 else "0",
            "notified_day": row[12] if len(row) > 12 else "0",
        }

    def get_tasks_for_notification(self):
        records = self.sheet_tasks.get_all_values()
        if len(records) <= 1:
            return []
        tasks = []
        for row in records[1:]:
            if len(row) < 13 or row[5] != "active":
                continue
            try:
                naive_dt = datetime.strptime(f"{row[2]} {row[3]}", "%Y-%m-%d %H:%M")
                deadline_dt = naive_dt.replace(tzinfo=MOSCOW_TZ)
            except:
                continue
            tasks.append({
                "id": int(row[0]), "title": row[1], "deadline_dt": deadline_dt,
                "assignee": row[4] if row[4] else None,
                "notified_60": row[7] if len(row) > 7 else "0",
                "notified_30": row[8] if len(row) > 8 else "0",
                "notified_15": row[9] if len(row) > 9 else "0",
                "notified_0": row[10] if len(row) > 10 else "0",
                "notified_morning": row[11] if len(row) > 11 else "0",
                "notified_day": row[12] if len(row) > 12 else "0",
            })
        return tasks

    @_locked
    def update_task_notification(self, task_id, field, value):
        col_map = {'notified_60': 8, 'notified_30': 9, 'notified_15': 10,
                   'notified_0': 11, 'notified_morning': 12, 'notified_day': 13}
        col = col_map.get(field)
        if not col:
            return False
        cell = self.sheet_tasks.find(str(task_id), in_column=1)
        if not cell:
            return False
        self.sheet_tasks.update_cell(cell.row, col, str(value))
        self._invalidate_cache("tasks")
        return True

    @_locked
    def update_task_field(self, task_id, field, value):
        col_map = {'assignee': 5, 'status': 6}
        col = col_map.get(field)
        if not col:
            return False
        cell = self.sheet_tasks.find(str(task_id), in_column=1)
        if not cell:
            return False
        self.sheet_tasks.update_cell(cell.row, col, str(value))
        self._invalidate_cache("tasks")
        return True

    # ---------- Подписчики ----------
    def _fetch_all_subscribers(self):
        records = self.sheet_subscribers.get_all_values()
        if len(records) <= 1:
            return []
        return [int(row[0]) for row in records[1:] if row and row[0].isdigit()]

    def _fetch_subscribers_with_names(self):
        records = self.sheet_subscribers.get_all_values()
        if len(records) <= 1:
            return []
        out = []
        for row in records[1:]:
            if row and row[0].isdigit():
                uid = int(row[0])
                name = row[1] if len(row) > 1 and row[1] else f"Пользователь {uid}"
                out.append((uid, name))
        return out

    def get_all_subscribers(self):
        return self._get_cached("subscribers_list", self._fetch_all_subscribers)

    def get_subscribers_with_names(self):
        return self._get_cached("subscribers_names", self._fetch_subscribers_with_names)

    def add_subscriber(self, user_id, name=None):
        try:
            if self.sheet_subscribers.find(str(user_id), in_column=1):
                return False
        except Exception:
            pass
        if not name:
            name = f"Пользователь {user_id}"
        self.sheet_subscribers.append_row([user_id, name])
        self._invalidate_cache("subscribers_list")
        self._invalidate_cache("subscribers_names")
        return True

    def remove_subscriber(self, user_id):
        try:
            cell = self.sheet_subscribers.find(str(user_id), in_column=1)
            if cell:
                self.sheet_subscribers.delete_rows(cell.row)
                self._invalidate_cache("subscribers_list")
                self._invalidate_cache("subscribers_names")
                return True
        except Exception:
            pass
        return False

    # ---------- ПРАЙС ----------
    # У каждого товара есть постоянный ID (столбец H). Наружу (сайт, боты, отзывы, ссылки /share/N)
    # он отдаётся как `row_index` — так что при удалении строк выше ссылки и отзывы не «съезжают».
    # При первой миграции ID = текущий номер строки, поэтому старые ссылки остаются рабочими.
    def _migrate_price_ids(self):
        with _WRITE_LOCK:
            records = self.sheet_price.get_all_values()
            if not records:
                self.sheet_price.append_row(PRICE_COLUMNS)
                return
            header = records[0]
            if len(header) < PRICE_ID_COL or (header[PRICE_ID_COL - 1] or "").strip() != "ID":
                self.sheet_price.update_cell(1, PRICE_ID_COL, "ID")
            used, missing = set(), []
            for idx, row in enumerate(records[1:], start=2):
                if not any((c or "").strip() for c in row[:7]):
                    continue
                raw = str(row[PRICE_ID_COL - 1]).strip() if len(row) >= PRICE_ID_COL else ""
                if raw.isdigit() and int(raw) not in used:
                    used.add(int(raw))
                else:
                    missing.append(idx)
            if not missing:
                return
            updates = []
            for idx in missing:
                new_id = idx if idx not in used else max(used | {len(records)}) + 1
                used.add(new_id)
                updates.append({"range": f"H{idx}", "values": [[new_id]]})
            self.sheet_price.batch_update(updates, value_input_option="RAW")
            self._invalidate_cache("price")
            logger.info(f"Прайс: проставлено ID у {len(updates)} товаров")

    def _next_price_id(self, used_ids, count=1):
        """Следующий ID: не меньше счётчика в настройках, чтобы ID удалённых товаров не переиспользовались."""
        try:
            counter = int(self.get_setting("price_next_id", "0") or 0)
        except ValueError:
            counter = 0
        nxt = max(counter, (max(used_ids) if used_ids else 0) + 1)
        self.set_setting("price_next_id", nxt + count)
        return nxt

    def _price_row_map(self):
        """{id: номер строки} по свежим данным листа (одна читающая операция)."""
        col = self.sheet_price.col_values(PRICE_ID_COL)
        return {int(v): i for i, v in enumerate(col, start=1) if i > 1 and str(v).strip().isdigit()}

    @staticmethod
    def _price_dict(row, price_id, sheet_row):
        row = list(row) + [""] * (7 - len(row))
        return {
            "row_index": price_id,
            "sheet_row": sheet_row,
            "name": row[0], "description": row[1], "photo": row[2],
            "retail": row[3], "wholesale": row[4], "wholesale_from": row[5],
            "category": row[6] or "Без категории",
        }

    def _fetch_price_items(self):
        records = self.sheet_price.get_all_values()
        if len(records) <= 1:
            return []
        items = []
        for idx, row in enumerate(records[1:], start=2):
            if not any((cell or "").strip() for cell in row[:7]):
                continue
            raw_id = str(row[PRICE_ID_COL - 1]).strip() if len(row) >= PRICE_ID_COL else ""
            if not raw_id.isdigit():
                continue   # ещё не прошёл миграцию — появится после следующего запуска
            items.append(self._price_dict(row, int(raw_id), idx))
        return items

    def get_price_items(self):
        return self._get_cached("price", self._fetch_price_items)

    def get_price_item_by_row(self, row_index):
        """row_index здесь — постоянный ID товара."""
        try:
            sheet_row = self._price_row_map().get(int(row_index))
            if not sheet_row:
                return None
            row = self.sheet_price.row_values(sheet_row)
            if not row or not any((c or "").strip() for c in row[:7]):
                return None
            return self._price_dict(row, int(row_index), sheet_row)
        except Exception:
            return None

    @_locked
    def add_price_item(self, name, description="", photo="", retail="", wholesale="", wholesale_from="", category=""):
        if not name:
            return False
        try:
            used = set(self._price_row_map())
            new_id = self._next_price_id(used)
            self.sheet_price.append_row([
                name, description, photo,
                str(retail), str(wholesale), str(wholesale_from),
                category or "Без категории", new_id,
            ], value_input_option="RAW")
            self._invalidate_cache("price")
            self.log_action("system", "Добавление товара в прайс", name)
            return True
        except Exception as e:
            logger.error(f"add_price_item: {e}")
            return False

    @_locked
    def update_price_item(self, row_index, field, value):
        col_map = {'name': 1, 'description': 2, 'photo': 3,
                   'retail': 4, 'wholesale': 5, 'wholesale_from': 6, 'category': 7}
        col = col_map.get(field)
        if not col:
            return False
        try:
            sheet_row = self._price_row_map().get(int(row_index))
            if not sheet_row:
                return False
            self.sheet_price.update_cell(sheet_row, col, str(value))
            self._invalidate_cache("price")
            return True
        except Exception as e:
            logger.error(f"update_price_item: {e}")
            return False

    @_locked
    def update_price_item_fields(self, row_index, fields):
        """Меняет сразу несколько полей одной строкой (один запрос вместо N)."""
        order = ['name', 'description', 'photo', 'retail', 'wholesale', 'wholesale_from', 'category']
        try:
            sheet_row = self._price_row_map().get(int(row_index))
            if not sheet_row:
                return False
            current = self.sheet_price.row_values(sheet_row)
            current = list(current) + [""] * (7 - len(current))
            for i, f in enumerate(order):
                if f in fields:
                    current[i] = str(fields[f])
            self.sheet_price.update(f"A{sheet_row}:G{sheet_row}", [current[:7]], value_input_option="RAW")
            self._invalidate_cache("price")
            return True
        except Exception as e:
            logger.error(f"update_price_item_fields: {e}")
            return False

    def _delete_sheet_rows(self, sheet_rows):
        """Удаляет строки листа «Прайс» одним запросом (с конца, чтобы номера не съезжали)."""
        requests = [{"deleteDimension": {"range": {
            "sheetId": self.sheet_price.id, "dimension": "ROWS",
            "startIndex": r - 1, "endIndex": r}}} for r in sorted(set(sheet_rows), reverse=True)]
        if requests:
            self.sheet.batch_update({"requests": requests})

    @_locked
    def delete_price_item(self, row_index):
        try:
            sheet_row = self._price_row_map().get(int(row_index))
            if not sheet_row:
                return False
            self._delete_sheet_rows([sheet_row])
            self._invalidate_cache("price")
            self.log_action("system", "Удаление товара из прайса", f"ID {row_index}")
            return True
        except Exception as e:
            logger.error(f"delete_price_item: {e}")
            return False

    @_locked
    def delete_price_items(self, rows):
        try:
            rmap = self._price_row_map()
            targets = [rmap[int(r)] for r in set(rows) if int(r) in rmap]
            self._delete_sheet_rows(targets)
        except Exception as e:
            logger.error(f"delete_price_items: {e}")
            return 0
        self._invalidate_cache("price")
        self.log_action("system", "Массовое удаление товаров", f"удалено {len(targets)}")
        return len(targets)

    @_locked
    def set_category_for_rows(self, rows, category):
        try:
            rmap = self._price_row_map()
            targets = [rmap[int(r)] for r in set(rows) if int(r) in rmap]
            if targets:
                self.sheet_price.batch_update(
                    [{"range": f"G{r}", "values": [[category]]} for r in targets],
                    value_input_option="RAW")
        except Exception as e:
            logger.error(f"set_category_for_rows: {e}")
            return 0
        self._invalidate_cache("price")
        self.log_action("system", "Массовая смена категории", f"{len(targets)} товаров → {category}")
        return len(targets)

    @_locked
    def import_price_items(self, items):
        if not items:
            return 0
        all_rows = self.sheet_price.get_all_values()
        used = set(self._price_row_map())
        # следующая свободная строка — по столбцу названий, а не по длине всех значений
        start_row = len(all_rows) + 1
        rows_to_add = []
        first_id = self._next_price_id(used, count=len(items))
        for n, it in enumerate(items):
            new_id = first_id + n
            rows_to_add.append([
                it.get("name", "") or "",
                it.get("description", "") or "",
                it.get("photo", "") or "",
                str(it.get("retail", "") or ""),
                str(it.get("wholesale", "") or ""),
                str(it.get("wholesale_from", "") or ""),
                it.get("category", "") or "Без категории",
                new_id,
            ])
        end_row = start_row + len(rows_to_add) - 1
        try:
            self.sheet_price.update(f"A{start_row}:H{end_row}", rows_to_add, value_input_option="RAW")
            self._invalidate_cache("price")
            self.log_action("system", "Импорт товаров из CSV", f"добавлено {len(rows_to_add)}")
            return len(rows_to_add)
        except Exception as e:
            logger.error(f"import_price_items: {e}")
            raise

    def get_price_categories(self):
        items = self.get_price_items()
        return sorted({it["category"] for it in items if it.get("category")})

    # ---------- ПРОМОКОДЫ ----------
    def _fetch_promos(self):
        records = self.sheet_promos.get_all_values()
        if len(records) <= 1:
            return []
        items = []
        for idx, row in enumerate(records[1:], start=2):
            if not row or not (row[0] or "").strip():
                continue
            while len(row) < 6:
                row.append("")
            try:
                max_uses = int(row[3]) if row[3] else 0
            except:
                max_uses = 0
            try:
                used_count = int(row[4]) if row[4] else 0
            except:
                used_count = 0
            items.append({
                "row_index": idx,
                "code": (row[0] or "").strip(),
                "discount_percent": float(row[1]) if row[1] else 0.0,
                "valid_until": (row[2] or "").strip(),
                "max_uses": max_uses,
                "used_count": used_count,
                "active": (row[5] or "").strip().lower() in ("1", "true", "yes", "да", ""),
            })
        return items

    def get_promos(self):
        return self._get_cached("promos", self._fetch_promos)

    def validate_promo(self, code):
        code = (code or "").strip()
        if not code:
            return {"valid": False, "reason": "Пустой код"}
        normalized = code.upper()
        promos = self.get_promos()
        promo = next((p for p in promos if p["code"].upper() == normalized), None)
        if not promo:
            return {"valid": False, "reason": "Промокод не найден"}
        if not promo["active"]:
            return {"valid": False, "reason": "Промокод отключён"}
        if promo["discount_percent"] <= 0:
            return {"valid": False, "reason": "Некорректная скидка"}
        if promo["valid_until"]:
            try:
                until = datetime.strptime(promo["valid_until"], "%Y-%m-%d").date()
                if datetime.now().date() > until:
                    return {"valid": False, "reason": "Срок действия истёк"}
            except Exception:
                pass
        if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
            return {"valid": False, "reason": "Лимит использований исчерпан"}
        return {
            "valid": True,
            "code": promo["code"],
            "discount_percent": promo["discount_percent"],
            "row_index": promo["row_index"],
        }

    def increment_promo_usage(self, code):
        code = (code or "").strip().upper()
        if not code:
            return False
        promos = self.get_promos()
        promo = next((p for p in promos if p["code"].upper() == code), None)
        if not promo:
            return False
        try:
            new_count = promo["used_count"] + 1
            self.sheet_promos.update_cell(promo["row_index"], 5, str(new_count))
            self._invalidate_cache("promos")
            return True
        except Exception as e:
            logger.error(f"increment_promo_usage: {e}")
            return False

    # ---------- ОТЗЫВЫ (с модерацией) ----------
    def _fetch_all_reviews(self):
        records = self.sheet_reviews.get_all_values()
        if len(records) <= 1:
            return []
        items = []
        for row in records[1:]:
            if not row or not (row[0] or "").strip():
                continue
            while len(row) < 7:
                row.append("")
            try:
                rid = int(row[0])
            except:
                continue
            try:
                product_row = int(row[1])
            except:
                continue
            try:
                rating = int(row[3])
            except:
                rating = 0
            items.append({
                "id": rid,
                "product_row": product_row,
                "name": row[2] or "",
                "rating": max(1, min(5, rating)),
                "text": row[4] or "",
                "created": row[5] or "",
                "status": (row[6] or "pending").strip().lower(),
            })
        return items

    def get_all_reviews(self):
        return self._get_cached("reviews", self._fetch_all_reviews)

    def get_reviews_for_product(self, product_row, limit=20):
        reviews = self.get_all_reviews()
        filtered = [r for r in reviews if r["product_row"] == product_row and r["status"] == "approved"]
        filtered.sort(key=lambda r: r.get("created", ""), reverse=True)
        return filtered[:limit]

    def get_pending_reviews(self):
        reviews = self.get_all_reviews()
        pending = [r for r in reviews if r["status"] == "pending"]
        pending.sort(key=lambda r: r.get("created", ""), reverse=True)
        return pending

    def get_reviews_pending_count(self):
        return len(self.get_pending_reviews())

    def get_reviews_summary(self):
        reviews = self.get_all_reviews()
        summary = {}
        for r in reviews:
            if r["status"] != "approved":
                continue
            key = r["product_row"]
            if key not in summary:
                summary[key] = {"count": 0, "sum": 0}
            summary[key]["count"] += 1
            summary[key]["sum"] += r["rating"]
        result = {}
        for k, v in summary.items():
            result[str(k)] = {
                "count": v["count"],
                "avg": round(v["sum"] / v["count"], 1) if v["count"] else 0,
            }
        return result

    @_locked
    def add_review(self, product_row, name, rating, text):
        rating = max(1, min(5, int(rating)))
        text = (text or "").strip()[:1000]
        name = (name or "Аноним").strip()[:100]
        if not text:
            return False
        all_reviews = self.get_all_reviews()
        next_id = 1
        if all_reviews:
            try:
                next_id = max(r["id"] for r in all_reviews) + 1
            except Exception:
                next_id = len(all_reviews) + 1
        try:
            self.sheet_reviews.append_row([
                next_id, product_row, name, rating, text,
                moscow_now().strftime("%Y-%m-%d %H:%M"), "pending",
            ])
            self._invalidate_cache("reviews")
            return True
        except Exception as e:
            logger.error(f"add_review: {e}")
            return False

    def _find_review_row(self, review_id):
        try:
            cell = self.sheet_reviews.find(str(review_id), in_column=1)
            if cell:
                return cell.row
        except Exception as e:
            logger.error(f"_find_review_row({review_id}): {e}")
        return None

    def approve_review(self, review_id):
        row = self._find_review_row(review_id)
        if not row:
            return False
        try:
            self.sheet_reviews.update_cell(row, 7, "approved")
            self._invalidate_cache("reviews")
            return True
        except Exception as e:
            logger.error(f"approve_review: {e}")
            return False

    def reject_review(self, review_id):
        row = self._find_review_row(review_id)
        if not row:
            return False
        try:
            self.sheet_reviews.delete_rows(row)
            self._invalidate_cache("reviews")
            return True
        except Exception as e:
            logger.error(f"reject_review: {e}")
            return False

    def delete_review(self, review_id):
        return self.reject_review(review_id)

    # ---------- ОТПРАВКИ (сколько позиции ушло в каждую точку) ----------
    def _fetch_shipments(self):
        records = self.sheet_shipments.get_all_values()
        result = {}
        for row in records[1:]:
            if len(row) < 3 or not (row[0] or "").strip():
                continue
            try:
                qty = int(float(row[2]))
            except (ValueError, TypeError):
                qty = 0
            result[(row[0].strip().lower(), (row[1] or "").strip().lower())] = qty
        return result

    def get_shipments(self):
        """{(позиция_lower, точка_lower): количество}"""
        return self._get_cached("shipments", self._fetch_shipments)

    @_locked
    def set_shipment(self, position, location, qty):
        position = (position or "").strip()
        location = (location or "").strip()
        if not position or not location:
            return False
        qty = max(0, int(qty))
        try:
            records = self.sheet_shipments.get_all_values()
            for idx, row in enumerate(records[1:], start=2):
                if (len(row) >= 2
                        and row[0].strip().lower() == position.lower()
                        and row[1].strip().lower() == location.lower()):
                    self.sheet_shipments.update_cell(idx, 3, qty)
                    break
            else:
                self.sheet_shipments.append_row([position, location, qty])
            self._invalidate_cache("shipments")
            self.log_action("system", "Отправка", f"{position} → {location}: {qty}")
            return True
        except Exception as e:
            logger.error(f"set_shipment: {e}")
            return False

    @_locked
    def add_shipments_batch(self, items):
        """Прибавляет количества к отправкам одним пакетом запросов.

        items — [(позиция, точка, количество)]; повторы суммируются.
        Возвращает {(позиция_lower, точка_lower): новое_значение}.
        """
        delta = {}
        names = {}
        for position, location, qty in items:
            key = (position.strip().lower(), location.strip().lower())
            delta[key] = delta.get(key, 0) + int(qty)
            names[key] = (position.strip(), location.strip())

        records = self.sheet_shipments.get_all_values()
        existing = {}
        for idx, row in enumerate(records[1:], start=2):
            if len(row) >= 2 and row[0].strip():
                try:
                    cur = int(float(row[2])) if len(row) > 2 and row[2] else 0
                except (ValueError, TypeError):
                    cur = 0
                existing[(row[0].strip().lower(), row[1].strip().lower())] = (idx, cur)

        updates, new_rows, result = [], [], {}
        for key, add in delta.items():
            if key in existing:
                idx, cur = existing[key]
                result[key] = cur + add
                updates.append({"range": f"C{idx}", "values": [[result[key]]]})
            else:
                result[key] = add
                new_rows.append([names[key][0], names[key][1], add])
        if updates:
            self.sheet_shipments.batch_update(updates, value_input_option="RAW")
        if new_rows:
            self.sheet_shipments.append_rows(new_rows, value_input_option="RAW")
        self._invalidate_cache("shipments")
        self.log_action("system", "Отправки (вставка текста)", f"{len(delta)} поз., {sum(delta.values())} шт")
        return result

    @_locked
    def add_orders_batch(self, items):
        """Создаёт несколько заказов одним запросом.

        items — [(позиция, заказано, напечатано, срок "YYYY-MM-DD", заказчик)].
        Возвращает список номеров созданных заказов.
        """
        if not items:
            return []
        records = self.sheet_orders.get_all_values()
        last = 0
        for row in records[1:]:
            try:
                last = max(last, int(row[0]))
            except (ValueError, TypeError, IndexError):
                continue
        now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
        rows, nums = [], []
        for position, ordered, printed, deadline, customer in items:
            last += 1
            nums.append(last)
            rows.append([last, position, int(ordered), int(printed), deadline, now_str, "Нет", customer])
        self.sheet_orders.append_rows(rows, value_input_option="RAW")
        self._invalidate_cache("orders")
        self.log_action("system", "Создание заказов (страница допечатки)",
                        ", ".join(f"№{n} {r[1]} x{r[2]}" for n, r in zip(nums, rows)))
        return nums

    @_locked
    def close_position_orders(self, position_lower):
        """Помечает выполненными все активные заказы позиции. Возвращает, сколько закрыто."""
        records = self.sheet_orders.get_all_values()
        now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
        updates, closed = [], 0
        for idx, row in enumerate(records[1:], start=2):
            row = row + [""] * (8 - len(row))
            if row[6].strip().lower() == "да" or normalize_position(row[1]).lower() != position_lower:
                continue
            updates.append({"range": f"G{idx}", "values": [["Да"]]})
            updates.append({"range": f"F{idx}", "values": [[now_str]]})
            closed += 1
        if updates:
            self.sheet_orders.batch_update(updates, value_input_option="RAW")
            self._invalidate_cache("orders")
            self.log_action("system", "Закрытие позиции (страница допечатки)", f"{position_lower}: {closed} зак.")
        return closed

    @_locked
    def set_position_ordered(self, position_lower, new_total):
        """Ставит суммарное «заказано» по позиции (см. plan_set_ordered).

        Возвращает {"before": было, "after": стало}. ValueError — если нельзя (текст пригоден для показа).
        """
        records = self.sheet_orders.get_all_values()
        orders = []
        for idx, row in enumerate(records[1:], start=2):
            row = row + [""] * (8 - len(row))
            if row[6].strip().lower() == "да" or normalize_position(row[1]).lower() != position_lower:
                continue
            try:
                ordered, printed = int(float(row[2])), int(float(row[3] or 0))
            except (ValueError, TypeError):
                continue
            orders.append({"id": row[0], "row": idx, "ordered": ordered, "printed": printed, "deadline": row[4].strip()})
        before = sum(o["ordered"] for o in orders)
        changes = plan_set_ordered(orders, new_total)
        if changes:
            now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
            updates = []
            for c in changes:
                updates.append({"range": f"C{c['row']}", "values": [[c["ordered"]]]})
                updates.append({"range": f"F{c['row']}", "values": [[now_str]]})
                if c.get("close"):
                    updates.append({"range": f"G{c['row']}", "values": [["Да"]]})
            self.sheet_orders.batch_update(updates, value_input_option="RAW")
            self._invalidate_cache("orders")
            self.log_action("system", "Изменение «заказано» (страница допечатки)", f"{position_lower}: {before} → {new_total}")
        return {"before": before, "after": new_total}

    @_locked
    def add_printed_batch(self, qty_by_position):
        """Прибавляет напечатанное к активным заказам позиций (сначала ближайший срок).

        qty_by_position — {название_позиции_lower: сколько_штук}.
        Возвращает {"added": {название_lower: добавлено}, "leftover": {название_lower: не влезло}}.
        """
        records = self.sheet_orders.get_all_values()
        by_pos = {}
        for idx, row in enumerate(records[1:], start=2):
            row = row + [""] * (8 - len(row))
            if row[6].strip().lower() == "да":
                continue
            key = normalize_position(row[1]).lower()
            if key not in qty_by_position:
                continue
            try:
                ordered, printed = int(float(row[2])), int(float(row[3] or 0))
            except (ValueError, TypeError):
                continue
            by_pos.setdefault(key, []).append(
                {"id": row[0], "row": idx, "ordered": ordered, "printed": printed, "deadline": row[4].strip()}
            )

        now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
        updates, added, leftover = [], {}, {}
        for key, qty in qty_by_position.items():
            changes, left = distribute_printed(by_pos.get(key, []), qty)
            for c in changes:
                updates.append({"range": f"D{c['row']}", "values": [[c["printed"]]]})
                updates.append({"range": f"F{c['row']}", "values": [[now_str]]})
            added[key] = sum(c["added"] for c in changes)
            if left:
                leftover[key] = left
        if updates:
            self.sheet_orders.batch_update(updates, value_input_option="RAW")
        self._invalidate_cache("orders")
        self.log_action("system", "Напечатано (вставка текста)", f"{sum(added.values())} шт по {len(added)} поз.")
        return {"added": added, "leftover": leftover}

    # ---------- Заглушки ----------
    def init_tasks_sheet(self): pass
    def init_subscribers_sheet(self): pass
    def init_price_sheet(self): pass
    def init_sheet(self): pass

    def get_all_items(self):
        return self.get_all_models(), self.get_all_kits()
