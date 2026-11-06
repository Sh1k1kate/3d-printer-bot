from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from keyboards import (
    main_menu, cancel_keyboard, calendar_keyboard, my_orders_inline_keyboard, edit_order_keyboard, order_group_keyboard
)
from states import CreateOrder, EditOrder
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer, safe_edit
from datetime import datetime
from production import group_orders
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

MAX_QTY = 1_000_000


def _safe_int(text, min_value=0, max_value=10**9):
    """Только ASCII-цифры, в пределах диапазона; иначе None (никаких исключений)."""
    text = (text or "").strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    value = int(text)
    return value if min_value <= value <= max_value else None


def _order_num_from(data, prefix):
    """callback_data вида <prefix><номер> -> str(номер) или None."""
    num = _safe_int((data or "")[len(prefix):], 0, 10**9)
    return None if num is None else str(num)


def _to_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return default


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


@router.message(CreateOrder.waiting_for_model, F.text, F.text != "❌ Отмена")
async def process_order_model_text(message: Message, state: FSMContext):
    item_name = message.text.strip()
    if not item_name:
        await message.answer("❌ Название не может быть пустым.")
        return
    if len(item_name) > 200:
        await message.answer("❌ Слишком длинное название.")
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
            f"❌ Модель или набор «{item_name}» не найдены.\n"
            "Проверьте название или используйте кнопку 'Список моделей и наборов'."
        )


@router.message(CreateOrder.waiting_for_quantity, F.text, F.text != "❌ Отмена")
async def process_order_quantity(message: Message, state: FSMContext):
    quantity = _safe_int(message.text, 1, MAX_QTY)
    if quantity is None:
        await message.answer("Введите целое положительное число (до 1 000 000).")
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


@router.message(CreateOrder.waiting_for_customer, F.text, F.text != "❌ Отмена")
async def process_order_customer(message: Message, state: FSMContext):
    customer = "" if message.text == "Пропустить" else message.text.strip()
    if len(customer) > 100:
        await message.answer("❌ Имя заказчика слишком длинное (до 100 символов).")
        return
    await state.update_data(order_customer=customer)
    now = datetime.now()
    await message.answer(
        "Выберите срок заказа на календаре:",
        reply_markup=calendar_keyboard(now.year, now.month, prefix="cal_order")
    )
    await state.set_state(CreateOrder.waiting_for_deadline)


# ---------- Календарь для заказов ----------
def _parse_ym(data):
    parts = (data or "").split("_")
    if len(parts) != 5:
        return None
    year = _safe_int(parts[3], 2000, 2100)
    month = _safe_int(parts[4], 1, 12)
    return None if year is None or month is None else (year, month)


@router.callback_query(F.data.startswith("cal_order_prev_"))
async def calendar_order_prev(callback: CallbackQuery):
    ym = _parse_ym(callback.data)
    if ym is None:
        await callback.answer("Ошибка формата")
        return
    year, month = ym
    if month == 1:
        month, year = 12, year - 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_order"))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_order_next_"))
async def calendar_order_next(callback: CallbackQuery):
    ym = _parse_ym(callback.data)
    if ym is None:
        await callback.answer("Ошибка формата")
        return
    year, month = ym
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
    parts = callback.data.split("_")
    try:
        if len(parts) != 5:
            raise ValueError
        year, month, day = (_safe_int(parts[2], 2000, 2100), _safe_int(parts[3], 1, 12), _safe_int(parts[4], 1, 31))
        selected_date = datetime(year, month, day).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        await callback.answer("Ошибка формата", show_alert=True)
        return
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
        except Exception:
            pass
    except Exception:
        logger.exception("Не удалось создать заказ")
        await callback.message.answer("❌ Не удалось создать заказ. Попробуйте ещё раз.")
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


def _find_group(key):
    """Группа активных заказов по ключу из callback (ключ считается заново — состояния в боте нет)."""
    return next((g for g in group_orders(sheet.get_active_orders()) if g["key"] == key), None)


