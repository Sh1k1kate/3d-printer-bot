import os
import logging
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.fsm.storage.memory import MemoryStorage
from handlers import router
from config import BOT_TOKEN, BAMBU_EMAIL, BAMBU_PASSWORD
from google_sheets import SheetManager, moscow_now
from datetime import datetime, timedelta
import aiohttp
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не задан в переменных окружения!")
    raise ValueError("BOT_TOKEN is required")

# ---------- Telegram bot ----------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

# ---------- FastAPI app ----------
app = FastAPI()

# Шаблоны
templates = Jinja2Templates(directory="templates")

# ---------- Вспомогательная функция для расчёта дней до дедлайна ----------
def get_days_left(deadline: str) -> str:
    """Возвращает строку с оставшимся временем до даты."""
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

# ---------- Класс для работы с облачным API Bambu Lab ----------
class BambuCloudAPI:
    def __init__(self, email=None, password=None):
        self.email = email or os.getenv("BAMBU_EMAIL")
        self.password = password or os.getenv("BAMBU_PASSWORD")
        self.access_token = None
        self.token_expiry = None
        self.api_base = "https://api.bambulab.com/v1"
        self._session = None

    async def _get_session(self):
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _login(self):
        """Авторизация в облаке Bambu Lab."""
        if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.access_token
        if not self.email or not self.password:
            logger.error("BAMBU_EMAIL и BAMBU_PASSWORD не заданы")
            return None
        session = await self._get_session()
        try:
            # Эндпоинт может отличаться – проверьте документацию Bambu Lab
            async with session.post(f"{self.api_base}/auth/login", json={
                "email": self.email,
                "password": self.password
            }) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 3600)
                    self.token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
                    logger.info("Успешная авторизация в Bambu Lab")
                    return self.access_token
                else:
                    logger.error(f"Ошибка авторизации Bambu: {resp.status} - {await resp.text()}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка авторизации Bambu: {e}")
            return None

    async def get_printers(self):
        """Получить список принтеров и их статус."""
        token = await self._login()
        if not token:
            return []
        session = await self._get_session()
        try:
            async with session.get(f"{self.api_base}/printers", headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    printers = data.get("printers", [])
                    result = []
                    for p in printers:
                        result.append({
                            "id": p.get("id"),
                            "name": p.get("name"),
                            "status": p.get("status"),  # printing, idle, offline
                            "progress": p.get("progress", 0),
                            "model": p.get("model"),
                            "current_job": p.get("current_job")
                        })
                    return result
                else:
                    logger.error(f"Ошибка получения принтеров: {resp.status} - {await resp.text()}")
                    return []
        except Exception as e:
            logger.error(f"Ошибка получения принтеров: {e}")
            return []

    async def close(self):
        if self._session:
            await self._session.close()

# Глобальный экземпляр API
_bambu_api = None
def get_bambu_api():
    global _bambu_api
    if _bambu_api is None:
        _bambu_api = BambuCloudAPI()
    return _bambu_api

# ---------- Вебхук ----------
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

# ---------- Главная ----------
@app.get("/")
async def root():
    return {"status": "3D Printer Bot is running"}

# ---------- Трекер ----------
@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    return templates.TemplateResponse("tracker.html", {"request": request})

# ---------- API заказов ----------
@app.get("/api/orders")
async def get_orders_api():
    try:
        sheet = SheetManager()
        orders = sheet.get_active_orders()
        result = []
        for order in orders:
            if len(order) >= 7:
                result.append({
                    "id": order[0],
                    "position": order[1],
                    "ordered": int(order[2]),
                    "printed": int(order[3]),
                    "deadline": order[4],
                    "modified": order[5],
                    "status": order[6],
                    "progress": round(int(order[3]) / int(order[2]) * 100) if int(order[2]) > 0 else 0
                })
        return JSONResponse(content={"orders": result})
    except Exception as e:
        logger.error(f"API orders error: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)

# ---------- API задач ----------
@app.get("/api/tasks")
async def get_tasks_api():
    try:
        sheet = SheetManager()
        # Получаем все активные задачи (без фильтрации по пользователю)
        # Метод get_active_tasks с параметром user_id=None должен возвращать все активные задачи
        tasks = sheet.get_active_tasks(user_id=None)
        result = []
        for task in tasks:
            # task: (task_id, title, deadline, assignee, status) – зависит от реализации
            # Убедитесь, что порядок полей соответствует вашему методу
            # Если у вас другой порядок, скорректируйте индексы
            task_id, title, deadline, assignee, status = task
            result.append({
                "id": task_id,
                "title": title,
                "deadline": deadline,
                "assignee": assignee if assignee else "Общая",
                "status": status,
                "time_left": get_days_left(deadline)
            })
        return JSONResponse(content={"tasks": result})
    except Exception as e:
        logger.error(f"API tasks error: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)

# ---------- API принтеров (облачный Bambu Lab) ----------
@app.get("/api/printers")
async def get_printers_api():
    try:
        api = get_bambu_api()
        printers = await api.get_printers()
        return JSONResponse(content={"printers": printers})
    except Exception as e:
        logger.error(f"Ошибка получения принтеров: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e), "printers": []}, status_code=500)

# ---------- Проверка задач (cron) ----------
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

# ---------- Запуск ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
