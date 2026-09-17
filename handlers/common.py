from aiogram import Router, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import ALLOWED_USERS
import logging
import re

logger = logging.getLogger(__name__)

router = Router()


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = getattr(event.from_user, "id", None) if hasattr(event, "from_user") else None
        if user_id and not is_allowed(user_id):
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            else:
                await event.answer("⛔ Доступ запрещён. Вы не авторизованы для использования этого бота.")
            return
        return await handler(event, data)


def escape_markdown(text) -> str:
    """Экранирует спецсимволы Markdown V1 в пользовательских строках."""
    if text is None:
        return ""
    return re.sub(r"([_*`\[\]()~])", r"\\\1", str(text))


async def safe_send(bot, chat_id: int, text: str, **kwargs):
    """Безопасная отправка сообщения: при ошибке Markdown шлёт как plain-text."""
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        if "can't parse entities" in str(e):
            logger.warning(f"Markdown parse error (send), fallback to plain: {e}")
            kwargs.pop("parse_mode", None)
            return await bot.send_message(chat_id, text, **kwargs)
        raise


async def safe_edit(message, text: str, **kwargs):
    """Безопасное редактирование: при ошибке Markdown редактирует как plain-text."""
    try:
        return await message.edit_text(text, **kwargs)
    except Exception as e:
        err_str = str(e)
        if "can't parse entities" in err_str:
            logger.warning(f"Markdown parse error (edit), fallback to plain: {e}")
            kwargs.pop("parse_mode", None)
            try:
                return await message.edit_text(text, **kwargs)
            except Exception as e2:
                logger.warning(f"Edit fallback error: {e2}")
                return None
        # Ошибки типа "message is not modified" — игнорируем
        logger.warning(f"Edit error: {e}")
        return None


async def safe_answer(message, text: str, **kwargs):
    """Безопасный ответ на сообщение: при ошибке Markdown — plain-text."""
    try:
        return await message.answer(text, **kwargs)
    except Exception as e:
        if "can't parse entities" in str(e):
            logger.warning(f"Markdown parse error (answer), fallback to plain: {e}")
            kwargs.pop("parse_mode", None)
            return await message.answer(text, **kwargs)
        raise


# ---------- Игнор пустых callback (календарь, заголовки) ----------
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()


# ---------- Fallback для необработанных callback ----------
@router.callback_query()
async def fallback_callback(callback: CallbackQuery):
    logger.warning(f"Необработанный callback: {callback.data} (от {callback.from_user.id})")
    try:
        await callback.answer(
            "⚠️ Кнопка устарела. Откройте меню заново командой /start.",
            show_alert=True
        )
    except Exception:
        pass


# ---------- Fallback для сообщений ----------
@router.message()
async def fallback_message(message: Message):
    if message.text:
        logger.warning(f"Необработанное сообщение от {message.from_user.id}: {message.text[:50]}")
        if message.text.startswith("/"):
            await message.answer("🤔 Неизвестная команда. Введите /help для списка команд.")


def format_time(minutes: int) -> str:
    if minutes <= 0:
        return "—"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}ч"
    return f"{hours}ч {mins}мин"


def format_model_info(model_name, details):
    safe_name = escape_markdown(model_name)
    text = f"📦 *{safe_name}*\n\n"
    for i, (det_name, on_pallet, per_unit, time_pp, grams_pp) in enumerate(details, 1):
        safe_det = escape_markdown(det_name)
        text += f"🔹 *Деталь {i}:* {safe_det}\n"
        text += f"   └ На палете: {on_pallet} шт.\n"
        text += f"   └ Нужно на единицу модели: {per_unit} шт.\n"
        text += f"   └ Время печати 1 палета: {format_time(time_pp)}\n"
        text += f"   └ Грамм на 1 палет: {grams_pp} г\n\n"
    return text


def format_kit_info(kit_name, kit_data):
    name, items_text, price, desc = kit_data
    safe_name = escape_markdown(name)
    safe_items = escape_markdown(items_text)
    safe_desc = escape_markdown(desc)
    text = f"🎁 *Набор: {safe_name}*\n\n"
    text += f"📋 *Состав:* {safe_items}\n"
    if price:
        text += f"💰 *Цена:* {price} руб.\n"
    if desc:
        text += f"📄 *Описание:* {safe_desc}\n"
    return text


def parse_callback_data(data: str, separator: str = "|") -> list:
    if separator in data:
        return data.split(separator)
    return data.split("_")
