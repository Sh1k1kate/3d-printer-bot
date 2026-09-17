from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from keyboards import (
    main_menu, cancel_keyboard, calendar_keyboard, my_orders_inline_keyboard, edit_order_keyboard,
    items_inline_keyboard
)
from states import CreateOrder, EditOrder
from google_sheets import SheetManager
from .common import format_model_info, format_kit_info
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

# ---------- Создание заказа (текстовый ввод) ----------
@router.message(F.text == "🛒 Создать заказ")
async def create_order_start(message: Message, state: FSMContext):
    await state.set_state(CreateOrder.waiting_for_model)
    await message.answer(
        "✏️ Введите *название модели или набора*, который хотите заказать:\n"
        "(можно ввести существующее название из списка)",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.message(CreateOrder.waiting_for_model, F.text != "❌ Отмена")
async def process_order_model_text(message: Message, state: FSMContext):
    item_name = message.text.strip()
    if not item_name:
        await message.answer("❌ Название не может быть пустым. Введите название модели или набора:")
        return

    models = sheet.get_all_models()
    kits = sheet.get_all_kits()

    if item_name in models:
        order_type = "model"
        await state.update_data(order_item=item_name, order_type=order_type)
        await message.answer(
            f"🛒 Заказ модели *{item_name}*\nВведите количество (целое число):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateOrder.waiting_for_quantity)
    elif item_name in kits:
        order_type = "kit"
        await state.update_data(order_item=item_name, order_type=order_type)
        await message.answer(
            f"🛒 Заказ набора *{item_name}*\nВведите количество (целое число):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateOrder.waiting_for_quantity)
    else:
        await message.answer(
            f"❌ Модель или набор с именем '{item_name}' не найдены.\n"
            "Проверьте название и попробуйте снова, или используйте кнопку 'Список моделей и наборов' для просмотра."
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
    if message.text == "Пропустить":
        customer = ""
    else:
        customer = message.text.strip()
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
    year = int(data[3])
    month = int(data[4])
    if month == 1:
        month = 12
        year -= 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_order"))
    await callback.answer()

@router.callback_query(F.data.startswith("cal_order_next_"))
async def calendar_order_next(callback: CallbackQuery):
    data = callback.data.split("_")
    year = int(data[3])
    month = int(data[4])
    if month == 12:
        month = 1
        year += 1
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
    year = int(data[2])
    month = int(data[3])
    day = int(data[4])
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
        await callback.message.answer(
            f"✅ Заказ №{order_num} создан!\n\n"
            f"Позиция: {position}\n"
            f"Количество: {quantity} шт.\n"
            f"Срок: {selected_date}\n"
            f"Статус: в работе"
            + (f"\n👤 Заказчик: {customer}" if customer else ""),
            reply_markup=main_menu
        )
        await callback.message.delete()
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await callback.answer()

# ---------- Мои заказы ----------
@router.message(F.text == "📦 Мои заказы")
async def show_my_orders(message: Message):
    orders = sheet.get_active_orders()
    if not orders:
        await message.answer("📭 У вас нет активных заказов. Создайте новый через кнопку 'Создать заказ'.")
        return
    await message.answer("Выберите заказ для просмотра или редактирования:", reply_markup=my_orders_inline_keyboard(orders))

@router.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: CallbackQuery):
    order_num = callback.data.split("_")[-1]
    order = sheet.get_order_by_number(order_num)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    num, position, qty, printed, deadline, modified, status, customer = order[:8]
    text = f"📄 *Заказ №{num}*\n"
    text += f"Позиция: {position}\n"
    text += f"Заказано: {qty} шт.\n"
    text += f"Напечатано: {printed} шт.\n"
    text += f"Осталось: {int(qty)-int(printed)} шт.\n"
    text += f"Срок: {deadline}\n"
    text += f"Статус: {'✅ Выполнен' if status.lower() == 'да' else '⏳ В работе'}\n"
    if customer:
        text += f"👤 Заказчик: {customer}\n"
    if position.startswith("Набор: "):
        kit_name = position[7:]
        kit_data = sheet.get_kit_details(kit_name)
        if kit_data:
            text += f"🎁 *Состав набора:* {kit_data[1]}\n"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=edit_order_keyboard(num))
    await callback.answer()

@router.callback_query(F.data == "back_to_orders")
async def back_to_orders(callback: CallbackQuery):
    orders = sheet.get_active_orders()
    if orders:
        await callback.message.edit_text("Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await callback.message.edit_text("Нет активных заказов.")
    await callback.answer()

@router.callback_query(F.data.startswith("printed_"))
async def start_edit_printed(callback: CallbackQuery, state: FSMContext):
    order_num = callback.data.split("_")[-1]
    await state.update_data(edit_order_num=order_num)
    await callback.message.answer("Введите новое количество напечатанных экземпляров (целое число):", reply_markup=cancel_keyboard)
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
        await message.answer(f"❌ Нельзя напечатать больше, чем заказано ({max_qty}).")
        return
    sheet.update_order_printed(order_num, new_printed)
    await message.answer(f"✅ Для заказа №{order_num} напечатанное количество обновлено: {new_printed} шт.", reply_markup=main_menu)
    await state.clear()

@router.callback_query(F.data.startswith("complete_"))
async def mark_completed(callback: CallbackQuery):
    order_num = callback.data.split("_")[-1]
    sheet.mark_order_completed(order_num)
    await callback.answer("Заказ отмечен выполненным!", show_alert=True)
    orders = sheet.get_active_orders()
    if orders:
        await callback.message.edit_text("Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await callback.message.edit_text("Нет активных заказов. 🎉")
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu)
    await callback.answer()
