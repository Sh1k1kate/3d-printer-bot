from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from keyboards import cancel_keyboard, main_menu
from states import AddPrice
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()


@router.message(Command("add_price"))
async def add_price_start(message: Message, state: FSMContext):
    await state.clear()
    await safe_answer(
        message,
        "🛒 *Добавление товара в прайс*\n\nВведите *название товара*:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddPrice.waiting_for_name)


@router.message(AddPrice.waiting_for_name, F.text != "❌ Отмена")
async def price_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return
    await state.update_data(name=name)
    await safe_answer(message, "Введите *описание* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_description)


@router.message(AddPrice.waiting_for_description, F.text != "❌ Отмена")
async def price_desc(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() == "нет":
        desc = ""
    await state.update_data(description=desc)
    await safe_answer(message, "Введите *URL фото* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_photo)


@router.message(AddPrice.waiting_for_photo, F.text != "❌ Отмена")
async def price_photo(message: Message, state: FSMContext):
    photo = message.text.strip()
    if photo.lower() == "нет":
        photo = ""
    await state.update_data(photo=photo)
    await safe_answer(message, "Введите *розничную цену* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_retail)


@router.message(AddPrice.waiting_for_retail, F.text != "❌ Отмена")
async def price_retail(message: Message, state: FSMContext):
    text = message.text.strip()
    retail = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(retail=retail)
    await safe_answer(message, "Введите *оптовую цену* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_wholesale)


@router.message(AddPrice.waiting_for_wholesale, F.text != "❌ Отмена")
async def price_wholesale(message: Message, state: FSMContext):
    text = message.text.strip()
    wholesale = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(wholesale=wholesale)
    await safe_answer(message, "Введите *минимальное количество для опта* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_wholesale_from)


@router.message(AddPrice.waiting_for_wholesale_from, F.text != "❌ Отмена")
async def price_wholesale_from(message: Message, state: FSMContext):
    text = message.text.strip()
    wholesale_from = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(wholesale_from=wholesale_from)
    cats = sheet.get_price_categories()
    if cats:
        cats_text = ", ".join(cats[:15])
        await safe_answer(
            message,
            f"Введите *категорию* (или 'нет'):\nСуществующие: {escape_markdown(cats_text)}",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
    else:
        await safe_answer(message, "Введите *категорию* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_category)


@router.message(AddPrice.waiting_for_category, F.text != "❌ Отмена")
async def price_category(message: Message, state: FSMContext):
    cat = message.text.strip()
    if cat.lower() == "нет":
        cat = "Без категории"
    data = await state.get_data()
    ok = sheet.add_price_item(
        data["name"], data.get("description", ""), data.get("photo", ""),
        data.get("retail", ""), data.get("wholesale", ""),
        data.get("wholesale_from", ""), cat
    )
    if ok:
        await safe_answer(
            message,
            f"✅ Товар *{escape_markdown(data['name'])}* добавлен в прайс!\n"
            f"Смотреть: /price",
            parse_mode="Markdown",
            reply_markup=main_menu
        )
    else:
        await message.answer("❌ Не удалось добавить товар.", reply_markup=main_menu)
    await state.clear()


@router.message(StateFilter(AddPrice), F.text == "❌ Отмена")
async def cancel_add_price(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добавление товара отменено.", reply_markup=main_menu)
