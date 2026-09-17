from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from keyboards import main_menu, cancel_keyboard
from google_sheets import SheetManager
import re
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    user_id = message.from_user.id
    name = message.from_user.full_name or str(user_id)
    if sheet.add_subscriber(user_id, name):
        await message.answer("✅ Вы подписались на общие уведомления о задачах.")
    else:
        await message.answer("ℹ️ Вы уже подписаны на уведомления.")


@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    user_id = message.from_user.id
    if sheet.remove_subscriber(user_id):
        await message.answer("✅ Вы отписались от общих уведомлений.")
    else:
        await message.answer("ℹ️ Вы не были подписаны на уведомления.")


@router.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@router.message(Command("settings"))
async def settings(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_settings = sheet.get_user_settings(user_id)
    morning_time = user_settings.get("morning_time", "09:00")
    await message.answer(
        f"⚙️ *Настройки уведомлений*\n\n"
        f"Текущее время утреннего уведомления: {morning_time}\n"
        f"Введите новое время в формате `ЧЧ:ММ` (например, `09:00`):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state("waiting_morning_time")


@router.message(StateFilter("waiting_morning_time"), F.text != "❌ Отмена")
async def set_morning_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        await message.answer("❌ Неверный формат. Введите ЧЧ:ММ")
        return
    hours, minutes = time_str.split(':')
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        await message.answer("❌ Неверное время.")
        return
    user_id = message.from_user.id
    if sheet.set_user_settings(user_id, morning_time=time_str):
        await message.answer(f"✅ Время утреннего уведомления установлено: {time_str}", reply_markup=main_menu)
    else:
        await message.answer("❌ Ошибка сохранения настроек.", reply_markup=main_menu)
    await state.clear()
