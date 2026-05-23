import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from handlers import router
from config import BOT_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
dp.include_router(router)

# FastAPI приложение
app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Ошибка вебхука: {e}")
        return {"status": "error"}

@app.get("/")
async def root():
    return {"status": "alive"}

# Эндпоинт для пинга (cron-job)
@app.get("/ping")
async def ping():
    # Можно выполнить легковесное действие, например, проверить подключение к Google Sheets
    try:
        from google_sheets import SheetManager
        sm = SheetManager()
        sm.sheet.title  # просто проверка доступа
        return {"status": "ok", "message": "pong"}
    except Exception as e:
        logging.error(f"Ping error: {e}")
        return {"status": "error", "message": str(e)}

# Если запускаем локально (для теста)
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)