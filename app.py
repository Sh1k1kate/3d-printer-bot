import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import routers
from handlers.common import AccessMiddleware
from config import BOT_TOKEN, BAMBU_EMAIL, BAMBU_PASSWORD
from google_sheets import SheetManager, moscow_now
from bambu_cloud import BambuCloudManager
from datetime import datetime, timedelta
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан!")
    raise ValueError("BOT_TOKEN is required")

# ---------- Глобальный SheetManager ----------
try:
    sheet_manager = SheetManager()
    logger.info("SheetManager успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации SheetManager: {e}")
    sheet_manager = None

# ---------- Telegram bot ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------- Регистрируем middleware на уровне диспетчера ----------
dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())

# ---------- Подключаем роутеры ----------
for router in routers:
    dp.include_router(router)

# ---------- FastAPI app ----------
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------- Bambu Cloud Manager ----------
bambu_cloud = BambuCloudManager()


def get_days_left(deadline):
    try:
        due = datetime.strptime(deadline, "%Y-%m-%d")
        diff = (due - datetime.now()).days
        if diff < 0:
            return "Просрочено"
        elif diff == 0:
            return "Сегодня"
        elif diff == 1:
            return "Завтра"
        else:
            return f"{diff} дн."
    except:
        return "—"


# ---------- Вебхук ----------
@app.post("/webhook")
async def webhook(request: Request):
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}


# ---------- Главная ----------
@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}


# ---------- Трекер ----------
@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    return templates.TemplateResponse("tracker.html", {"request": request})


# ---------- Manifest для PWA ----------
@app.get("/manifest.json")
async def manifest():
    return JSONResponse(content={
        "name": "3D Printer Tracker",
        "short_name": "3D Tracker",
        "start_url": "/tracker",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#3b82f6",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}
        ]
    })


# ---------- API заказов ----------
@app.get("/api/orders")
async def get_orders_api(customer: str = "", from_date: str = "", to_date: str = ""):
    if not sheet_manager:
        return JSONResponse(content={"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        orders = sheet_manager.get_active_orders()
        result = []
        for order in orders:
            if len(order) < 8:
                continue
            order_customer = order[7] if order[7] else ""
            if customer and customer.lower() not in order_customer.lower():
                continue
            if from_date and order[4] < from_date:
                continue
            if to_date and order[4] > to_date:
                continue
            result.append({
                "id": order[0],
                "position": order[1],
                "ordered": int(order[2]),
                "printed": int(order[3]),
                "deadline": order[4],
                "modified": order[5],
                "status": order[6],
                "customer": order_customer,
                "progress": round(int(order[3]) / int(order[2]) * 100) if int(order[2]) > 0 else 0
            })
        return JSONResponse(content={"orders": result})
    except Exception as e:
        logger.error(f"API error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ---------- API задач ----------
@app.get("/api/tasks")
async def get_tasks_api():
    if not sheet_manager:
        return JSONResponse(content={"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        tasks = sheet_manager.get_active_tasks()
        result = []
        for task in tasks:
            result.append({
                "id": task[0],
                "title": task[1],
                "deadline": task[2],
                "time": task[3] if len(task) > 3 else "",
                "assignee": task[4] if task[4] else "Общая",
                "status": task[5],
                "time_left": get_days_left(task[2])
            })
        return JSONResponse(content={"tasks": result})
    except Exception as e:
        logger.error(f"API tasks error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


# ---------- API принтеров (Bambu Cloud) ----------
@app.get("/api/printers")
async def get_printers_api():
    printers = bambu_cloud.get_printers()
    return JSONResponse(content={"printers": printers})


# ---------- Проверка задач (cron) ----------
@app.get("/check_tasks")
async def check_tasks():
    if not sheet_manager:
        return JSONResponse(content={"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        logger.info("Начало проверки задач")
        tasks = sheet_manager.get_tasks_for_notification()
        now = moscow_now()
        notified_count = 0

        for task in tasks:
            try:
                deadline_dt = task["deadline_dt"]
                diff_minutes = (deadline_dt - now).total_seconds() / 60
                assignee = task["assignee"]
                task_id = task["id"]
                title = task["title"]

                user_settings = sheet_manager.get_user_settings(assignee) if assignee else None
                morning_hour = int(user_settings.get("morning_time", "09:00").split(':')[0]) if user_settings else 9

                recipients = []
                if assignee and str(assignee).isdigit():
                    recipients = [int(assignee)]
                else:
                    recipients = sheet_manager.get_all_subscribers()

                if now.hour == morning_hour and now.minute == 0 and task["notified_morning"] == "0":
                    for recipient in recipients:
                        try:
                            await bot.send_message(
                                recipient,
                                f"🌅 Напоминание: сегодня задача '{title}' должна быть выполнена до {deadline_dt.strftime('%H:%M')}!"
                            )
                            notified_count += 1
                        except Exception as e:
                            logger.error(f"Ошибка утреннего уведомления: {e}")
                    sheet_manager.update_task_notification(task_id, 'notified_morning', '1')

                notifications = [(60, 'notified_60'), (30, 'notified_30'), (15, 'notified_15'), (0, 'notified_0')]
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
                                logger.error(f"Ошибка уведомления за {minutes} минут: {e}")
                        sheet_manager.update_task_notification(task_id, field, '1')
            except Exception as e:
                logger.error(f"Ошибка обработки задачи {task.get('id')}: {e}")

        return JSONResponse(content={"status": "ok", "notified": notified_count})
    except Exception as e:
        logger.error(f"Критическая ошибка в /check_tasks: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)


# ---------- Запуск ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
