import os
import html
import time
import logging
from aiogram import Router, Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, BotCommand, BotCommandScopeDefault,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from google_sheets import SheetManager

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

# ============================================================
# URL КАТАЛОГА
# ============================================================
PUBLIC_URL = os.getenv("PUBLIC_URL", "")


def _normalize_base_url(url: str) -> str:
    """
    Приводит PUBLIC_URL к чистому базовому домену:
    - убирает пробелы
    - убирает слэши на конце
    - убирает ошибочно приклеенные /price, /tracker, /webhook_client, /webhook
    """
    url = (url or "").strip().rstrip("/")
    for suffix in ("/price", "/tracker", "/webhook_client", "/webhook"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


BASE_URL = _normalize_base_url(PUBLIC_URL)
PRICE_URL = f"{BASE_URL}/price" if BASE_URL else ""

if BASE_URL:
    logger.info(f"[client_bot] PUBLIC_URL={PUBLIC_URL!r} → PRICE_URL={PRICE_URL}")
else:
    logger.warning("[client_bot] PUBLIC_URL не задан — кнопки каталога будут недоступны")


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def _kb_price():
    if not PRICE_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Открыть каталог", web_app=WebAppInfo(url=PRICE_URL))],
        [InlineKeyboardButton(text="🔗 Открыть в браузере", url=PRICE_URL)],
    ])


# ============================================================
# ПАРСИНГ НОМЕРА ЗАКАЗА
# ============================================================
def _parse_order_number(text: str):
    """
    Извлекает номер заказа из текста команды.
    Возвращает строку цифр или None.

    Работает с:
    - "/status 12"
    - "/status 12@my_bot"
    - "/status  12  "  (лишние пробелы)
    - "/status 12\\u00a0"  (NBSP)
    - "/status"  → None
    """
    text = text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None

    arg = parts[1].strip()

    # Если команда адресована боту явно (/status@my_bot), отрезаем @username
    if "@" in arg:
        arg = arg.split("@", 1)[0].strip()

    # Оставляем только цифры (убирает пробелы, NBSP, ZWSP и т.п.)
    digits = "".join(c for c in arg if c.isascii() and c.isdigit())
    return digits[:9] if digits else None


# ============================================================
# RATE LIMIT для /status (в памяти, на пользователя)
# ============================================================
STATUS_RATE_LIMIT = 5        # запросов
STATUS_RATE_WINDOW = 60.0    # за столько секунд
_status_hits: dict = {}


def _status_rate_limited(user_id: int) -> bool:
    """True, если пользователь превысил лимит; иначе регистрирует обращение."""
    now = time.monotonic()
    hits = [t for t in _status_hits.get(user_id, []) if now - t < STATUS_RATE_WINDOW]
    if len(hits) >= STATUS_RATE_LIMIT:
        _status_hits[user_id] = hits
        return True
    hits.append(now)
    _status_hits[user_id] = hits
    # не даём словарю расти бесконечно
    if len(_status_hits) > 5000:
        for uid in [u for u, v in _status_hits.items() if not v or now - v[-1] >= STATUS_RATE_WINDOW]:
            _status_hits.pop(uid, None)
    return False


def _esc(value) -> str:
    """Экранирование пользовательских/табличных данных для parse_mode=HTML."""
    return html.escape("" if value is None else str(value), quote=False)


# ============================================================
# КОМАНДЫ
# ============================================================
@router.message(Command("start"))
async def cmd_start(message: Message):
    kb = _kb_price()
    if kb:
        await message.answer(
            "👋 Добро пожаловать в <b>Kobra Print</b>!\n\n"
            "Мы печатаем на заказ — от сувениров до функциональных деталей.\n\n"
            "• /price — каталог товаров и цен\n"
            "• /status N — статус заказа (например: <code>/status 1</code>)\n"
            "• /help — контакты",
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "👋 Добро пожаловать в <b>Kobra Print</b>!\n\n"
            "Каталог временно недоступен. Свяжитесь с нами: @master3Dpech",
            parse_mode="HTML",
        )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📞 <b>Наши контакты</b>\n\n"
        "Telegram: @master3Dpech\n"
        "Email: kobraprintteam@gmail.com\n"
        "Instagram: @kobra_print_\n"
        "VK: vk.com/club238320840\n"
        "YouTube: youtube.com/@kobra_print\n\n"
        "Каталог — /price\n"
        "Статус заказа — /status N",
        parse_mode="HTML",
    )


