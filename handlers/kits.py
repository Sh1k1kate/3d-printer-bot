from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from keyboards import (
    main_menu, cancel_keyboard, kit_action_keyboard, kit_parameters_keyboard,
    select_model_keyboard, show_current_items_keyboard
)
from states import AddKit, EditKit
from google_sheets import SheetManager
from .common import format_kit_info, escape_markdown, safe_answer, safe_edit
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()


@router.message(F.text == "➕ Добавить набор")
async def add_kit_start(message: Message, state: FSMContext):
    await state.clear()
    models = sheet.get_all_models()
    if not models:
        await message.answer("❌ Сначала добавьте хотя бы одну модель.")
        return
    await message.answer("Введите *название набора*:", reply_markup=cancel_keyboard)
    await state.set_state(AddKit.waiting_for_kit_name)


@router.message(AddKit.waiting_for_kit_name, F.text != "❌ Отмена")
async def process_kit_name(message: Message, state: FSMContext):
    kit_name = message.text.strip()
    existing = sheet.get_all_kits()
    if kit_name in existing:
        await message.answer("❌ Набор с таким названием уже существует.")
        return
    await state.update_data(kit_name=kit_name, kit_items=[])
    models = sheet.get_all_models()
    await safe_answer(
        message,
        f"Набор *{escape_markdown(kit_name)}*\n\nДобавьте модели:",
        parse_mode="Markdown",
        reply_markup=select_model_keyboard(models, prefix="add_kit_model")
    )
    await state.set_state(AddKit.waiting_for_item)


