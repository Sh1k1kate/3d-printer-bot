from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from keyboards import (
    main_menu, cancel_keyboard, calendar_keyboard, my_orders_inline_keyboard, edit_order_keyboard
)
from states import CreateOrder, EditOrder
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer, safe_edit
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()


# ---------- Создание заказа (текстовый ввод) ----------
@router.message(F.text == "🛒 Создать заказ")
async def create_order_start(message: Message, state: FSMContext):
    await state.set_state(CreateOrder.waiting_for_model)
    await safe_answer(
        message,
        "✏️ Введите *название модели или набора*, который хотите заказать:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )


@router.message(CreateOrder.waiting_for_model, F.text != "❌ Отмена")
async def process_order_model_text(message: Message, state: FSMContext):
    item_name = message.text.strip()
    if not item_name:
        await message.answer("❌ Название не может быть пустым.")
        return

    models = sheet.get_all_models()
    kits = sheet.get_all_kits()

    if item_name in models:
        await state.update_data(order_item=item_name, order_type="model")
        await safe_answer(
            message,
            f"🛒 Заказ модели *{escape_markdown(item_name)}*\nВведите количество (целое число):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateOrder.waiting_for_quantity)
    elif item_name in kits:
        await state.update_data(order_item=item_name, order_type="kit")
        await safe_answer(
            message,
            f"🛒 Заказ набора *{escape_markdown(item_name)}*\nВведите количество (целое число):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateOrder.waiting_for_quantity)
    else:
        await message.answer(
            f"❌ Модель или набор '{item_name}' не найдены.\n"
            "Проверьте название или используйте кнопку 'Список моделей и наборов'."
        )


@router.message(CreateOrder.waiting_for_quantity, F.text != "❌ Отмена")
async def process_order_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите целое положительное число.")
        return
    quantity = int(message.text)
    if quantity <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    await state.update_data(order_quantity=quantity)
    await message.answer(
        "Введите *имя заказчика* (или нажмите 'Пропустить'):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Пропустить")], [KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    )
    await state.set_state(CreateOrder.waiting_for_customer)


@router.message(CreateOrder.waiting_for_customer, F.text != "❌ Отмена")
async def process_order_customer(message: Message, state: FSMContext):
    customer = "" if message.text == "Пропустить" else message.text.strip()
    await state.update_data(order_customer=customer)
    now = datetime.now()
    await message.answer(
        "Выберите срок заказа на календаре:",
        reply_markup=calendar_keyboard(now.year, now.month, prefix="cal_order")
    )
    await state.set_state(CreateOrder.waiting_for_deadline)


# ---------- Календарь для заказов ----------
@router.callback_query(F.data.startswith("cal_order_prev_"))
async def calendar_order_prev(callback: CallbackQuery):
    data = callback.data.split("_")
    year, month = int(data[3]), int(data[4])
    if month == 1:
        month, year = 12, year - 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_order"))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_order_next_"))
async def calendar_order_next(callback: CallbackQuery):
    data = callback.data.split("_")
    year, month = int(data[3]), int(data[4])
    if month == 12:
        month, year = 1, year + 1
    else:
        month += 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_order"))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_order_"))
