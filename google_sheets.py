import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, CREDENTIALS_FILE
from datetime import datetime, timezone, timedelta
import time
import logging

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))


def moscow_now():
    return datetime.now(MOSCOW_TZ)


PRICE_COLUMNS = ["Название", "Описание", "Фото (URL)", "Розница", "Опт", "Опт от (шт)", "Категория"]


class SheetManager:
    # ✅ Настоящий синглтон — один объект на весь процесс
    _instance = None
    _cache = {}
    _cache_ttl = 10

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # __init__ выполнится ровно один раз
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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
            "Прайс", rows=1000, cols=7,
            header=PRICE_COLUMNS,
        )

    # ---------- Безопасное открытие/создание листа ----------
    def _ensure_worksheet(self, title, rows, cols, header):
        """Открывает лист, если есть. Если нет — создаёт с заголовком.
        Устойчиво к гонкам и к 429."""
        try:
            return self.sheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            pass
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                # Квота — подождём и попробуем ещё раз
                time.sleep(2)
                try:
                    return self.sheet.worksheet(title)
                except gspread.exceptions.WorksheetNotFound:
                    pass
            else:
                raise

        # Листа нет — создаём
        try:
            ws = self.sheet.add_worksheet(title=title, rows=rows, cols=cols)
            try:
                ws.append_row(header)
            except Exception as e:
                logger.warning(f"Не удалось записать заголовок листа '{title}': {e}")
            logger.info(f"Создан лист '{title}'")
            return ws
        except gspread.exceptions.APIError as e:
            if "already exists" in str(e):
                # Кто-то успел создать между нашими вызовами — просто открываем
                return self.sheet.worksheet(title)
            raise

    # ---------- Кеширование ----------
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
                logger.warning(f"Quota exceeded, using cached data for {cache_key}")
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

    # ---------- Лог ----------
    def log_action(self, user_id, action, details=""):
        try:
            now_str = moscow_now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet_log.append_row([now_str, user_id, action, details])
        except Exception as e:
            logger.error(f"Ошибка записи лога: {e}")

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
        except Exception as e:
            logger.warning(f"get_user_settings error: {e}")
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
            logger.error(f"Ошибка сохранения настроек: {e}")
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
            logger.error(f"Error updating {field} at {col}{row_index}: {e}")
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
        self.sheet_models.update(f"A{start_row}:F{end_row}", rows_to_add, value_input_option="USER_ENTERED")
        self._invalidate_cache()
        self.log_action("system", "Добавление модели", model_name)

    def delete_part(self, model_name, det_name):
        for row_idx, row in self._normalize_rows_with_index():
            if row[0] == model_name and row[1] == det_name:
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
            if 'x' in part:
                name, qty_str = part.split('x')
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

    def update_order_printed(self, order_num, printed_qty):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            self.sheet_orders.update_cell(cell.row, 4, printed_qty)
            self.sheet_orders.update_cell(cell.row, 6, moscow_now().strftime("%Y-%m-%d %H:%M:%S"))
            self._invalidate_cache("orders")
            self.log_action("system", f"Обновление печати заказа №{order_num}", f"Напечатано {printed_qty}")
            return True
        return False

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
            "id": int(row[0]),
            "title": row[1],
            "deadline": row[2],
            "time": row[3] if len(row) > 3 else "",
            "assignee": row[4] if row[4] else None,
            "status": row[5],
            "created": row[6],
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
    def _fetch_price_items(self):
        records = self.sheet_price.get_all_values()
        if len(records) <= 1:
            return []
        items = []
        for idx, row in enumerate(records[1:], start=2):
            if not any((cell or "").strip() for cell in row):
                continue
            while len(row) < 7:
                row.append("")
            items.append({
                "row_index": idx,
                "name": row[0],
                "description": row[1],
                "photo": row[2],
                "retail": row[3],
                "wholesale": row[4],
                "wholesale_from": row[5],
                "category": row[6] or "Без категории",
            })
        return items

    def get_price_items(self):
        return self._get_cached("price", self._fetch_price_items)

    def get_price_item_by_row(self, row_index):
        try:
            row = self.sheet_price.row_values(row_index)
            if not row or not any((c or "").strip() for c in row):
                return None
            while len(row) < 7:
                row.append("")
            return {
                "row_index": row_index,
                "name": row[0],
                "description": row[1],
                "photo": row[2],
                "retail": row[3],
                "wholesale": row[4],
                "wholesale_from": row[5],
                "category": row[6] or "Без категории",
            }
        except Exception:
            return None

    def add_price_item(self, name, description="", photo="", retail="", wholesale="", wholesale_from="", category=""):
        if not name:
            return False
        try:
            self.sheet_price.append_row([
                name, description, photo,
                str(retail), str(wholesale), str(wholesale_from),
                category or "Без категории",
            ])
            self._invalidate_cache("price")
            self.log_action("system", "Добавление товара в прайс", name)
            return True
        except Exception as e:
            logger.error(f"Ошибка добавления товара: {e}")
            return False

    def update_price_item(self, row_index, field, value):
        col_map = {'name': 1, 'description': 2, 'photo': 3,
                   'retail': 4, 'wholesale': 5, 'wholesale_from': 6, 'category': 7}
        col = col_map.get(field)
        if not col:
            return False
        try:
            self.sheet_price.update_cell(row_index, col, str(value))
            self._invalidate_cache("price")
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления товара: {e}")
            return False

    def delete_price_item(self, row_index):
        try:
            self.sheet_price.delete_rows(row_index)
            self._invalidate_cache("price")
            self.log_action("system", "Удаление товара из прайса", f"строка {row_index}")
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления товара: {e}")
            return False

    def get_price_categories(self):
        items = self.get_price_items()
        return sorted({it["category"] for it in items if it.get("category")})

    # ---------- Заглушки для обратной совместимости ----------
    def init_tasks_sheet(self):
        pass

    def init_subscribers_sheet(self):
        pass

    def init_price_sheet(self):
        pass

    def init_sheet(self):
        pass

    def get_all_items(self):
        return self.get_all_models(), self.get_all_kits()
