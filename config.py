import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "142fAjnM3n7tzNz1WAokl_YV7LPg11STFjYyJ1ea66LM")
CREDENTIALS_FILE = os.getenv("CREDENTIALS_FILE", "credentials.json")
# ✅ Пароль для админки прайса (заголовок X-Admin-Token)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Белый список (ALLOWED_USERS через запятую в переменной окружения)
ALLOWED_USERS = []
allowed_env = os.getenv("ALLOWED_USERS", "")
if allowed_env:
    _parts = [x.strip() for x in allowed_env.split(",") if x.strip()]
    _bad = [x for x in _parts if not (x.isascii() and x.isdigit())]
    if _bad or not _parts:
        # не «открываем» бота всем из-за опечатки в переменной окружения
        raise ValueError(f"ALLOWED_USERS: ожидаются числовые Telegram ID через запятую, получено: {allowed_env!r}")
    ALLOWED_USERS = [int(x) for x in _parts]
else:
    ALLOWED_USERS = [398362790,763201845,7858131385]  # замените на ваш Telegram ID для локальных тестов

# Bambu Lab Cloud API (опционально, если используется)
BAMBU_EMAIL = os.getenv("BAMBU_EMAIL", "")
BAMBU_PASSWORD = os.getenv("BAMBU_PASSWORD", "")
BAMBU_TOKEN = os.getenv("BAMBU_TOKEN", "")  # готовый токен (можно получить через CLI)
BAMBU_REGION = os.getenv("BAMBU_REGION", "global")  # "global" или "china"

# Секрет для подписи админ-токенов и (опционально) защиты вебхуков/крона
TOKEN_SECRET = os.getenv("TOKEN_SECRET", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")