@router.message(Command("price"))
async def cmd_price(message: Message):
    kb = _kb_price()
    if not kb:
        await message.answer("Каталог временно недоступен. Свяжитесь: @master3Dpech")
        return
    await message.answer(
        "🛍 <b>Наш каталог</b>\n\n"
        "Откройте в Telegram или браузере:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    text = message.text or ""
    user_id = message.from_user.id if message.from_user else 0
    if _status_rate_limited(user_id):
        await message.answer("⏳ Слишком много запросов. Попробуйте через минуту.")
        return
    order_num = _parse_order_number(text)
    logger.info(f"[status] user={user_id} parsed={order_num!r}")

    if not order_num:
        await message.answer(
            "Использование: <code>/status 12</code>\n\n"
            "Номер заказа вы получили при оформлении.\n"
            "Пример: <code>/status 1</code>",
            parse_mode="HTML",
        )
        return

    # TODO(security/IDOR): номер заказа — единственный «секрет», любой пользователь может
    # перебирать номера. Нужна привязка заказа к клиенту (tracking-код / telegram id) — вне
    # рамок текущей правки. Поэтому здесь отдаём только позицию, прогресс, срок и статус
    # и НЕ показываем имя заказчика.
    try:
        order = sheet.get_order_by_number(order_num)
    except Exception as e:
        logger.error(f"[status] sheet error: {e}", exc_info=e)
        await message.answer("⚠️ Не удалось получить данные о заказе. Попробуйте позже.")
        return

    if not order:
        await message.answer(
            f"❌ Заказ <b>№{_esc(order_num)}</b> не найден.\n\n"
            f"Проверьте номер или напишите @master3Dpech",
            parse_mode="HTML",
        )
        return

    try:
        num, position, qty, printed, deadline, modified, status, customer = order[:8]
    except Exception as e:
        logger.error(f"[status] parse error: {e}", exc_info=e)
        await message.answer("⚠️ Не удалось прочитать заказ. Свяжитесь с нами.")
        return

    try:
        qty_i = int(float(qty))
        printed_i = int(float(printed))
        progress_pct = round(printed_i / qty_i * 100) if qty_i else 0
    except (ValueError, TypeError, OverflowError):
        qty_i = printed_i = progress_pct = 0

    done = str(status).lower().strip() == "да"
    lines = [
        f"📦 <b>Заказ №{_esc(num)}</b>",
        f"Позиция: {_esc(position)}",
        f"Напечатано: {printed_i} / {qty_i} ({progress_pct}%)",
        f"Срок: {_esc(deadline)}",
        f"Статус: {'✅ Готов' if done else '⏳ В работе'}",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")


# ============================================================
# FALLBACK
# ============================================================
@router.message()
async def fallback(message: Message):
    text = message.text or ""
    logger.info(f"[fallback] user={message.from_user.id if message.from_user else 0} len={len(text)}")
    await message.answer(
        "Я понимаю команды:\n\n"
        "/price — каталог товаров\n"
        "/status N — статус заказа\n"
        "/help — контакты"
    )


# ============================================================
# КОМАНДЫ В МЕНЮ
# ============================================================
async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="price", description="Каталог товаров"),
        BotCommand(command="status", description="Статус заказа"),
        BotCommand(command="help", description="Контакты"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("[client_bot] commands registered")
    except Exception as e:
        logger.warning(f"[client_bot] set_commands error: {e}")


def create_client_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return dp