@router.callback_query(AddKit.waiting_for_item, F.data.startswith("add_kit_model_"))
async def add_kit_select_model(callback: CallbackQuery, state: FSMContext):
    data = callback.data[14:]
    if data.startswith("page_"):
        page = int(data.split('_')[1])
        models = sheet.get_all_models()
        await callback.message.edit_reply_markup(
            reply_markup=select_model_keyboard(models, page=page, prefix="add_kit_model")
        )
        await callback.answer()
        return
    model_name = data
    await state.update_data(selected_model=model_name)
    await safe_answer(
        callback.message,
        f"Модель *{escape_markdown(model_name)}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddKit.waiting_for_quantity_for_item)
    await callback.answer()


@router.message(AddKit.waiting_for_quantity_for_item, F.text != "❌ Отмена")
async def add_kit_process_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите целое положительное число.")
        return
    qty = int(message.text)
    if qty <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    data = await state.get_data()
    model_name = data.get("selected_model")
    if not model_name:
        await message.answer("Ошибка: модель не выбрана.")
        await state.clear()
        return
    items = data.get("kit_items", [])
    for i, (m, q) in enumerate(items):
        if m == model_name:
            items[i] = (m, q + qty)
            break
    else:
        items.append((model_name, qty))
    await state.update_data(kit_items=items)
    await message.answer(f"✅ Добавлено: {escape_markdown(model_name)} x{qty}.")
    models = sheet.get_all_models()
    await message.answer("Выберите следующую модель:", reply_markup=select_model_keyboard(models, prefix="add_kit_model"))
    await state.set_state(AddKit.waiting_for_item)


@router.callback_query(AddKit.waiting_for_item, F.data == "add_kit_done")
async def add_kit_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("kit_items", [])
    if not items:
        await callback.answer("Вы не добавили ни одной модели.", show_alert=True)
        return
    items_text = ", ".join([f"{model} x{count}" for model, count in items])
    await state.update_data(kit_items_text=items_text)
    await callback.message.answer("Введите *цену набора* (число):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddKit.waiting_for_price)
    await callback.answer()


@router.message(AddKit.waiting_for_price, F.text != "❌ Отмена")
async def process_kit_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(',', '.'))
    except:
        await message.answer("❌ Введите число (цену).")
        return
    await state.update_data(kit_price=price)
    await message.answer("Введите *описание набора* (или 'нет'):", parse_mode="Markdown")
    await state.set_state(AddKit.waiting_for_description)


@router.message(AddKit.waiting_for_description, F.text != "❌ Отмена")
async def process_kit_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() == "нет":
        desc = ""
    data = await state.get_data()
    kit_name = data["kit_name"]
    items_text = data["kit_items_text"]
    price = data["kit_price"]
    sheet.add_kit(kit_name, items_text, price, desc)
    await safe_answer(
        message,
        f"✅ Набор *{escape_markdown(kit_name)}* добавлен!",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()


@router.message(StateFilter(AddKit), F.text == "❌ Отмена")
async def cancel_add_kit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добавление набора отменено.", reply_markup=main_menu)


# ---------- Редактирование ----------
@router.callback_query(F.data.startswith("edit_kit_"))
async def edit_kit_start(callback: CallbackQuery):
    kit_name = callback.data[9:]
    kit_data = sheet.get_kit_details(kit_name)
    if not kit_data:
        await callback.answer("Набор не найден", show_alert=True)
        return
    await safe_edit(
        callback.message,
        f"✏️ Редактирование набора *{escape_markdown(kit_name)}*",
        parse_mode="Markdown",
        reply_markup=kit_parameters_keyboard(kit_name)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_kit_param_"))
async def edit_kit_param_start(callback: CallbackQuery, state: FSMContext):
    data = callback.data[15:]
    parts = data.split('_')
    if len(parts) < 2:
        await callback.answer("Ошибка формата")
        return
    param = parts[-1]
    kit_name = '_'.join(parts[:-1])
    kit_data = sheet.get_kit_details(kit_name)
    if not kit_data:
        await callback.answer("Набор не найден", show_alert=True)
        return
    if param == "name":
        current = kit_data[0]
        prompt = "Введите новое *название набора*:"
        await ask_edit_kit_value(callback, state, kit_name, param, current, prompt)
    elif param == "items":
        items = sheet.parse_kit_items(kit_name)
        await state.update_data(edit_kit_name=kit_name, edit_kit_items=items)
        items_display = "\n".join([f"• {escape_markdown(m)} x{q}" for m, q in items]) if items else "Пока пусто"
        await safe_edit(
            callback.message,
            f"📋 *Текущий состав набора {escape_markdown(kit_name)}:*\n{items_display}",
            parse_mode="Markdown",
            reply_markup=show_current_items_keyboard(items)
        )
        await state.set_state(EditKit.waiting_for_item_edit)
        await callback.answer()
        return
    elif param == "price":
        current = kit_data[2]
        prompt = "Введите новую *цену*:"
        await ask_edit_kit_value(callback, state, kit_name, param, current, prompt)
    elif param == "desc":
        current = kit_data[3] if len(kit_data) > 3 else ""
        prompt = "Введите новое *описание* (или 'нет'):"
        await ask_edit_kit_value(callback, state, kit_name, param, current, prompt)
    else:
        await callback.answer("Неизвестный параметр")


async def ask_edit_kit_value(callback, state, kit_name, param, current, prompt):
    await state.update_data(
        edit_kit_name=kit_name,
        edit_kit_param=param,
        edit_kit_current=current
    )
    await safe_answer(
        callback.message,
        f"{prompt}\n\nТекущее значение: *{escape_markdown(current)}*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditKit.waiting_for_new_value)
    await callback.answer()


@router.callback_query(EditKit.waiting_for_item_edit, F.data == "edit_kit_add")
async def edit_kit_add_model(callback: CallbackQuery, state: FSMContext):
    models = sheet.get_all_models()
    if not models:
        await callback.answer("Нет доступных моделей", show_alert=True)
        return
    await safe_edit(
        callback.message,
        "Выберите модель для добавления:",
        reply_markup=select_model_keyboard(models, prefix="edit_kit_model")
    )
    await state.update_data(edit_kit_action="add")
    await callback.answer()


@router.callback_query(EditKit.waiting_for_item_edit, F.data.startswith("edit_kit_model_"))
async def edit_kit_select_model(callback: CallbackQuery, state: FSMContext):
    data = callback.data[15:]
    if data.startswith("page_"):
        page = int(data.split('_')[1])
        models = sheet.get_all_models()
        await callback.message.edit_reply_markup(reply_markup=select_model_keyboard(models, page=page, prefix="edit_kit_model"))
        await callback.answer()
        return
    model_name = data
    await state.update_data(edit_selected_model=model_name)
    await safe_answer(
        callback.message,
        f"Модель *{escape_markdown(model_name)}*\nВведите количество:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditKit.waiting_for_quantity_edit)
    await callback.answer()


@router.message(EditKit.waiting_for_quantity_edit, F.text != "❌ Отмена")
async def edit_kit_process_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите целое положительное число.")
        return
    qty = int(message.text)
    if qty <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    data = await state.get_data()
    model_name = data.get("edit_selected_model")
    kit_name = data.get("edit_kit_name")
    items = data.get("edit_kit_items", [])
    if not model_name or not kit_name:
        await message.answer("Ошибка: данные потеряны.")
        await state.clear()
        return
    for i, (m, q) in enumerate(items):
        if m == model_name:
            items[i] = (m, q + qty)
            break
    else:
        items.append((model_name, qty))
    await state.update_data(edit_kit_items=items)
    items_text = ", ".join([f"{m} x{q}" for m, q in items])
    sheet.update_kit_field(kit_name, 'items', items_text)
    await message.answer(f"✅ Добавлено: {escape_markdown(model_name)} x{qty}.")
    items_display = "\n".join([f"• {escape_markdown(m)} x{q}" for m, q in items])
    await safe_answer(
        message,
        f"📋 *Текущий состав набора {escape_markdown(kit_name)}:*\n{items_display}",
        parse_mode="Markdown",
        reply_markup=show_current_items_keyboard(items)
    )
    await state.set_state(EditKit.waiting_for_item_edit)


@router.callback_query(EditKit.waiting_for_item_edit, F.data.startswith("remove_kit_item_"))
async def edit_kit_remove_item(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split('_')[-1])
    data = await state.get_data()
    items = data.get("edit_kit_items", [])
    kit_name = data.get("edit_kit_name")
    if not items or index >= len(items):
        await callback.answer("Ошибка: позиция не найдена")
        return
    removed = items.pop(index)
    await state.update_data(edit_kit_items=items)
    items_text = ", ".join([f"{m} x{q}" for m, q in items])
    sheet.update_kit_field(kit_name, 'items', items_text)
    items_display = "\n".join([f"• {escape_markdown(m)} x{q}" for m, q in items])
    await safe_edit(
        callback.message,
        f"🗑️ Удалено: {escape_markdown(removed[0])} x{removed[1]}\n\n📋 *Текущий состав {escape_markdown(kit_name)}:*\n{items_display}",
        parse_mode="Markdown",
        reply_markup=show_current_items_keyboard(items)
    )
    await callback.answer()


@router.callback_query(EditKit.waiting_for_item_edit, F.data == "back_to_kit")
async def edit_kit_back_to_kit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kit_name = data.get("edit_kit_name")
    if not kit_name:
        await callback.answer("Ошибка")
        return
    kit_data = sheet.get_kit_details(kit_name)
    if kit_data:
        text = format_kit_info(kit_name, kit_data)
        await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
    await state.clear()
    await callback.answer()


@router.message(EditKit.waiting_for_new_value, F.text != "❌ Отмена")
async def process_edit_kit_param(message: Message, state: FSMContext):
    data = await state.get_data()
    kit_name = data.get("edit_kit_name")
    param = data.get("edit_kit_param")
    if not kit_name or not param:
        await message.answer("Ошибка: данные потеряны.")
        await state.clear()
        return
    new_value = message.text.strip()
    if param == "name":
        if new_value != kit_name and new_value in sheet.get_all_kits():
            await message.answer("❌ Набор с таким именем уже существует.")
            return
        sheet.update_kit_field(kit_name, 'name', new_value)
        await safe_answer(message, f"✅ Название изменено на *{escape_markdown(new_value)}*", parse_mode="Markdown")
        kit_name = new_value
    elif param == "price":
        try:
            price = float(new_value.replace(',', '.'))
        except:
            await message.answer("❌ Введите число.")
            return
        sheet.update_kit_field(kit_name, 'price', price)
        await message.answer(f"✅ Цена обновлена: {price}")
    elif param == "desc":
        if new_value.lower() == "нет":
            new_value = ""
        sheet.update_kit_field(kit_name, 'desc', new_value)
        await message.answer("✅ Описание обновлено.")
    else:
        await message.answer("Неизвестный параметр")
        await state.clear()
        return
    await state.clear()
    kit_data = sheet.get_kit_details(kit_name)
    if kit_data:
        text = format_kit_info(kit_name, kit_data)
        await safe_answer(message, text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
    await message.answer("Продолжайте редактирование или вернитесь в меню.", reply_markup=main_menu)


@router.message(StateFilter(EditKit), F.text == "❌ Отмена")
async def cancel_edit_kit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование набора отменено.", reply_markup=main_menu)


@router.callback_query(F.data.startswith("kit_"))
async def show_kit_details(callback: CallbackQuery):
    kit_name = callback.data[4:]
    kit_data = sheet.get_kit_details(kit_name)
    if not kit_data:
        await callback.answer("Набор не найден", show_alert=True)
        return
    text = format_kit_info(kit_name, kit_data)
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
    await callback.answer()
