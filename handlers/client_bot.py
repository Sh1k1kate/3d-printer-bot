import os
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

PUBLIC_URL = os.getenv("PUBLIC_URL", "")


def _kb_price():
    if not PUBLIC_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Открыть каталог", web_app=WebAppInfo(url=f"{PUBLIC_URL}/price"))],
        [InlineKeyboardButton(text="🔗 В браузере", url=f"{PUBLIC_URL}/price")],
    ])


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Добро пожаловать в <b>Kobra Print</b>!\n\n"
        "Мы печатаем на заказ — от сувениров до функциональных деталей.\n\n"
        "• /price — каталог товаров и цен\n"
        "• /status N — статус заказа (N — номер, напр. /status 12)\n"
        "• /help — контакты\n\n"
        "По любым вопросам — пишите нам!",
        parse_mode="HTML",
        reply_markup=_kb_price(),
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
        "По вопросам заказов — /price\n"
        "Статус заказа — /status <номер>",
        parse_mode="HTML",
    )


@router.message(Command("price"))
async def cmd_price(message: Message):
    if not PUBLIC_URL:
        await message.answer("Каталог временно недоступен. Свяжитесь с нами: @master3Dpech")
        return
    await message.answer(
        "🛍 <b>Наш каталог</b>\n\n"
        "Открыть в Telegram или браузере:",
        parse_mode="HTML",
        reply_markup=_kb_price(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message):
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "Использование: <code>/status 12</code>\n"
            "Номер заказа вы получили при оформлении.",
            parse_mode="HTML",
        )
        return
    order_num = args[1]
    order = sheet.get_order_by_number(order_num)
    if not order:
        await message.answer(f"❌ Заказ №{order_num} не найден.\nПроверьте номер или напишите @master3Dpech")
        return
    try:
        num, position, qty, printed, deadline, modified, status, customer = order[:8]
    except Exception:
        await message.answer("Не удалось получить данные о заказе. Свяжитесь с нами.")
        return
    try:
        qty_i = int(qty)
        printed_i = int(printed)
        progress_pct = round(printed_i / qty_i * 100) if qty_i else 0
    except Exception:
        qty_i = printed_i = progress_pct = 0
    done = status.lower() == "да"
    lines = [
        f"📦 <b>Заказ №{num}</b>",
        f"Позиция: {position}",
        f"Напечатано: {printed_i} / {qty_i} ({progress_pct}%)",
        f"Срок: {deadline}",
        f"Статус: {'✅ Готов' if done else '⏳ В работе'}",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Я понимаю только команды:\n"
        "/price — каталог\n"
        "/status N — статус заказа\n"
        "/help — контакты"
    )


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="price", description="Каталог товаров"),
        BotCommand(command="status", description="Статус заказа"),
        BotCommand(command="help", description="Контакты"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
    except Exception as e:
        logger.warning(f"set_commands client: {e}")


def create_client_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return dp
  
