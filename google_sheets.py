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
        records = self.sheet.get_all_values()
        if len(records) <= 1:
            return []
        result = []
        current_model = None
        for idx, row in enumerate(records[1:], start=2):
            if row[0] and row[0].strip():
                current_model = row[0].strip()
            # Дополняем row до 6 элементов (если меньше)
            while len(row) < 6:
                row.append("")
            new_row = [current_model] + row[1:6]  # A, B, C, D, E, F
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
                    time_per_pallet = int(float(row[4])) if row[4] else 0
                except:
                    time_per_pallet = 0
                try:
                    grams_per_pallet = int(float(row[5])) if len(row) > 5 and row[5] else 0
                except:
                    grams_per_pallet = 0
                details.append((row_idx, det_name, on_pallet, per_unit, time_per_pallet, grams_per_pallet))
        return details

    def get_model_details(self, model_name):
        details_with_rows = self.get_model_details_with_rows(model_name)
        return [(det_name, on_pallet, per_unit, time_per_pallet, grams_per_pallet) 
                for (_, det_name, on_pallet, per_unit, time_per_pallet, grams_per_pallet) in details_with_rows]

    def get_part_row_and_data(self, model_name, det_name):
        details = self.get_model_details_with_rows(model_name)
        for row_idx, d_name, on_pallet, per_unit, time_pp, grams_pp in details:
            if d_name == det_name:
                return row_idx, on_pallet, per_unit, time_pp, grams_pp
        return None

    def update_part_field(self, row_index, field, new_value):
        """
        field: 'name', 'on_pallet', 'per_unit', 'time', 'grams'
        """
        col_map = {
            'name': 2,      # B
            'on_pallet': 3, # C
            'per_unit': 4,  # D
            'time': 5,      # E
            'grams': 6      # F
        }
        col = col_map.get(field)
        if not col:
            return False
        
        # Все значения записываем как строки (избегаем ошибок формата ячеек)
        value_to_write = str(new_value)
        try:
            self.sheet.update_cell(row_index, col, value_to_write)
            return True
        except Exception as e:
            print(f"Error updating {field} at {col}{row_index}: {e}")
            return False

    def add_model(self, model_name, details):
        """
        details: list of tuples (det_name, on_pallet, per_unit, time_per_pallet_min, grams_per_pallet)
        """
        all_rows = self.sheet.get_all_values()
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
        self.sheet.update(cell_range, rows_to_add, value_input_option="USER_ENTERED")

    def init_sheet(self):
        if not self.sheet.get_all_values():
            headers = ["Название", "Детали", "Кол-во на палете", "Нужно на шт.", "Время палета (мин)", "Грамм на палет"]
            self.sheet.append_row(headers)
