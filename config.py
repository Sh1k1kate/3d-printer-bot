import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "142fAjnM3n7tzNz1WAokl_YV7LPg11STFjYyJ1ea66LM")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
# ✅ Пароль для админки прайса (заголовок X-Admin-Token)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Белый список (ALLOWED_USERS через запятую в переменной окружения)
ALLOWED_USERS = []
allowed_env = os.getenv("ALLOWED_USERS", "")
if allowed_env:
    ALLOWED_USERS = [int(x.strip()) for x in allowed_env.split(",") if x.strip().isdigit()]
else:
    ALLOWED_USERS = [398362790,763201845,7858131385]  # замените на ваш Telegram ID для локальных тестов

# Bambu Lab Cloud API (опционально, если используется)
BAMBU_EMAIL = os.getenv("BAMBU_EMAIL", "")
BAMBU_PASSWORD = os.getenv("BAMBU_PASSWORD", "")
BAMBU_TOKEN = os.getenv("BAMBU_TOKEN", "")  # готовый токен (можно получить через CLI)
BAMBU_REGION = os.getenv("BAMBU_REGION", "global")  # "global" или "china"
