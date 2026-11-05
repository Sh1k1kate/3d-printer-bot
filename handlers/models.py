from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from keyboards import (
    main_menu, cancel_keyboard, add_model_action_keyboard, detail_param_keyboard,
    model_action_keyboard, edit_part_keyboard, edit_param_keyboard,
    items_inline_keyboard, resolve_name
)
from states import AddModel, EditModel, CreateOrder
from google_sheets import SheetManager
from .common import format_time, format_model_info, escape_markdown, safe_edit, safe_answer
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

STALE_MSG = "Устарело, откройте список заново"
MAX_NAME_LEN = 100
MAX_INT_VALUE = 1_000_000


def _parse_int(text, min_value=0, max_value=MAX_INT_VALUE):
    """Безопасный разбор целого: только ASCII-цифры, в пределах [min_value, max_value]. None при ошибке."""
    text = (text or "").strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    value = int(text)
    if value < min_value or value > max_value:
        return None
    return value


def _resolve_model(raw):
    try:
        return resolve_name(raw, sheet.get_all_models())
    except Exception as e:
        logger.warning(f"Не удалось получить список моделей: {e}")
        return None


async def _stale(callback: CallbackQuery):
    await callback.answer(STALE_MSG, show_alert=True)


# ---------- Список моделей и наборов (кнопка главного меню) ----------
@router.message(F.text == "📋 Список моделей и наборов")
async def list_items_handler(message: Message):
    await list_items(message)


