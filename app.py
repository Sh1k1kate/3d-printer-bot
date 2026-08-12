import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import router
from config import BOT_TOKEN
from google_sheets import SheetManager, moscow_now
from datetime import datetime, timezone, timedelta

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

@app.get("/check_tasks")
async def check_tasks():
    sheet = SheetManager()
    tasks = sheet.get_tasks_for_notification()
    now = moscow_now()  # московское время
    notified_count = 0
    for task in tasks:
        deadline_dt = task["deadline_dt"]
        diff_minutes = (deadline_dt - now).total_seconds() / 60
        assignee = task["assignee"]
        task_id = task["id"]
        title = task["title"]

        # Утреннее уведомление в 9:00 (один раз в день)
        if now.hour == 9 and now.minute == 0 and task["notified_morning"] == "0":
            if assignee and str(assignee).isdigit():
                try:
                    await bot.send_message(int(assignee), f"🌅 Напоминание: сегодня задача '{title}' должна быть выполнена до {deadline_dt.strftime('%H:%M')}!")
                    sheet.update_task_notification(task_id, 'notified_morning', '1')
                    notified_count += 1
                except Exception as e:
                    logging.error(f"Ошибка отправки утреннего уведомления: {e}")

        # Проверка уведомлений за 60, 30, 15, 0 минут
        notifications = [
            (60, 'notified_60'),
            (30, 'notified_30'),
            (15, 'notified_15'),
            (0, 'notified_0')
        ]
        for minutes, field in notifications:
            if abs(diff_minutes - minutes) < 0.5 and task[field] == "0":
                if assignee and str(assignee).isdigit():
                    try:
                        if minutes == 0:
                            text = f"🔔 Срок выполнения задачи '{title}' истёк (до {deadline_dt.strftime('%H:%M')})!"
                        else:
                            text = f"⏰ Через {minutes} минут задача '{title}' должна быть выполнена (до {deadline_dt.strftime('%H:%M')})!"
                        await bot.send_message(int(assignee), text)
                        sheet.update_task_notification(task_id, field, '1')
                        notified_count += 1
                    except Exception as e:
                        logging.error(f"Ошибка отправки уведомления за {minutes} минут: {e}")
            # Если разница меньше -0.5 (уже позже), и уведомление не отправлено – отметить как отправленное
            elif diff_minutes < -0.5 and task[field] == "0":
                sheet.update_task_notification(task_id, field, '1')

    return {"status": "ok", "notified": notified_count}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)