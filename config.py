import os

# “окен бота Ц будет передан через переменную окружени€ на Render
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ID вашей Google Sheets таблицы
SPREADSHEET_ID = "142fAjnM3n7tzNz1WAokl_YV7LPg11STFjYyJ1ea66LM"

# ѕуть к файлу сервисного аккаунта (на Render Ц абсолютный путь, но можно хранить как переменную)
CREDENTIALS_FILE = "credentials.json"  # в корне проекта