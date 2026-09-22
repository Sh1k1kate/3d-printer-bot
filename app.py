import os
import base64
import logging
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates
from aiogram import Bot, Dispatcher
from aiogram.types import Update, ErrorEvent
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import routers
from handlers.common import AccessMiddleware
from config import BOT_TOKEN
from google_sheets import SheetManager, moscow_now
from bambu_cloud import BambuCloudManager
from datetime import datetime

# ✅ Импорт функций 3MF-анализа
from handlers_3mf import (
    extract_colors_from_3mf,
    hex_to_rgb,
    rgb_to_hex,
    group_similar_colors,
    find_closest_colors,
    generate_color_palette,
    BAMBU_COLORS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан!")
    raise ValueError("BOT_TOKEN is required")

try:
    sheet_manager = SheetManager()
    logger.info("SheetManager успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации SheetManager: {e}")
    sheet_manager = None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.message.middleware(AccessMiddleware())
dp.callback_query.middleware(AccessMiddleware())
for router in routers:
    dp.include_router(router)


@dp.errors()
async def errors_handler(event: ErrorEvent):
    logger.error(f"Global error: {event.exception}", exc_info=event.exception)
    return True


app = FastAPI()
templates = Jinja2Templates(directory="templates")
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


@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    return templates.TemplateResponse("tracker.html", {"request": request})


# ✅ Страница загрузки 3MF (upload_3mf.html лежит в корне проекта)
@app.get("/upload_3mf", response_class=HTMLResponse)
async def upload_3mf_page():
    return FileResponse("upload_3mf.html")


@app.get("/manifest.json")
async def manifest():
    return JSONResponse(content={
        "name": "3D Printer Tracker",
        "short_name": "3D Tracker",
        "start_url": "/tracker",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#3b82f6",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"}]
    })


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
            try:
                ordered = int(order[2])
                printed = int(order[3])
            except (ValueError, TypeError):
                ordered = 0
                printed = 0
            result.append({
                "id": order[0],
                "position": order[1],
                "ordered": ordered,
                "printed": printed,
                "deadline": order[4],
                "modified": order[5],
                "status": order[6],
                "customer": order_customer,
                "progress": round(printed / ordered * 100) if ordered > 0 else 0
            })
        return JSONResponse(content={"orders": result})
    except Exception as e:
        logger.error(f"API error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


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


@app.get("/api/printers")
async def get_printers_api():
    printers = await run_in_threadpool(bambu_cloud.get_printers)
    return JSONResponse(content={"printers": printers})


# ✅ POST /api/analyze_3mf — обработка файла из веб-интерфейса
MAX_3MF_SIZE = 50 * 1024 * 1024


def _process_3mf_bytes(content: bytes):
    """Синхронная обработка 3MF — запускается в threadpool."""
    raw_colors_hex = extract_colors_from_3mf(content)
    if not raw_colors_hex:
        return {"colors": [], "count": 0, "palette": None}

    raw_colors_rgb = [hex_to_rgb(h) for h in raw_colors_hex]
    grouped = group_similar_colors(raw_colors_rgb, tolerance=20, max_colors=10)

    unique_matches = []
    seen_hex = set()
    for rgb in grouped:
        hex_str = rgb_to_hex(rgb)
        matches = find_closest_colors(hex_str, BAMBU_COLORS, top_n=1)
        if matches:
            match = matches[0][1]
            if match["hex"] not in seen_hex:
                seen_hex.add(match["hex"])
                unique_matches.append(match)

    palette_b64 = None
    try:
        palette_bytes = generate_color_palette(grouped)
        if palette_bytes:
            palette_b64 = base64.b64encode(palette_bytes).decode("ascii")
    except Exception as e:
        logger.warning(f"Ошибка генерации палитры: {e}")

    return {
        "colors": unique_matches,
        "count": len(unique_matches),
        "palette": palette_b64,
    }


@app.post("/api/analyze_3mf")
async def analyze_3mf_api(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".3mf"):
        return JSONResponse({"detail": "Нужен файл .3mf"}, status_code=400)
    try:
        content = await file.read()
    except Exception as e:
        return JSONResponse({"detail": f"Не удалось прочитать файл: {e}"}, status_code=400)

    if len(content) > MAX_3MF_SIZE:
        return JSONResponse({"detail": "Файл больше 50 МБ"}, status_code=400)

    try:
        result = await run_in_threadpool(_process_3mf_bytes, content)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Ошибка анализа 3MF: {e}", exc_info=e)
        return JSONResponse({"detail": f"Ошибка анализа: {e}"}, status_code=500)


@app.get("/check_tasks")
async def check_tasks():
    if not sheet_manager:
        return JSONResponse(content={"error": "SheetManager не инициализирован"}, status_code=500)
    try:
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
                recipients = [int(assignee)] if (assignee and str(assignee).isdigit()) else sheet_manager.get_all_subscribers()
                if now.hour == morning_hour and now.minute == 0 and task["notified_morning"] == "0":
                    for recipient in recipients:
                        try:
                            await bot.send_message(recipient, f"🌅 Напоминание: сегодня задача '{title}' должна быть выполнена до {deadline_dt.strftime('%H:%M')}!")
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
                                    text = f"🔔 Срок задачи '{title}' истёк (до {deadline_dt.strftime('%H:%M')})!"
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
