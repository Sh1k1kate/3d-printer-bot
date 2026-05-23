import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_ID, CREDENTIALS_FILE

class SheetManager:
    def __init__(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
        self.client = gspread.authorize(creds)
        self.sheet = self.client.open_by_key(SPREADSHEET_ID).sheet1

    def _normalize_rows(self):
        """Превращает группированную таблицу (пустые A) в плоский список с повторёнными названиями моделей."""
        records = self.sheet.get_all_values()
        if len(records) <= 1:
            return []
        header = records[0]
        normalized = [header]
        current_model = None
        for row in records[1:]:
            if row[0] and row[0].strip():
                current_model = row[0].strip()
            new_row = [current_model] + row[1:]
            normalized.append(new_row)
        return normalized

    def get_all_models(self):
        rows = self._normalize_rows()
        models = set()
        for row in rows[1:]:
            if row[0]:
                models.add(row[0])
        return sorted(list(models))

    def get_model_details(self, model_name):
        rows = self._normalize_rows()
        if len(rows) <= 1:
            return []
        details = []
        for row in rows[1:]:
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
                    print_time = float(row[4]) if row[4] else 0.0
                except:
                    print_time = 0.0
                details.append((det_name, on_pallet, per_unit, print_time))
        return details

    def add_model(self, model_name, details):
        all_rows = self.sheet.get_all_values()
        next_row = len(all_rows) + 1
        for i, (det_name, on_pallet, per_unit, print_time) in enumerate(details):
            model_cell = model_name if i == 0 else ""
            self.sheet.update(f"A{next_row + i}", model_cell)
            self.sheet.update(f"B{next_row + i}", det_name)
            self.sheet.update(f"C{next_row + i}", on_pallet)
            self.sheet.update(f"D{next_row + i}", per_unit)
            self.sheet.update(f"E{next_row + i}", print_time)

    def init_sheet(self):
        if not self.sheet.get_all_values():
            headers = ["Название", "Детали", "Кол-во на палете", "Нужно на шт.", "Время печати (мин.)"]
            self.sheet.append_row(headers)
