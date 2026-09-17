from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from keyboards import (
    main_menu, cancel_keyboard, add_model_action_keyboard, detail_param_keyboard,
    model_action_keyboard, edit_part_keyboard, edit_param_keyboard, parts_inline_keyboard,
    items_inline_keyboard
)
from states import AddModel, EditModel
from google_sheets import SheetManager
from .common import format_time, format_model_info, parse_callback_data
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

# ---------- Добавление модели ----------
@router.message(F.text == "➕ Добавить модель")
async def add_model_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Введите *название модели*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_model_name)

@router.message(AddModel.waiting_for_model_name, F.text != "❌ Отмена")
async def process_model_name(message: Message, state: FSMContext):
    model_name = message.text.strip()
    await state.update_data(model_name=model_name, details_list=[])
    await message.answer(
        f"Модель *{model_name}* создаётся.\n\nТеперь вы можете добавлять детали. Используйте кнопки:",
        parse_mode="Markdown",
        reply_markup=add_model_action_keyboard()
    )
    await state.set_state(AddModel.choosing_action)

@router.callback_query(AddModel.choosing_action, F.data == "add_detail")
async def add_detail_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите *название детали*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_detail_name)
    await callback.answer()

@router.message(AddModel.waiting_for_detail_name, F.text != "❌ Отмена")
async def process_detail_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название детали обязательно.")
        return
    data = await state.get_data()
    details_list = data.get("details_list", [])
    details_list.append([name, "", "", "", ""])
    await state.update_data(details_list=details_list, current_index=len(details_list)-1)
    detail_index = len(details_list) - 1
    await message.answer(
        f"Деталь *{name}* добавлена. Теперь заполните параметры (или пропустите):",
        parse_mode="Markdown",
        reply_markup=detail_param_keyboard(detail_index, data["model_name"])
    )
    await state.set_state(AddModel.choosing_param)