async def list_items(message: Message):
    models, kits = sheet.get_all_items()
    if not models and not kits:
        await message.answer("Пока ничего нет. Добавьте модель или набор.")
        return
    await message.answer("Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))


# ---------- Добавление модели ----------
@router.message(F.text == "➕ Добавить модель")
async def add_model_start(message: Message, state: FSMContext):
    await state.clear()
    await safe_answer(message, "Введите *название модели*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_model_name)


@router.message(AddModel.waiting_for_model_name, F.text, F.text != "❌ Отмена")
async def process_model_name(message: Message, state: FSMContext):
    model_name = message.text.strip()
    if not model_name or len(model_name) > MAX_NAME_LEN:
        await message.answer(f"❌ Название обязательно (до {MAX_NAME_LEN} символов).")
        return
    if model_name.lower() in {m.lower() for m in sheet.get_all_models()}:
        await message.answer("❌ Модель с таким названием уже существует. Введите другое название:")
        return
    await state.update_data(model_name=model_name, details_list=[])
    await safe_answer(
        message,
        f"Модель *{escape_markdown(model_name)}* создаётся.\n\n"
        "Теперь вы можете добавлять детали. Используйте кнопки:",
        parse_mode="Markdown",
        reply_markup=add_model_action_keyboard()
    )
    await state.set_state(AddModel.choosing_action)


@router.callback_query(AddModel.choosing_action, F.data == "add_detail")
async def add_detail_start(callback: CallbackQuery, state: FSMContext):
    await safe_answer(callback.message, "Введите *название детали*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_detail_name)
    await callback.answer()


@router.message(AddModel.waiting_for_detail_name, F.text, F.text != "❌ Отмена")
async def process_detail_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name or len(name) > MAX_NAME_LEN:
        await message.answer(f"❌ Название детали обязательно (до {MAX_NAME_LEN} символов).")
        return
    data = await state.get_data()
    details_list = data.get("details_list", [])
    if name.lower() in {d[0].lower() for d in details_list}:
        await message.answer("❌ Деталь с таким названием уже есть в этой модели. Введите другое название:")
        return
    details_list.append([name, "", "", "", ""])
    await state.update_data(details_list=details_list, current_index=len(details_list)-1)
    detail_index = len(details_list) - 1
    await safe_answer(
        message,
        f"Деталь *{escape_markdown(name)}* добавлена. Теперь заполните параметры:",
        parse_mode="Markdown",
        reply_markup=detail_param_keyboard(detail_index, data["model_name"])
    )
    await state.set_state(AddModel.choosing_param)


@router.callback_query(AddModel.choosing_param, F.data.startswith("set_"))
async def set_param_start(callback: CallbackQuery, state: FSMContext):
    # формат: set_<param>_<index>, где param может содержать '_' (on_pallet, per_unit)
    body = callback.data[len("set_"):]
    param_type, _, idx_str = body.rpartition("_")
    detail_index = _parse_int(idx_str, 0, 1000)
    if param_type not in ("on_pallet", "per_unit", "time", "grams") or detail_index is None:
        await callback.answer("Ошибка формата", show_alert=True)
        return
    await state.update_data(current_param=param_type, current_index=detail_index)
    prompts = {
        "on_pallet": "Введите *количество на палете* (целое число) или 'нет' для пропуска:",
        "per_unit": "Введите *количество на единицу модели* (целое число) или 'нет':",
        "time": "Введите *время печати* в формате `часы минуты` (например, `8 47`) или 'нет':",
        "grams": "Введите *граммовку на палет* (целое число) или 'нет':"
    }
    await safe_answer(callback.message, prompts[param_type], parse_mode="Markdown", reply_markup=cancel_keyboard)
    if param_type == "on_pallet":
        await state.set_state(AddModel.waiting_for_on_pallet)
    elif param_type == "per_unit":
        await state.set_state(AddModel.waiting_for_per_unit)
    elif param_type == "time":
        await state.set_state(AddModel.waiting_for_time)
    elif param_type == "grams":
        await state.set_state(AddModel.waiting_for_grams)
    await callback.answer()


@router.message(AddModel.waiting_for_on_pallet, F.text, F.text != "❌ Отмена")
async def process_on_pallet(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if (text.isascii() and text.isdigit() and len(text) <= 7) else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет'.")
        return
    await save_param_value(message, state, "on_pallet", value)


@router.message(AddModel.waiting_for_per_unit, F.text, F.text != "❌ Отмена")
async def process_per_unit(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if (text.isascii() and text.isdigit() and len(text) <= 7) else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет'.")
        return
    await save_param_value(message, state, "per_unit", value)


@router.message(AddModel.waiting_for_time, F.text, F.text != "❌ Отмена")
async def process_time(message: Message, state: FSMContext):
    text = message.text.strip()
    value = ""
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Введите два числа: часы и минуты, или 'нет'.")
            return
        try:
            if not all(x.isascii() and x.isdigit() for x in parts):
                raise ValueError
            hours = int(parts[0]); minutes = int(parts[1])
            if hours < 0 or minutes < 0 or minutes >= 60 or hours > 9999:
                raise ValueError
            value = str(hours * 60 + minutes)
        except ValueError:
            await message.answer("❌ Неверный формат. Введите два числа (часы и минуты) или 'нет'.")
            return
    await save_param_value(message, state, "time", value)


@router.message(AddModel.waiting_for_grams, F.text, F.text != "❌ Отмена")
async def process_grams(message: Message, state: FSMContext):
    text = message.text.strip()
    value = "" if text.lower() in ("", "нет", "-", "0") else (text if (text.isascii() and text.isdigit() and len(text) <= 7) else None)
    if value is None and text.lower() not in ("", "нет", "-", "0"):
        await message.answer("❌ Введите целое число или 'нет'.")
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
    await safe_answer(
        message,
        f"Параметр сохранён. Деталь *{escape_markdown(det_name)}* – что дальше?",
        parse_mode="Markdown",
        reply_markup=detail_param_keyboard(index, model_name)
    )
    await state.set_state(AddModel.choosing_param)


@router.callback_query(AddModel.choosing_param, F.data.startswith("save_detail_"))
async def save_detail(callback: CallbackQuery, state: FSMContext):
    index = _parse_int(callback.data.rsplit("_", 1)[-1], 0, 1000)
    data = await state.get_data()
    details_list = data.get("details_list", [])
    if index is None or index >= len(details_list):
        await callback.answer("Ошибка", show_alert=True)
        return
    await safe_answer(callback.message, "Деталь сохранена. Добавьте ещё или завершите.", reply_markup=add_model_action_keyboard())
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
    if not model_name or model_name.lower() in {m.lower() for m in sheet.get_all_models()}:
        await callback.answer("Модель с таким названием уже существует.", show_alert=True)
        await state.clear()
        return
    sheet.add_model(model_name, details_list)
    await safe_answer(
        callback.message,
        f"✅ Модель *{escape_markdown(model_name)}* успешно добавлена с {len(details_list)} деталями!",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()
    await callback.answer()


@router.message(StateFilter(AddModel), F.text == "❌ Отмена")
async def cancel_add_model(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добавление модели отменено.", reply_markup=main_menu)


# ---------- Редактирование модели ----------
@router.callback_query(F.data.startswith("edit_model_"))
async def edit_model_start(callback: CallbackQuery, state: FSMContext):
    model_name = _resolve_model(callback.data[len("edit_model_"):])
    if model_name is None:
        await _stale(callback)
        return
    details_with_rows = sheet.get_model_details_with_rows(model_name)
    if not details_with_rows:
        await callback.answer("Нет деталей для редактирования", show_alert=True)
        return
    parts_list = [det_name for (_, det_name, _, _, _, _) in details_with_rows]
    await safe_edit(
        callback.message,
        f"✏️ Редактирование модели *{escape_markdown(model_name)}*\nВыберите деталь:",
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
    raw_model, raw_part = raw.split('|', 1)
    model_name = _resolve_model(raw_model)
    if model_name is None:
        await _stale(callback)
        return
    parts = [d[1] for d in sheet.get_model_details_with_rows(model_name)]
    det_name = resolve_name(raw_part, parts)
    if det_name is None:
        await _stale(callback)
        return
    await safe_edit(
        callback.message,
        f"Редактирование детали *{escape_markdown(det_name)}* (модель *{escape_markdown(model_name)}*)",
        parse_mode="Markdown",
        reply_markup=edit_param_keyboard(model_name, det_name)
    )
    await state.update_data(edit_model_name=model_name, edit_det_name=det_name)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_param_"))
async def edit_param_selected(callback: CallbackQuery, state: FSMContext):
    raw = callback.data[len("edit_param_"):]
    parts = raw.split('|')
    if len(parts) != 3:
        await callback.answer("Ошибка формата")
        return
    raw_model, raw_part, param = parts
    model_name = _resolve_model(raw_model)
    if model_name is None:
        await _stale(callback)
        return
    part_names = [d[1] for d in sheet.get_model_details_with_rows(model_name)]
    det_name = resolve_name(raw_part, part_names)
    if det_name is None:
        await _stale(callback)
        return
    part_info = sheet.get_part_row_and_data(model_name, det_name)
    if not part_info:
        await _stale(callback)
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
        # row_idx только что прочитан заново и сопоставлен с именем детали
        if sheet.delete_part(model_name, det_name):
            await callback.answer("Деталь удалена!", show_alert=True)
            details = sheet.get_model_details(model_name)
            if details:
                text = format_model_info(model_name, details)
                await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
            else:
                await safe_edit(callback.message, "Деталь удалена. В модели больше нет деталей.")
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
    await safe_answer(
        callback.message,
        f"{prompt}\n\nТекущее значение: *{escape_markdown(current)}*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditModel.waiting_for_new_value)
    await callback.answer()


@router.message(EditModel.waiting_for_new_value, F.text, F.text != "❌ Отмена")
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
    # Перечитываем строку: за время диалога таблица могла измениться (вставка/удаление строк)
    fresh = sheet.get_part_row_and_data(model_name, det_name)
    if not fresh or fresh[0] != row_idx:
        await message.answer("⚠️ Данные изменились. Откройте модель заново через список.", reply_markup=main_menu)
        await state.clear()
        return
    try:
        if param == "name":
            if not new_text or len(new_text) > MAX_NAME_LEN:
                await message.answer(f"❌ Название обязательно (до {MAX_NAME_LEN} символов).")
                return
            existing = sheet.get_model_details_with_rows(model_name)
            for (_, dname, _, _, _, _) in existing:
                if dname.lower() == new_text.lower() and dname != det_name:
                    await message.answer("❌ Деталь с таким именем уже существует.")
                    return
            sheet.update_part_field(row_idx, 'name', new_text)
            await safe_answer(message, f"✅ Название детали изменено на *{escape_markdown(new_text)}*", parse_mode="Markdown")
        elif param == "on_pallet":
            new_int = _parse_int(new_text, 1)
            if new_int is None:
                await message.answer("❌ Введите целое положительное число.")
                return
            sheet.update_part_field(row_idx, 'on_pallet', new_int)
            await message.answer(f"✅ Количество на палете: *{new_int}* шт.", parse_mode="Markdown")
        elif param == "per_unit":
            new_int = _parse_int(new_text, 1)
            if new_int is None:
                await message.answer("❌ Введите целое положительное число.")
                return
            sheet.update_part_field(row_idx, 'per_unit', new_int)
            await message.answer(f"✅ Количество на единицу: *{new_int}* шт.", parse_mode="Markdown")
        elif param == "time":
            parts = new_text.split()
            if len(parts) != 2:
                await message.answer("❌ Введите два числа: часы и минуты.")
                return
            hours = _parse_int(parts[0], 0, 9999); minutes = _parse_int(parts[1], 0, 59)
            if hours is None or minutes is None:
                await message.answer("❌ Часы >=0, минуты 0-59 (целые числа).")
                return
            new_minutes = hours * 60 + minutes
            sheet.update_part_field(row_idx, 'time', new_minutes)
            await message.answer(f"✅ Время печати: *{format_time(new_minutes)}*", parse_mode="Markdown")
        elif param == "grams":
            new_int = _parse_int(new_text, 0)
            if new_int is None:
                await message.answer("❌ Введите целое неотрицательное число.")
                return
            sheet.update_part_field(row_idx, 'grams', new_int)
            await message.answer(f"✅ Граммовка: *{new_int}* г", parse_mode="Markdown")
        else:
            await message.answer("❌ Неизвестный параметр")
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Введите корректное числовое значение.")
        return
    except Exception as e:
        logger.exception("Ошибка редактирования детали")
        await message.answer("❌ Ошибка при сохранении. Попробуйте ещё раз.")
        await state.clear()
        return
    await state.clear()
    details = sheet.get_model_details(model_name)
    text = format_model_info(model_name, details)
    await safe_answer(message, text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    await message.answer("Вы можете продолжить редактирование.", reply_markup=main_menu)


@router.message(StateFilter(EditModel.waiting_for_new_value), F.text == "❌ Отмена")
async def cancel_edit_model(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=main_menu)


# ---------- Просмотр модели ----------
@router.callback_query(F.data.startswith("model_"))
async def show_model_details(callback: CallbackQuery):
    model_name = _resolve_model(callback.data[6:])
    if model_name is None:
        await _stale(callback)
        return
    details = sheet.get_model_details(model_name)
    if not details:
        await _stale(callback)
        return
    text = format_model_info(model_name, details)
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    await callback.answer()


@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery):
    models, kits = sheet.get_all_items()
    if models or kits:
        await safe_edit(callback.message, "Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))
    else:
        await safe_edit(callback.message, "Ничего нет.")
    await callback.answer()


# ---------- Расчёт ----------
@router.callback_query(F.data.startswith("calc_"))
async def start_calculation(callback: CallbackQuery, state: FSMContext):
    model_name = _resolve_model(callback.data[5:])
    if model_name is None:
        await _stale(callback)
        return
    await state.update_data(calc_model=model_name)
    await safe_answer(
        callback.message,
        f"📊 Для модели *{escape_markdown(model_name)}*\nВведите, сколько единиц вам нужно напечатать:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state("waiting_for_quantity")
    await callback.answer()


@router.message(StateFilter("waiting_for_quantity"), F.text, F.text != "❌ Отмена")
async def process_quantity(message: Message, state: FSMContext):
    quantity = _parse_int(message.text, 1, 1_000_000)
    if quantity is None:
        await message.answer("Введите целое положительное число (до 1 000 000):")
        return
    data = await state.get_data()
    model_name = data.get("calc_model")
    if not model_name:
        await message.answer("Ошибка: модель не выбрана.", reply_markup=main_menu)
        await state.clear()
        return
    details = sheet.get_model_details(model_name)
    if not details:
        await message.answer("Ошибка: данные о модели не найдены.")
        await state.clear()
        return
    result_text = f"📐 *Результат для {quantity} шт. модели {escape_markdown(model_name)}:*\n\n"
    max_print_time = 0
    total_grams = 0
    for det_name, on_pallet, per_unit, time_pp, grams_pp in details:
        if on_pallet <= 0 or per_unit <= 0:
            result_text += f"⚠️ *{escape_markdown(det_name)}*: не заполнено кол-во. Расчёт невозможен.\n\n"
            continue
        total_required = per_unit * quantity
        pallets_needed = (total_required + on_pallet - 1) // on_pallet
        part_time = time_pp * pallets_needed
        part_grams = grams_pp * pallets_needed
        total_grams += part_grams
        result_text += f"🔸 *{escape_markdown(det_name)}*:\n"
        result_text += f"   Нужно всего: {total_required} шт.\n"
        result_text += f"   В одном палете: {on_pallet} шт.\n"
        result_text += f"   ➤ Потребуется *{pallets_needed}* палет(а)\n"
        result_text += f"   ⏱ Время: {format_time(part_time)}\n"
        result_text += f"   ⚖️ Граммы: {part_grams} г\n\n"
        if part_time > max_print_time:
            max_print_time = part_time
    result_text += f"⏳ *Общее время печати:* {format_time(max_print_time)}\n"
    result_text += f"⚖️ *Общий расход граммов:* {total_grams} г"
    await safe_answer(message, result_text, parse_mode="Markdown", reply_markup=main_menu)
    await state.clear()


# ---------- ЗАКАЗ ИЗ КАРТОЧКИ МОДЕЛИ (✅ НОВЫЙ ХЕНДЛЕР) ----------
@router.callback_query(F.data.startswith("order_model_"))
async def order_model_from_card(callback: CallbackQuery, state: FSMContext):
    """Кнопка «🛒 Заказать эту модель» в карточке модели."""
    model_name = _resolve_model(callback.data[len("order_model_"):])
    if model_name is None:
        await _stale(callback)
        return
    await state.clear()
    await state.update_data(order_item=model_name, order_type="model")
    await safe_answer(
        callback.message,
        f"🛒 Заказ модели *{escape_markdown(model_name)}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
