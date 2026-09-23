import os
import json
import base64
import time
import logging
import aiohttp
from fastapi import FastAPI, Request, UploadFile, File, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from aiogram import Bot, Dispatcher
from aiogram.types import Update, ErrorEvent
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import routers
from handlers.common import AccessMiddleware
from config import BOT_TOKEN, ADMIN_PASSWORD
from google_sheets import SheetManager, moscow_now
from bambu_cloud import BambuCloudManager
from datetime import datetime

# 3MF-анализ
from handlers_3mf import (
    extract_colors_from_3mf, hex_to_rgb, rgb_to_hex,
    group_similar_colors, find_closest_colors, generate_color_palette, BAMBU_COLORS,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
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


# ---------- АВТОРИЗАЦИЯ АДМИНА (прайс) ----------
def verify_admin(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD не задан на сервере")
    if x_admin_token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверный пароль администратора")
    return True


class PriceItemIn(BaseModel):
    name: str
    description: str = ""
    photo: str = ""
    retail: str = ""
    wholesale: str = ""
    wholesale_from: str = ""
    category: str = ""


# ---------- ЗАГРУЗКА ФОТО В GOOGLE DRIVE ----------
DRIVE_UPLOAD_URL = os.getenv("DRIVE_UPLOAD_URL", "")
DRIVE_UPLOAD_SECRET = os.getenv("DRIVE_UPLOAD_SECRET", "")
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 МБ


@app.post("/api/upload_image")
async def upload_image_api(file: UploadFile = File(...), _: bool = Depends(verify_admin)):
    """Принимает картинку от админки, отправляет в Apps Script, возвращает публичный URL."""
    if not DRIVE_UPLOAD_URL or not DRIVE_UPLOAD_SECRET:
        return JSONResponse(
            {"error": "DRIVE_UPLOAD_URL / DRIVE_UPLOAD_SECRET не заданы на сервере"},
            status_code=500,
        )
    if not file.content_type or not file.content_type.startswith("image/"):
        return JSONResponse({"error": "Только изображения (jpg, png, webp, gif)"}, status_code=400)

    content = await file.read()
    if not content:
        return JSONResponse({"error": "Пустой файл"}, status_code=400)
    if len(content) > MAX_IMAGE_SIZE:
        return JSONResponse({"error": "Файл больше 5 МБ"}, status_code=400)

    b64 = base64.b64encode(content).decode("ascii")
    filename = file.filename or f"upload_{int(time.time())}.jpg"

    payload = {
        "secret": DRIVE_UPLOAD_SECRET,
        "filename": filename,
        "mime": file.content_type,
        "image": b64,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DRIVE_UPLOAD_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    logger.error(f"Drive upload HTTP {resp.status}: {raw[:300]}")
                    return JSONResponse({"error": "Google Drive вернул ошибку"}, status_code=502)
                data = json.loads(raw)
    except Exception as e:
        logger.error(f"Drive upload exception: {e}")
        return JSONResponse({"error": f"Ошибка соединения с Drive: {e}"}, status_code=502)

    if not data.get("ok"):
        return JSONResponse(
            {"error": data.get("error") or "Drive отказал в загрузке"},
            status_code=502,
        )

    return JSONResponse({"url": data["url"]})


# ---------- УТИЛИТЫ ----------
def get_days_left(deadline):
    try:
        due = datetime.strptime(deadline, "%Y-%m-%d")
        diff = (due - datetime.now()).days
        if diff < 0: return "Просрочено"
        if diff == 0: return "Сегодня"
        if diff == 1: return "Завтра"
        return f"{diff} дн."
    except:
        return "—"


# ---------- TELEGRAM WEBHOOK ----------
@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = Update(**(await request.json()))
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"status": "error"}


# ---------- СТРАНИЦЫ ----------
@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    return templates.TemplateResponse("tracker.html", {"request": request})


@app.get("/price", response_class=HTMLResponse)
async def price_page(request: Request):
    return templates.TemplateResponse("price.html", {"request": request})


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


# ---------- API: ЗАКАЗЫ ----------
@app.get("/api/orders")
async def get_orders_api(customer: str = "", from_date: str = "", to_date: str = ""):
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        result = []
        for order in sheet_manager.get_active_orders():
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
                ordered = int(order[2]); printed = int(order[3])
            except (ValueError, TypeError):
                ordered = 0; printed = 0
            result.append({
                "id": order[0], "position": order[1],
                "ordered": ordered, "printed": printed,
                "deadline": order[4], "modified": order[5],
                "status": order[6], "customer": order_customer,
                "progress": round(printed / ordered * 100) if ordered > 0 else 0
            })
        return JSONResponse({"orders": result})
    except Exception as e:
        logger.error(f"API error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------- API: ЗАДАЧИ ----------
@app.get("/api/tasks")
async def get_tasks_api():
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        result = [{
            "id": t[0], "title": t[1], "deadline": t[2],
            "time": t[3] if len(t) > 3 else "",
            "assignee": t[4] if t[4] else "Общая",
            "status": t[5],
            "time_left": get_days_left(t[2])
        } for t in sheet_manager.get_active_tasks()]
        return JSONResponse({"tasks": result})
    except Exception as e:
        logger.error(f"API tasks error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------- API: ПРИНТЕРЫ ----------
@app.get("/api/printers")
async def get_printers_api():
    printers = await run_in_threadpool(bambu_cloud.get_printers)
    return JSONResponse({"printers": printers})


# ---------- API: 3MF ----------
MAX_3MF_SIZE = 50 * 1024 * 1024


def _process_3mf_bytes(content: bytes):
    raw_colors_hex = extract_colors_from_3mf(content)
    if not raw_colors_hex:
        return {"colors": [], "count": 0, "palette": None}
    raw_colors_rgb = [hex_to_rgb(h) for h in raw_colors_hex]
    grouped = group_similar_colors(raw_colors_rgb, tolerance=20, max_colors=10)
    unique_matches = []
    seen_hex = set()
    for rgb in grouped:
        matches = find_closest_colors(rgb_to_hex(rgb), BAMBU_COLORS, top_n=1)
        if matches and matches[0][1]["hex"] not in seen_hex:
            seen_hex.add(matches[0][1]["hex"])
            unique_matches.append(matches[0][1])
    palette_b64 = None
    try:
        palette_bytes = generate_color_palette(grouped)
        if palette_bytes:
            palette_b64 = base64.b64encode(palette_bytes).decode("ascii")
    except Exception as e:
        logger.warning(f"Ошибка генерации палитры: {e}")
    return {"colors": unique_matches, "count": len(unique_matches), "palette": palette_b64}


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


# ---------- API: ПРАЙС ----------
@app.get("/api/price")
async def get_price_api():
    """Публичный список товаров — без row_index."""
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        items = sheet_manager.get_price_items()
        categories = sheet_manager.get_price_categories()
        public_items = [{
            "name": it["name"],
            "description": it["description"],
            "photo": it["photo"],
            "retail": it["retail"],
            "wholesale": it["wholesale"],
            "wholesale_from": it["wholesale_from"],
            "category": it["category"],
        } for it in items]
        return JSONResponse({"items": public_items, "categories": categories})
    except Exception as e:
        logger.error(f"API price error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/price/admin")
async def get_price_admin_api(_: bool = Depends(verify_admin)):
    """Полный список с row_index — только для админки."""
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        return JSONResponse({"items": sheet_manager.get_price_items()})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/price")
async def add_price_api(payload: PriceItemIn, _: bool = Depends(verify_admin)):
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        ok = sheet_manager.add_price_item(
            payload.name, payload.description, payload.photo,
            payload.retail, payload.wholesale, payload.wholesale_from, payload.category
        )
        if not ok:
            return JSONResponse({"error": "Не удалось добавить (пустое имя?)"}, status_code=400)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/price/{row_index}")
async def update_price_api(row_index: int, payload: PriceItemIn, _: bool = Depends(verify_admin)):
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    if not sheet_manager.get_price_item_by_row(row_index):
        return JSONResponse({"error": "Товар не найден"}, status_code=404)
    try:
        for field, value in [
            ("name", payload.name), ("description", payload.description),
            ("photo", payload.photo), ("retail", payload.retail),
            ("wholesale", payload.wholesale), ("wholesale_from", payload.wholesale_from),
            ("category", payload.category),
        ]:
            sheet_manager.update_price_item(row_index, field, value)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/price/{row_index}")
async def delete_price_api(row_index: int, _: bool = Depends(verify_admin)):
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    if not sheet_manager.get_price_item_by_row(row_index):
        return JSONResponse({"error": "Товар не найден"}, status_code=404)
    try:
        ok = sheet_manager.delete_price_item(row_index)
        if not ok:
            return JSONResponse({"error": "Не удалось удалить"}, status_code=400)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------- CRON ----------
@app.get("/check_tasks")
async def check_tasks():
    if not sheet_manager:
        return JSONResponse({"error": "SheetManager не инициализирован"}, status_code=500)
    try:
        tasks = sheet_manager.get_tasks_for_notification()
        now = moscow_now()
        notified_count = 0
        for task in tasks:
            try:
                diff_minutes = (task["deadline_dt"] - now).total_seconds() / 60
                assignee = task["assignee"]
                task_id = task["id"]
                title = task["title"]
                user_settings = sheet_manager.get_user_settings(assignee) if assignee else None
                morning_hour = int(user_settings.get("morning_time", "09:00").split(':')[0]) if user_settings else 9
                recipients = [int(assignee)] if (assignee and str(assignee).isdigit()) else sheet_manager.get_all_subscribers()

                if now.hour == morning_hour and now.minute == 0 and task["notified_morning"] == "0":
                    for recipient in recipients:
                        try:
                            await bot.send_message(recipient, f"🌅 Напоминание: сегодня задача '{title}' должна быть выполнена до {task['deadline_dt'].strftime('%H:%M')}!")
                            notified_count += 1
                        except Exception as e:
                            logger.error(f"Ошибка утреннего уведомления: {e}")
                    sheet_manager.update_task_notification(task_id, 'notified_morning', '1')

                for minutes, field in [(60, 'notified_60'), (30, 'notified_30'), (15, 'notified_15'), (0, 'notified_0')]:
                    if abs(diff_minutes - minutes) < 0.5 and task[field] == "0":
                        for recipient in recipients:
                            try:
                                text = (f"🔔 Срок задачи '{title}' истёк (до {task['deadline_dt'].strftime('%H:%M')})!"
                                        if minutes == 0
                                        else f"⏰ Через {minutes} минут задача '{title}' должна быть выполнена (до {task['deadline_dt'].strftime('%H:%M')})!")
                                await bot.send_message(recipient, text)
                                notified_count += 1
                            except Exception as e:
                                logger.error(f"Ошибка уведомления за {minutes} минут: {e}")
                        sheet_manager.update_task_notification(task_id, field, '1')
            except Exception as e:
                logger.error(f"Ошибка обработки задачи {task.get('id')}: {e}")
        return JSONResponse({"status": "ok", "notified": notified_count})
    except Exception as e:
        logger.error(f"Критическая ошибка в /check_tasks: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