@router.callback_query(AddModel.choosing_param, F.data.startswith("set_"))
async def set_param_start(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    param_type = data[1]
    detail_index = int(data[2])
    await state.update_data(current_param=param_type, current_index=detail_index)
    prompts = {
        "on_pallet": "Введите *количество на палете* (целое число) или пропустите (введите 'нет'):",
        "per_unit": "Введите *количество на единицу модели* (целое число) или пропустите:",
        "time": "Введите *время печати* в формате `часы минуты` (например, `8 47`) или пропустите:",
        "grams": "Введите *граммовку на палет* (целое число) или пропустите:"
    }
    await callback.message.answer(prompts[param_type], parse_mode="Markdown", reply_markup=cancel_keyboard)
    if param_type == "on_pallet":
        await state.set_state(AddModel.waiting_for_on_pallet)
    elif param_type == "per_unit":
        await state.set_state(AddModel.waiting_for_per_unit)
    elif param_type == "time":
        await state.set_state(AddModel.waiting_for_time)
    elif param_type == "grams":
        await state.set_state(AddModel.waiting_for_grams)
    await callback.answer()

@router.message(AddModel.waiting_for_on_pallet, F.text != "❌ Отмена")
async def process_on_pallet(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if text.isdigit() else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет' для пропуска.")
        return
    await save_param_value(message, state, "on_pallet", value)

@router.message(AddModel.waiting_for_per_unit, F.text != "❌ Отмена")
async def process_per_unit(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if text.isdigit() else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет' для пропуска.")
        return
    await save_param_value(message, state, "per_unit", value)

@router.message(AddModel.waiting_for_time, F.text != "❌ Отмена")
async def process_time(message: Message, state: FSMContext):
    text = message.text.strip()
    value = ""
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Введите два числа: часы и минуты (например, `8 47`) или 'нет' для пропуска.")
            return
        try:
            hours = int(parts[0]); minutes = int(parts[1])
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError
            value = str(hours * 60 + minutes)
        except:
            await message.answer("❌ Неверный формат. Введите два числа (часы и минуты) или 'нет'.")
            return
    await save_param_value(message, state, "time", value)

@router.message(AddModel.waiting_for_grams, F.text != "❌ Отмена")
async def process_grams(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if text.isdigit() else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет' для пропуска.")
        return
    await save_param_value(message, state, "grams", value)

async def save_param_value(message: Message, state: FSMContext, param_type: str, value):
    data = await state.get_data()
    details_list = data.get("details_list", [])
    index = data.get("current_index")
    if index is None or index >= len(details_list):
        await message.answer("Ошибка: деталь не найдена.")
        await state.clear()
        return
    if param_type == "on_pallet":
        details_list[index][1] = value
    elif param_type == "per_unit":
        details_list[index][2] = value
    elif param_type == "time":
        details_list[index][3] = value
    elif param_type == "grams":
        details_list[index][4] = value
    await state.update_data(details_list=details_list)
    model_name = data.get("model_name")
    det_name = details_list[index][0]
    await message.answer(
        f"Параметр сохранён. Деталь *{det_name}* – что дальше?",
        parse_mode="Markdown",
        reply_markup=detail_param_keyboard(index, model_name)
    )
    await state.set_state(AddModel.choosing_param)

@router.callback_query(AddModel.choosing_param, F.data.startswith("save_detail_"))
async def save_detail(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[-1])
    data = await state.get_data()
    details_list = data.get("details_list", [])
    if index >= len(details_list):
        await callback.answer("Ошибка", show_alert=True)
        return
    await callback.message.answer(
        "Деталь сохранена. Вы можете добавить ещё одну или завершить.",
        reply_markup=add_model_action_keyboard()
    )
    await state.set_state(AddModel.choosing_action)
    await callback.answer()

@router.callback_query(AddModel.choosing_action, F.data == "finish_model")
async def finish_model(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    model_name = data.get("model_name")
    details_list = data.get("details_list", [])
    if not details_list:
        await callback.answer("Нельзя создать модель без деталей.", show_alert=True)
        return
    sheet.add_model(model_name, details_list)
    await callback.message.answer(f"✅ Модель *{model_name}* успешно добавлена с {len(details_list)} деталями!", reply_markup=main_menu)
    await state.clear()
    await callback.answer()

@router.message(StateFilter(AddModel), F.text == "❌ Отмена")
async def cancel_add_model(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добавление модели отменено.", reply_markup=main_menu)

# ---------- Редактирование модели ----------
@router.callback_query(F.data.startswith("edit_model_"))
async def edit_model_start(callback: CallbackQuery, state: FSMContext):
    model_name = callback.data[len("edit_model_"):]
    details_with_rows = sheet.get_model_details_with_rows(model_name)
    if not details_with_rows:
        await callback.answer("Нет деталей для редактирования", show_alert=True)
        return
    parts_list = [det_name for (_, det_name, _, _, _, _) in details_with_rows]
    await callback.message.edit_text(
        f"✏️ Редактирование модели *{model_name}*\nВыберите деталь для изменения:",
        parse_mode="Markdown",
        reply_markup=edit_part_keyboard(parts_list, model_name)
    )
    await state.update_data(edit_model_name=model_name, edit_parts=parts_list, edit_rows=details_with_rows)
    await callback.answer()

@router.callback_query(F.data.startswith("edit_part_"))
async def edit_part_selected(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[len("edit_part_"):]
    if '|' not in raw:
        await callback.answer("Ошибка формата")
        return
    model_name, part_index_str = raw.split('|', 1)
    try:
        part_index = int(part_index_str)
    except ValueError:
        await callback.answer("Ошибка формата")
        return
    data_state = await state.get_data()
    rows = data_state.get("edit_rows", [])
    if part_index >= len(rows):
        await callback.answer("Ошибка", show_alert=True)
        return
    det_name = rows[part_index][1]
    await callback.message.edit_text(
        f"Редактирование детали *{det_name}* (модель *{model_name}*)",
        reply_markup=edit_param_keyboard(model_name, det_name)
    )
    await state.update_data(edit_det_name=det_name, edit_det_index=part_index)
    await callback.answer()

@router.callback_query(F.data.startswith("edit_param_"))
async def edit_param_selected(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[len("edit_param_"):]
    if '|' not in raw:
        await callback.answer("Ошибка формата")
        return
    parts = raw.split('|')
    if len(parts) != 3:
        await callback.answer("Ошибка формата")
        return
    model_name, det_name, param = parts
    part_info = sheet.get_part_row_and_data(model_name, det_name)
    if not part_info:
        await callback.answer("Деталь не найдена", show_alert=True)
        return
    row_idx, on_pallet, per_unit, time_pp, grams_pp = part_info
    prompt = ""
    current = ""
    if param == "name":
        current = det_name
        prompt = "Введите новое *название детали*:"
    elif param == "on_pallet":
        current = str(on_pallet)
        prompt = "Введите новое *количество на палете* (целое число):"
    elif param == "per_unit":
        current = str(per_unit)
        prompt = "Введите новое *количество на единицу модели* (целое число):"
    elif param == "time":
        current = format_time(time_pp)
        prompt = "Введите новое *время печати* в формате `часы минуты` (например, `8 47`):"
    elif param == "grams":
        current = f"{grams_pp} г"
        prompt = "Введите новую *граммовку* (целое число):"
    elif param == "delete":
        if sheet.delete_part(model_name, det_name):
            await callback.answer("Деталь удалена!", show_alert=True)
            details = sheet.get_model_details(model_name)
            text = format_model_info(model_name, details)
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
        else:
            await callback.answer("Ошибка удаления", show_alert=True)
        return
    else:
        await callback.answer("Неизвестный параметр")
        return
    await state.update_data(
        edit_row_idx=row_idx,
        edit_param=param,
        edit_model_name=model_name,
        edit_det_name=det_name,
        edit_current_value=current
    )
    await callback.message.answer(
        f"{prompt}\n\nТекущее значение: *{current}*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditModel.waiting_for_new_value)
    await callback.answer()

@router.message(EditModel.waiting_for_new_value, F.text != "❌ Отмена")
async def process_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    row_idx = data.get("edit_row_idx")
    param = data.get("edit_param")
    model_name = data.get("edit_model_name")
    det_name = data.get("edit_det_name")
    if None in (row_idx, param, model_name, det_name):
        await message.answer("❌ Ошибка: данные потеряны.", reply_markup=main_menu)
        await state.clear()
        return
    new_text = message.text.strip()
    try:
        if param == "name":
            existing = sheet.get_model_details_with_rows(model_name)
            for (_, dname, _, _, _, _) in existing:
                if dname == new_text:
                    await message.answer("❌ Деталь с таким именем уже существует. Введите другое.")
                    return
            sheet.update_part_field(row_idx, 'name', new_text)
            await message.answer(f"✅ Название детали изменено на *{new_text}*", parse_mode="Markdown")
        elif param == "on_pallet":
            new_int = int(new_text)
            if new_int <= 0:
                await message.answer("❌ Количество на палете должно быть положительным числом.")
                return
            sheet.update_part_field(row_idx, 'on_pallet', new_int)
            await message.answer(f"✅ Количество на палете обновлено: *{new_int}* шт.", parse_mode="Markdown")
        elif param == "per_unit":
            new_int = int(new_text)
            if new_int <= 0:
                await message.answer("❌ Количество на единицу должно быть положительным числом.")
                return
            sheet.update_part_field(row_idx, 'per_unit', new_int)
            await message.answer(f"✅ Количество на единицу модели обновлено: *{new_int}* шт.", parse_mode="Markdown")
        elif param == "time":
            parts = new_text.split()
            if len(parts) != 2:
                await message.answer("❌ Введите два числа: часы и минуты. Пример: `8 47`")
                return
            hours = int(parts[0]); minutes = int(parts[1])
            if hours < 0 or minutes < 0 or minutes >= 60:
                await message.answer("❌ Часы >=0, минуты 0-59.")
                return
            new_minutes = hours * 60 + minutes
            sheet.update_part_field(row_idx, 'time', new_minutes)
            await message.answer(f"✅ Время печати палета обновлено: *{format_time(new_minutes)}*", parse_mode="Markdown")
        elif param == "grams":
            new_int = int(new_text)
            if new_int < 0:
                await message.answer("❌ Граммовка не может быть отрицательной.")
                return
            sheet.update_part_field(row_idx, 'grams', new_int)
            await message.answer(f"✅ Граммовка обновлена: *{new_int}* г", parse_mode="Markdown")
        else:
            await message.answer("❌ Неизвестный параметр")
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Ошибка: введите корректное числовое значение.")
        return
    except Exception as e:
        await message.answer(f"❌ Ошибка при обновлении: {e}")
        await state.clear()
        return
    await state.clear()
    details = sheet.get_model_details(model_name)
    text = format_model_info(model_name, details)
    try:
        await message.answer(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    except:
        await message.answer(text, reply_markup=model_action_keyboard(model_name))
    await message.answer("Вы можете продолжить редактирование или выбрать другое действие.", reply_markup=main_menu)

@router.message(StateFilter(EditModel.waiting_for_new_value), F.text == "❌ Отмена")
async def cancel_edit_model(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=main_menu)

# ---------- Просмотр модели ----------
@router.callback_query(F.data.startswith("model_"))
async def show_model_details(callback: CallbackQuery):
    model_name = callback.data[6:]
    details = sheet.get_model_details(model_name)
    if not details:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    text = format_model_info(model_name, details)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    except:
        await callback.message.edit_text(text, reply_markup=model_action_keyboard(model_name))
    await callback.answer()

@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery):
    models, kits = sheet.get_all_items()
    if models or kits:
        await callback.message.edit_text("Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))
    else:
        await callback.message.edit_text("Ничего нет.")
    await callback.answer()

# ---------- Расчёт ----------
@router.callback_query(F.data.startswith("calc_"))
async def start_calculation(callback: CallbackQuery, state: FSMContext):
    model_name = callback.data[5:]
    await state.update_data(calc_model=model_name)
    await callback.message.answer(
        f"📊 Для модели *{model_name}*\nВведите, сколько единиц вам нужно напечатать:",
        reply_markup=cancel_keyboard
    )
    await state.set_state("waiting_for_quantity")
    await callback.answer()

@router.message(StateFilter("waiting_for_quantity"), F.text != "❌ Отмена")
async def process_quantity(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите целое положительное число (количество моделей):")
        return
    quantity = int(message.text)
    if quantity <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    data = await state.get_data()
    model_name = data["calc_model"]
    details = sheet.get_model_details(model_name)
    if not details:
        await message.answer("Ошибка: данные о модели не найдены.")
        await state.clear()
        return
    result_text = f"📐 *Результат для {quantity} шт. модели {model_name}:*\n\n"
    max_print_time = 0
    total_grams = 0
    for det_name, on_pallet, per_unit, time_pp, grams_pp in details:
        if on_pallet <= 0 or per_unit <= 0:
            result_text += f"⚠️ *{det_name}*: не заполнено кол-во на палете или на единицу. Расчёт невозможен.\n\n"
            continue
        total_required = per_unit * quantity
        pallets_needed = (total_required + on_pallet - 1) // on_pallet
        part_time = time_pp * pallets_needed
        part_grams = grams_pp * pallets_needed
        total_grams += part_grams
        result_text += f"🔸 *{det_name}*:\n"
        result_text += f"   Нужно всего: {total_required} шт.\n"
        result_text += f"   В одном палете: {on_pallet} шт.\n"
        result_text += f"   ➤ Потребуется *{pallets_needed}* палет(а)\n"
        result_text += f"   ⏱ Время печати детали: {format_time(part_time)}\n"
        result_text += f"   ⚖️ Расход граммов: {part_grams} г\n\n"
        if part_time > max_print_time:
            max_print_time = part_time
    result_text += f"⏳ *Общее время печати модели (параллельная печать всех деталей):* {format_time(max_print_time)}\n"
    result_text += f"⚖️ *Общий расход граммов:* {total_grams} г"
    try:
        await message.answer(result_text, parse_mode="Markdown", reply_markup=main_menu)
    except:
        await message.answer(result_text, reply_markup=main_menu)
    await state.clear()