async def calendar_order_day(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != CreateOrder.waiting_for_deadline:
        await callback.answer("Ошибка: неверное состояние", show_alert=True)
        return
    data = callback.data.split("_")
    year, month, day = int(data[2]), int(data[3]), int(data[4])
    selected_date = datetime(year, month, day).strftime("%Y-%m-%d")
    user_data = await state.get_data()
    item_name = user_data.get("order_item")
    order_type = user_data.get("order_type")
    quantity = user_data.get("order_quantity")
    customer = user_data.get("order_customer", "")
    if not item_name or not quantity:
        await callback.answer("Ошибка: данные заказа потеряны.", show_alert=True)
        await state.clear()
        return
    position = item_name if order_type == "model" else f"Набор: {item_name}"
    try:
        order_num = sheet.add_order(position, quantity, selected_date, customer)
        text = (
            f"✅ Заказ №{order_num} создан!\n\n"
            f"Позиция: {escape_markdown(position)}\n"
            f"Количество: {quantity} шт.\n"
            f"Срок: {selected_date}\n"
            f"Статус: в работе"
        )
        if customer:
            text += f"\n👤 Заказчик: {escape_markdown(customer)}"
        await safe_answer(callback.message, text, parse_mode="Markdown", reply_markup=main_menu)
        try:
            await callback.message.delete()
        except:
            pass
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await callback.answer()


# ---------- Мои заказы ----------
@router.message(F.text == "📦 Мои заказы")
async def show_my_orders(message: Message):
    orders = sheet.get_active_orders()
    if not orders:
        await message.answer("📭 У вас нет активных заказов.")
        return
    await message.answer("Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))


@router.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: CallbackQuery):
    order_num = callback.data.split("_")[-1]
    order = sheet.get_order_by_number(order_num)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    num, position, qty, printed, deadline, modified, status, customer = order[:8]
    safe_position = escape_markdown(position)
    safe_customer = escape_markdown(customer) if customer else ""

    text = f"📄 *Заказ №{num}*\n"
    text += f"Позиция: {safe_position}\n"
    text += f"Заказано: {qty} шт.\n"
    text += f"Напечатано: {printed} шт.\n"
    text += f"Осталось: {int(qty)-int(printed)} шт.\n"
    text += f"Срок: {deadline}\n"
    text += f"Статус: {'✅ Выполнен' if status.lower() == 'да' else '⏳ В работе'}\n"
    if customer:
        text += f"👤 Заказчик: {safe_customer}\n"
    if position.startswith("Набор: "):
        kit_name = position[7:]
        kit_data = sheet.get_kit_details(kit_name)
        if kit_data:
            text += f"🎁 *Состав набора:* {escape_markdown(kit_data[1])}\n"
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=edit_order_keyboard(num))
    await callback.answer()


@router.callback_query(F.data == "back_to_orders")
async def back_to_orders(callback: CallbackQuery):
    orders = sheet.get_active_orders()
    if orders:
        await safe_edit(callback.message, "Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await safe_edit(callback.message, "Нет активных заказов.")
    await callback.answer()


@router.callback_query(F.data.startswith("printed_"))
async def start_edit_printed(callback: CallbackQuery, state: FSMContext):
    order_num = callback.data.split("_")[-1]
    await state.update_data(edit_order_num=order_num)
    await callback.message.answer("Введите новое количество напечатанных (целое число):", reply_markup=cancel_keyboard)
    await state.set_state(EditOrder.waiting_for_new_printed)
    await callback.answer()


@router.message(EditOrder.waiting_for_new_printed, F.text != "❌ Отмена")
async def process_edit_printed(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите целое число.")
        return
    new_printed = int(message.text)
    data = await state.get_data()
    order_num = data.get("edit_order_num")
    if not order_num:
        await message.answer("Ошибка: данные потеряны.")
        await state.clear()
        return
    order = sheet.get_order_by_number(order_num)
    if not order:
        await message.answer("Заказ не найден.")
        await state.clear()
        return
    max_qty = int(order[2])
    if new_printed > max_qty:
        await message.answer(f"❌ Нельзя напечатать больше заказанного ({max_qty}).")
        return
    sheet.update_order_printed(order_num, new_printed)
    await message.answer(f"✅ Напечатанное количество обновлено: {new_printed} шт.", reply_markup=main_menu)
    await state.clear()


@router.callback_query(F.data.startswith("complete_"))
async def mark_completed(callback: CallbackQuery):
    order_num = callback.data.split("_")[-1]
    sheet.mark_order_completed(order_num)
    await callback.answer("Заказ выполнен!", show_alert=True)
    orders = sheet.get_active_orders()
    if orders:
        await safe_edit(callback.message, "Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await safe_edit(callback.message, "Нет активных заказов. 🎉")
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    await safe_edit(callback.message, "Главное меню:", reply_markup=main_menu)
    await callback.answer()
