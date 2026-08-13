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
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан в переменных окружения!")
    raise ValueError("BOT_TOKEN is required")

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
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error"}

@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}

@app.get("/check_tasks")
async def check_tasks():
    try:
        logger.info("Начало проверки задач")
        sheet = SheetManager()
        tasks = sheet.get_tasks_for_notification()
        logger.info(f"Найдено задач для проверки: {len(tasks)}")
        now = moscow_now()
        notified_count = 0

        for task in tasks:
            try:
                deadline_dt = task["deadline_dt"]
                diff_minutes = (deadline_dt - now).total_seconds() / 60
                assignee = task["assignee"]
                task_id = task["id"]
                title = task["title"]

                recipients = []
                if assignee and str(assignee).isdigit():
                    recipients = [int(assignee)]
                else:
                    recipients = sheet.get_all_subscribers()
                    if not recipients:
                        logger.warning(f"Нет подписчиков для общей задачи {task_id}")
                        continue

                # Утреннее уведомление в 9:00
                if now.hour == 9 and now.minute == 0 and task["notified_morning"] == "0":
                    for recipient in recipients:
                        try:
                            await bot.send_message(
                                recipient,
                                f"🌅 Напоминание: сегодня задача '{title}' должна быть выполнена до {deadline_dt.strftime('%H:%M')}!"
                            )
                            notified_count += 1
                        except Exception as e:
                            logger.error(f"Ошибка отправки утреннего уведомления пользователю {recipient}: {e}")
                    sheet.update_task_notification(task_id, 'notified_morning', '1')
                    logger.info(f"Отправлено утреннее уведомление для задачи {task_id}")

                # Уведомления за 60, 30, 15, 0 минут
                notifications = [
                    (60, 'notified_60'),
                    (30, 'notified_30'),
                    (15, 'notified_15'),
                    (0, 'notified_0')
                ]
                for minutes, field in notifications:
                    if abs(diff_minutes - minutes) < 0.5 and task[field] == "0":
                        for recipient in recipients:
                            try:
                                if minutes == 0:
                                    text = f"🔔 Срок выполнения задачи '{title}' истёк (до {deadline_dt.strftime('%H:%M')})!"
                                else:
                                    text = f"⏰ Через {minutes} минут задача '{title}' должна быть выполнена (до {deadline_dt.strftime('%H:%M')})!"
                                await bot.send_message(recipient, text)
                                notified_count += 1
                            except Exception as e:
                                logger.error(f"Ошибка отправки уведомления за {minutes} минут пользователю {recipient}: {e}")
                        sheet.update_task_notification(task_id, field, '1')
                        logger.info(f"Отправлено уведомление за {minutes} минут для задачи {task_id}")
                    elif diff_minutes < -0.5 and task[field] == "0":
                        sheet.update_task_notification(task_id, field, '1')
                        logger.info(f"Задача {task_id}: пропущено уведомление {field}, т.к. время прошло")
            except Exception as e:
                logger.error(f"Ошибка обработки задачи {task.get('id', 'unknown')}: {e}", exc_info=True)

        logger.info(f"Проверка завершена, отправлено уведомлений: {notified_count}")
        return {"status": "ok", "notified": notified_count}

    except Exception as e:
        logger.error(f"Критическая ошибка в /check_tasks: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)