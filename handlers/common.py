from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import ALLOWED_USERS
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


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
        if not is_allowed(event.from_user.id):
            await event.answer("⛔ Доступ запрещён. Вы не авторизованы для использования этого бота.")
            return
        return await handler(event, data)


def format_time(minutes: int) -> str:
    if minutes <= 0:
        return "—"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}ч"
    return f"{hours}ч {mins}мин"


def format_model_info(model_name, details):
    text = f"📦 *{model_name}*\n\n"
    for i, (det_name, on_pallet, per_unit, time_pp, grams_pp) in enumerate(details, 1):
        text += f"🔹 *Деталь {i}:* {det_name}\n"
        text += f"   └ На палете: {on_pallet} шт.\n"
        text += f"   └ Нужно на единицу модели: {per_unit} шт.\n"
        text += f"   └ Время печати 1 палета: {format_time(time_pp)}\n"
        text += f"   └ Грамм на 1 палет: {grams_pp} г\n\n"
    return text


def format_kit_info(kit_name, kit_data):
    name, items_text, price, desc = kit_data
    text = f"🎁 *Набор: {name}*\n\n"
    text += f"📋 *Состав:* {items_text}\n"
    if price:
        text += f"💰 *Цена:* {price} руб.\n"
    if desc:
        text += f"📄 *Описание:* {desc}\n"
    return text


def parse_callback_data(data: str, separator: str = "|") -> list:
    if separator in data:
        return data.split(separator)
    return data.split("_")
