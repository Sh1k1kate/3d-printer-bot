import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, CREDENTIALS_FILE
from datetime import datetime

class SheetManager:
    def __init__(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        self.client = gspread.authorize(creds)
        self.sheet_models = self.client.open_by_key(SPREADSHEET_ID).worksheet("Время печати")
        self.sheet_orders = self.client.open_by_key(SPREADSHEET_ID).worksheet("Заказы")
        try:
            self.sheet_kits = self.client.open_by_key(SPREADSHEET_ID).worksheet("Наборы")
        except gspread.exceptions.WorksheetNotFound:
            self.sheet_kits = self.client.open_by_key(SPREADSHEET_ID).add_worksheet(title="Наборы", rows=100, cols=4)
            self.sheet_kits.append_row(["Название", "Состав", "Цена", "Описание"])

    # ---------- Модели ----------
    def _normalize_rows_with_index(self):
        records = self.sheet_models.get_all_values()
        if len(records) <= 1:
            return []
        result = []
        current_model = None
        for idx, row in enumerate(records[1:], start=2):
            if row[0] and row[0].strip():
                current_model = row[0].strip()
            while len(row) < 6:
                row.append("")
            new_row = [current_model] + row[1:6]
            result.append((idx, new_row))
        return result

    def get_all_models(self):
        rows = self._normalize_rows_with_index()
        models = set()
        for _, row in rows:
            if row[0]:
                models.add(row[0])
        return sorted(list(models))

    def get_model_details_with_rows(self, model_name):
        rows = self._normalize_rows_with_index()
        details = []
        for row_idx, row in rows:
            if row[0] == model_name:
                det_name = row[1] if len(row) > 1 else ""
                if not det_name:
                    continue
                try:
                    on_pallet = int(float(row[2])) if row[2] else 0
                except:
                    on_pallet = 0
                try:
                    per_unit = int(float(row[3])) if row[3] else 0
                except:
                    per_unit = 0
                try:
                    time_pp = int(float(row[4])) if row[4] else 0
                except:
                    time_pp = 0
                try:
                    grams_pp = int(float(row[5])) if len(row) > 5 and row[5] else 0
                except:
                    grams_pp = 0
                details.append((row_idx, det_name, on_pallet, per_unit, time_pp, grams_pp))
        return details

    def get_model_details(self, model_name):
        details_with_rows = self.get_model_details_with_rows(model_name)
        return [(det_name, on_pallet, per_unit, time_pp, grams_pp)
                for (_, det_name, on_pallet, per_unit, time_pp, grams_pp) in details_with_rows]

    def get_part_row_and_data(self, model_name, det_name):
        details = self.get_model_details_with_rows(model_name)
        for row_idx, d_name, on_pallet, per_unit, time_pp, grams_pp in details:
            if d_name == det_name:
                return row_idx, on_pallet, per_unit, time_pp, grams_pp
        return None

    def update_part_field(self, row_index, field, new_value):
        col_map = {'name': 2, 'on_pallet': 3, 'per_unit': 4, 'time': 5, 'grams': 6}
        col = col_map.get(field)
        if not col:
            return False
        value_to_write = str(new_value)
        try:
            self.sheet_models.update_cell(row_index, col, value_to_write)
            return True
        except Exception as e:
            print(f"Error updating {field} at {col}{row_index}: {e}")
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
        cell_range = f"A{start_row}:F{end_row}"
        self.sheet_models.update(cell_range, rows_to_add, value_input_option="USER_ENTERED")

    # ---------- Наборы ----------
    def get_all_kits(self):
        records = self.sheet_kits.get_all_values()
        if len(records) <= 1:
            return []
        return [row[0] for row in records[1:] if row and row[0]]

    def get_kit_details(self, kit_name):
        records = self.sheet_kits.get_all_values()
        for row in records[1:]:
            if row and row[0] == kit_name:
                return (row[0], row[1] if len(row) > 1 else "", row[2] if len(row) > 2 else "", row[3] if len(row) > 3 else "")
        return None

    def add_kit(self, kit_name, items_text, price, description):
        self.sheet_kits.append_row([kit_name, items_text, price, description])

    def update_kit_field(self, kit_name, field, new_value):
        col_map = {'name': 1, 'items': 2, 'price': 3, 'desc': 4}
        col = col_map.get(field)
        if not col:
            return False
        cell = self.sheet_kits.find(kit_name, in_column=1)
        if not cell:
            return False
        self.sheet_kits.update_cell(cell.row, col, str(new_value))
        return True

    def delete_kit(self, kit_name):
        cell = self.sheet_kits.find(kit_name, in_column=1)
        if cell:
            self.sheet_kits.delete_rows(cell.row)
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
                qty_str = part[space_idx+1:]
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

    def add_order(self, position, quantity, deadline_str):
        order_num = self.get_next_order_number()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [order_num, position, quantity, 0, deadline_str, now_str, "Нет"]
        self.sheet_orders.append_row(row)
        return order_num

    def get_user_orders(self):
        records = self.sheet_orders.get_all_values()
        if len(records) <= 1:
            return []
        return records[1:]

    def get_active_orders(self):
        all_orders = self.get_user_orders()
        active = []
        for order in all_orders:
            if len(order) >= 7:
                status = order[6].strip().lower()
                if status != 'да':
                    active.append(order)
        return active

    def update_order_printed(self, order_num, printed_qty):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            self.sheet_orders.update_cell(cell.row, 4, printed_qty)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet_orders.update_cell(cell.row, 6, now_str)
            return True
        return False

    def mark_order_completed(self, order_num):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            self.sheet_orders.update_cell(cell.row, 7, "Да")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.sheet_orders.update_cell(cell.row, 6, now_str)
            return True
        return False

    def get_order_by_number(self, order_num):
        cell = self.sheet_orders.find(str(order_num), in_column=1)
        if cell:
            row = self.sheet_orders.row_values(cell.row)
            return row
        return None

    # ---------- Общие ----------
    def get_all_items(self):
        return self.get_all_models(), self.get_all_kits()

    def init_sheet(self):
        if not self.sheet_models.get_all_values():
            headers = ["Название", "Детали", "Кол-во на палете", "Нужно на шт.", "Время палета (мин)", "Грамм на палет"]
            self.sheet_models.append_row(headers)
        if not self.sheet_orders.get_all_values():
            order_headers = ["Номер заказа", "Позиция", "Кол-во заказано", "Кол-во напечатано", "Срок заказа", "Дата последнего изменения", "Выполнен"]
            self.sheet_orders.append_row(order_headers)
        try:
            self.sheet_kits = self.client.open_by_key(SPREADSHEET_ID).worksheet("Наборы")
        except gspread.exceptions.WorksheetNotFound:
            self.sheet_kits = self.client.open_by_key(SPREADSHEET_ID).add_worksheet(title="Наборы", rows=100, cols=4)
            self.sheet_kits.append_row(["Название", "Состав", "Цена", "Описание"])