import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
SPREADSHEET_ID = "142fAjnM3n7tzNz1WAokl_YV7LPg11STFjYyJ1ea66LM"
CREDENTIALS_FILE = "credentials.json"

# Белый список – только эти пользователи могут использовать бота
# Узнать свой ID можно командой /id (если бот ещё доступен)
# Формат: [123456789, 987654321, ...]
ALLOWED_USERS = [
    123456789,  # замените на ваш ID
    # добавьте другие ID через запятую
]