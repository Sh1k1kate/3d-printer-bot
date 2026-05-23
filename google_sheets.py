import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, CREDENTIALS_FILE

class SheetManager:
    def __init__(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        self.client = gspread.authorize(creds)
        self.sheet = self.client.open_by_key(SPREADSHEET_ID).sheet1

    def _normalize_rows_with_index(self):
        """
        Возвращает список нормализованных строк (с повторённым названием модели)
        и дополнительно сохраняет исходный номер строки (1-based, включая заголовок).
        Каждая строка: (row_index, [model_name, det_name, on_pallet, per_unit, print_time])
        """
        records = self.sheet.get_all_values()
        if len(records) <= 1:
            return []
        result = []
        current_model = None
        # начинаем с 1, потому что records[0] - заголовок
        for idx, row in enumerate(records[1:], start=2):  # строки в Google Sheets нумеруются с 1, заголовок на строке 1
            if row[0] and row[0].strip():
                current_model = row[0].strip()
            new_row = [current_model] + row[1:]
            result.append((idx, new_row))
        return result

    def get_all_models(self):
        rows_with_idx = self._normalize_rows_with_index()
        models = set()
        for _, row in rows_with_idx:
            if row[0]:
                models.add(row[0])
        return sorted(list(models))

    def get_model_details_with_rows(self, model_name):
        """
        Возвращает список деталей для модели:
        [(row_index, det_name, on_pallet, per_unit, print_time), ...]
        """
        rows_with_idx = self._normalize_rows_with_index()
        details = []
        for row_idx, row in rows_with_idx:
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
                    print_time = int(float(row[4])) if row[4] else 0
                except:
                    print_time = 0
                details.append((row_idx, det_name, on_pallet, per_unit, print_time))
        return details

    def get_model_details(self, model_name):
        """Для обратной совместимости (без индексов)"""
        details_with_rows = self.get_model_details_with_rows(model_name)
        return [(det_name, on_pallet, per_unit, print_time) for (_, det_name, on_pallet, per_unit, print_time) in details_with_rows]

    def get_part_row_and_data(self, model_name, det_name):
        """Возвращает (row_index, on_pallet, per_unit, print_time) для указанной детали."""
        details = self.get_model_details_with_rows(model_name)
        for row_idx, d_name, on_pallet, per_unit, print_time in details:
            if d_name == det_name:
                return row_idx, on_pallet, per_unit, print_time
        return None

    def update_part_field(self, row_index, field, new_value):
        """
        Обновляет конкретное поле детали.
        field: 'name', 'on_pallet', 'per_unit', 'time'
        new_value: для name - строка, для чисел - int, для time - минуты (int)
        """
        col_map = {
            'name': 'B',
            'on_pallet': 'C',
            'per_unit': 'D',
            'time': 'E'
        }
        col = col_map.get(field)
        if not col:
            return False
        self.sheet.update(f"{col}{row_index}", new_value)
        return True

    def add_model(self, model_name, details):
        """details: list of tuples (det_name, on_pallet, per_unit, print_time_min)"""
        all_rows = self.sheet.get_all_values()
        start_row = len(all_rows) + 1

        rows_to_add = []
        for i, (det_name, on_pallet, per_unit, print_time_min) in enumerate(details):
            row = [""] * 5
            if i == 0:
                row[0] = model_name
            row[1] = det_name
            row[2] = on_pallet
            row[3] = per_unit
            row[4] = print_time_min
            rows_to_add.append(row)

        end_row = start_row + len(rows_to_add) - 1
        cell_range = f"A{start_row}:E{end_row}"
        self.sheet.update(cell_range, rows_to_add, value_input_option="USER_ENTERED")

    def init_sheet(self):
        if not self.sheet.get_all_values():
            headers = ["Название", "Детали", "Кол-во на палете", "Нужно на шт.", "Время печати (мин.)"]
            self.sheet.append_row(headers)