@router.callback_query(F.data.regexp(r"^og_[0-9a-f]{8}$"))
async def view_order_group(callback: CallbackQuery):
    g = _find_group(callback.data[3:])
    if not g:
        await callback.answer("Заказ уже закрыт или изменился — откройте список заново", show_alert=True)
        return
    who = escape_markdown(g["customer"]) if g["customer"] else "без заказчика"
    text = f"📦 *Заказ:* {who}\n📅 Срок: {g['deadline'] or 'не указан'}\n"
    text += f"Напечатано {g['printed']} из {g['ordered']}, осталось {g['remaining']}\n\n"
    for p in g["positions"]:
        mark = "✅" if p["done"] else ("🖨️" if p["remaining"] else "📦")
        text += f"{mark} №{p['id']} {escape_markdown(p['position'])} — {p['printed']}/{p['ordered']}\n"
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=order_group_keyboard(g))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ogdone_[0-9a-f]{8}$"))
async def complete_order_group(callback: CallbackQuery):
    g = _find_group(callback.data[7:])
    if not g:
        await callback.answer("Заказ уже закрыт или изменился — откройте список заново", show_alert=True)
        return
    done = sheet.mark_orders_completed([p["id"] for p in g["positions"] if not p["done"]])
    await callback.answer(f"Заказ выполнен ({done} поз.)", show_alert=True)
    orders = sheet.get_active_orders()
    if orders:
        await safe_edit(callback.message, "Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await safe_edit(callback.message, "Нет активных заказов. 🎉")


@router.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: CallbackQuery):
    order_num = _order_num_from(callback.data, "view_order_")
    order = sheet.get_order_by_number(order_num) if order_num is not None else None
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    order = list(order) + [""] * (8 - len(order))
    num, position, qty, printed, deadline, modified, status, customer = order[:8]
    safe_position = escape_markdown(position)
    safe_customer = escape_markdown(customer) if customer else ""

    text = f"📄 *Заказ №{num}*\n"
    text += f"Позиция: {safe_position}\n"
    text += f"Заказано: {qty} шт.\n"
    text += f"Напечатано: {printed} шт.\n"
    text += f"Осталось: {max(_to_int(qty) - _to_int(printed), 0)} шт.\n"
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
    order_num = _order_num_from(callback.data, "printed_")
    if order_num is None:
        await callback.answer("Ошибка формата", show_alert=True)
        return
    await state.update_data(edit_order_num=order_num)
    await callback.message.answer("Введите новое количество напечатанных (целое число):", reply_markup=cancel_keyboard)
    await state.set_state(EditOrder.waiting_for_new_printed)
    await callback.answer()


@router.message(EditOrder.waiting_for_new_printed, F.text, F.text != "❌ Отмена")
async def process_edit_printed(message: Message, state: FSMContext):
    new_printed = _safe_int(message.text, 0, MAX_QTY)
    if new_printed is None:
        await message.answer("Введите целое неотрицательное число.")
        return
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
    max_qty = _to_int(order[2])
    if new_printed > max_qty:
        await message.answer(f"❌ Нельзя напечатать больше заказанного ({max_qty}).")
        return
    sheet.update_order_printed(order_num, new_printed)
    await message.answer(f"✅ Напечатанное количество обновлено: {new_printed} шт.", reply_markup=main_menu)
    await state.clear()


# Регэксп: complete_task_<id> (tasks.py) не должен попадать сюда
@router.callback_query(F.data.regexp(r"^complete_[0-9]+$"))
async def mark_completed(callback: CallbackQuery):
    order_num = _order_num_from(callback.data, "complete_")
    if order_num is None:
        await callback.answer("Ошибка формата", show_alert=True)
        return
    if not sheet.mark_order_completed(order_num):
        await callback.answer("Заказ не найден", show_alert=True)
        return
    await callback.answer("Заказ выполнен!", show_alert=True)
    orders = sheet.get_active_orders()
    if orders:
        await safe_edit(callback.message, "Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await safe_edit(callback.message, "Нет активных заказов. 🎉")


# ✅ ПОЧИНЕНО: main_menu через reply-keyboard нельзя сделать edit_text
@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    # Убираем inline-сообщение (best-effort) и шлём новое с ReplyKeyboard
    try:
        await callback.message.delete()
    except Exception:
        pass
    try:
        await callback.message.answer("🏠 Главное меню:", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Не удалось отправить главное меню: {e}")
    await callback.answer()
