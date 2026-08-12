import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import router
from config import BOT_TOKEN
from google_sheets import SheetManager

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

app = FastAPI()

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return {"status": "error"}

@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}

# Новый эндпоинт для cron-job
@app.get("/check_tasks")
async def check_tasks():
    sheet = SheetManager()
    tasks = sheet.get_tasks_due_today()
    notified_count = 0
    for task in tasks:
        assignee = task['assignee']
        if assignee and str(assignee).isdigit():
            try:
                await bot.send_message(int(assignee), f"🔔 Напоминание: задача '{task['title']}' должна быть выполнена до {task['deadline']}!")
                notified_count += 1
            except Exception as e:
                logging.error(f"Не удалось отправить уведомление пользователю {assignee}: {e}")
        else:
            # Общая задача – уведомление не отправляем (можно позже добавить канал)
            pass
        # Помечаем, что уведомление отправлено
        sheet.update_task_field(task['id'], 'notified', '1')
    return {"status": "ok", "notified": notified_count}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)