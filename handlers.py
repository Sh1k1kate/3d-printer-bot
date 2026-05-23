from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from keyboards import (
    main_menu, models_inline_keyboard, model_action_keyboard,
    parts_inline_keyboard, part_parameters_keyboard, cancel_keyboard
)
from states import AddModel, EditModel
from google_sheets import SheetManager

router = Router()
sheet = SheetManager()

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
    for i, (det_name, on_pallet, per_unit, print_time_min) in enumerate(details, 1):
        text += f"🔹 *Деталь {i}:* {det_name}\n"
        text += f"   └ На палете: {on_pallet} шт.\n"
        text += f"   └ Нужно на единицу модели: {per_unit} шт.\n"
        text += f"   └ Время печати: {format_time(print_time_min)}\n\n"
    return text

@router.message(Command("start"))
async def cmd_start(message: Message):
    sheet.init_sheet()
    await message.answer(
        "👋 Привет! Я помогу рассчитать необходимое количество палет для 3D-печати.\n\n"
        "Используй кнопки ниже 👇",
        reply_markup=main_menu
    )

# ------------------- Добавление модели (без изменений) -------------------
@router.message(F.text == "➕ Добавить модель")
async def add_model_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Введите *название модели*:", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_model_name)

@router.message(AddModel.waiting_for_model_name, F.text != "❌ Отмена")
async def process_model_name(message: Message, state: FSMContext):
    model_name = message.text.strip()
    await state.update_data(model_name=model_name)
    await message.answer("Сколько *деталей* входит в эту модель? (введите число)")
    await state.set_state(AddModel.waiting_for_details_count)

@router.message(AddModel.waiting_for_details_count, F.text != "❌ Отмена")
async def process_details_count(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите целое число (количество деталей):")
        return
    count = int(message.text)
    if count <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    await state.update_data(details_count=count, current_detail=0, details_list=[])
    await state.set_state(AddModel.waiting_for_detail)
    await ask_next_detail(message, state)

async def ask_next_detail(message: Message, state: FSMContext):
    data = await state.get_data()
    current = data["current_detail"]
    total = data["details_count"]
    if current < total:
        await message.answer(
            f"📌 *Деталь {current+1} из {total}*\n\n"
            "Введите данные через *пробел*:\n"
            "`Название количество_на_палете количество_на_единицу часы минуты`\n\n"
            "Пример: `Голова 16 1 8 47`",
            reply_markup=cancel_keyboard
        )
    else:
        model_name = data["model_name"]
        details_list = data["details_list"]
        sheet.add_model(model_name, details_list)
        await message.answer(f"✅ Модель *{model_name}* успешно добавлена!", reply_markup=main_menu)
        await state.clear()

@router.message(AddModel.waiting_for_detail, F.text != "❌ Отмена")
async def process_detail(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 5:
        await message.answer(
            "❌ Неверный формат. Нужно 5 значений через пробел:\n"
            "`Название кол-во_на_палете кол-во_на_единицу часы минуты`\n"
            "Пример: `Голова 16 1 8 47`\nПопробуйте ещё раз:"
        )
        return
    name = parts[0]
    try:
        on_pallet = int(parts[1])
        per_unit = int(parts[2])
        hours = int(parts[3])
        minutes = int(parts[4])
        print_time_min = hours * 60 + minutes
    except ValueError:
        await message.answer("❌ Все значения должны быть числами. Попробуйте снова:")
        return

    data = await state.get_data()
    details_list = data.get("details_list", [])
    details_list.append((name, on_pallet, per_unit, print_time_min))
    await state.update_data(details_list=details_list, current_detail=data["current_detail"] + 1)
    await ask_next_detail(message, state)

# ------------------- Список моделей и просмотр -------------------
@router.message(F.text == "📋 Список моделей")
async def list_models(message: Message):
    models = sheet.get_all_models()
    if not models:
        await message.answer("Пока нет ни одной модели. Добавьте её через кнопку ➕.")
        return
    await message.answer("Выберите модель из списка:", reply_markup=models_inline_keyboard(models))

@router.callback_query(F.data.startswith("model_"))
async def show_model_details(callback: CallbackQuery):
    model_name = callback.data[6:]
    details = sheet.get_model_details(model_name)
    if not details:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    text = format_model_info(model_name, details)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    await callback.answer()

@router.callback_query(F.data == "back_to_models")
async def back_to_models(callback: CallbackQuery):
    models = sheet.get_all_models()
    if models:
        await callback.message.edit_text("Выберите модель из списка:", reply_markup=models_inline_keyboard(models))
    else:
        await callback.message.edit_text("Список моделей пуст.")
    await callback.answer()

# ------------------- Редактирование модели -------------------
@router.callback_query(F.data.startswith("edit_model_"))
async def edit_model_parts(callback: CallbackQuery):
    model_name = callback.data[len("edit_model_"):]
    details_with_rows = sheet.get_model_details_with_rows(model_name)
    if not details_with_rows:
        await callback.answer("Нет деталей для редактирования", show_alert=True)
        return
    # Получаем список названий деталей
    parts_list = [det_name for (_, det_name, _, _, _) in details_with_rows]
    await callback.message.edit_text(
        f"✏️ Редактирование модели *{model_name}*\nВыберите деталь:",
        parse_mode="Markdown",
        reply_markup=parts_inline_keyboard(model_name, parts_list)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_part_"))
async def edit_part_parameters(callback: CallbackQuery):
    # Формат: edit_part_{model_name}_{det_name}
    data = callback.data[len("edit_part_"):]
    # Разделяем по первому подчёркиванию? Название модели может содержать подчёркивания? Допустим нет.
    # Проще: разделить по первому вхождению '_' после префикса. Но модель может содержать '_'.
    # Используем более надёжный способ: ищем последнее вхождение '_'
    last_underscore = data.rfind('_')
    if last_underscore == -1:
        await callback.answer("Ошибка формата")
        return
    model_name = data[:last_underscore]
    det_name = data[last_underscore+1:]
    await callback.message.edit_text(
        f"✏️ Редактирование детали *{det_name}* (модель *{model_name}*)\n\nЧто вы хотите изменить?",
        parse_mode="Markdown",
        reply_markup=part_parameters_keyboard(model_name, det_name)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_param_"))
async def edit_param_start(callback: CallbackQuery, state: FSMContext):
    # Формат: edit_param_{model_name}_{det_name}_{param}
    # Опять разбираем, но параметр всегда последний: name, on_pallet, per_unit, time
    data = callback.data[len("edit_param_"):]
    parts = data.split('_')
    param = parts[-1]
    # Восстанавливаем модель и деталь: всё кроме последнего элемента
    rest = '_'.join(parts[:-1])
    # Последний элемент после последнего подчёркивания? Могут быть подчёркивания в названии детали.
    # Лучше: найти последнее вхождение '_' в data
    last_underscore = data.rfind('_')
    if last_underscore == -1:
        await callback.answer("Ошибка формата")
        return
    param = data[last_underscore+1:]
    rest = data[:last_underscore]  # model_det
    # В rest может быть несколько подчёркиваний, но последний разделяет модель и деталь
    # Найдём разделение модель/деталь: отделяем по первому подчёркиванию? Неправильно.
    # Используем метод: model_name - до первого подчёркивания, остальное - det_name? Тоже плохо.
    # Более просто: пусть названия моделей и деталей не содержат '_'. Тогда можно split('_') и взять первый как модель, второй как деталь.
    # Мы будем считать, что названия не содержат '_'. Это упрощает.
    # Поэтому:
    parts = rest.split('_')
    if len(parts) < 2:
        await callback.answer("Ошибка формата")
        return
    model_name = parts[0]
    det_name = '_'.join(parts[1:])   # на случай если в детали есть '_'
    # Получаем текущее значение параметра для подсказки
    part_info = sheet.get_part_row_and_data(model_name, det_name)
    if not part_info:
        await callback.answer("Деталь не найдена", show_alert=True)
        return
    row_idx, on_pallet, per_unit, print_time = part_info
    current_value = ""
    if param == "name":
        current_value = det_name
        prompt = "Введите новое *название детали*:"
    elif param == "on_pallet":
        current_value = str(on_pallet)
        prompt = "Введите новое *количество на палете* (целое число):"
    elif param == "per_unit":
        current_value = str(per_unit)
        prompt = "Введите новое *количество на единицу модели* (целое число):"
    elif param == "time":
        current_value = format_time(print_time)
        prompt = "Введите новое *время печати* в формате `часы минуты`\nПример: `8 47`"
    else:
        await callback.answer("Неизвестный параметр")
        return

    # Сохраняем в FSM данные для последующего обновления
    await state.update_data(
        edit_row_idx=row_idx,
        edit_param=param,
        edit_model_name=model_name,
        edit_det_name=det_name,
        edit_current_value=current_value
    )
    await callback.message.answer(
        f"{prompt}\n\nТекущее значение: *{current_value}*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditModel.waiting_for_new_value)
    await callback.answer()

@router.message(EditModel.waiting_for_new_value, F.text != "❌ Отмена")
async def edit_param_process(message: Message, state: FSMContext):
    data = await state.get_data()
    row_idx = data.get("edit_row_idx")
    param = data.get("edit_param")
    model_name = data.get("edit_model_name")
    det_name = data.get("edit_det_name")
    new_text = message.text.strip()

    try:
        if param == "name":
            # Проверяем, нет ли уже такой детали в этой модели
            existing = sheet.get_model_details_with_rows(model_name)
            for (_, dname, _, _, _) in existing:
                if dname == new_text:
                    await message.answer("❌ Деталь с таким именем уже существует в этой модели. Введите другое название.")
                    return
            new_value = new_text
            sheet.update_part_field(row_idx, 'name', new_value)
            await message.answer(f"✅ Название детали изменено на *{new_value}*", parse_mode="Markdown")
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
            hours = int(parts[0])
            minutes = int(parts[1])
            if hours < 0 or minutes < 0 or minutes >= 60:
                await message.answer("❌ Часы должны быть >=0, минуты от 0 до 59.")
                return
            new_minutes = hours*60 + minutes
            sheet.update_part_field(row_idx, 'time', new_minutes)
            await message.answer(f"✅ Время печати обновлено: *{format_time(new_minutes)}*", parse_mode="Markdown")
        else:
            await message.answer("Неизвестный параметр")
            await state.clear()
            return
    except ValueError:
        await message.answer("❌ Ошибка: введите корректное числовое значение.")
        return

    # После успешного обновления возвращаемся к модели
    await state.clear()
    # Обновляем сообщение с деталями модели (опционально)
    details = sheet.get_model_details(model_name)
    text = format_model_info(model_name, details)
    # Пытаемся отредактировать последнее сообщение бота (но сейчас у нас новое сообщение)
    # Просто отправим новое сообщение с информацией о модели и кнопками
    await message.answer(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    await message.answer("Вы можете продолжить редактирование или вернуться в меню.", reply_markup=main_menu)

@router.message(StateFilter(EditModel.waiting_for_new_value), F.text == "❌ Отмена")
async def cancel_edit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=main_menu)

# ------------------- Расчёт (без изменений) -------------------
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
    for det_name, on_pallet, per_unit, print_time_min in details:
        if on_pallet <= 0 or per_unit <= 0:
            result_text += f"⚠️ *{det_name}*: не заполнено кол-во на палете или на единицу. Расчёт невозможен.\n\n"
            continue
        total_required = per_unit * quantity
        pallets_needed = (total_required + on_pallet - 1) // on_pallet
        result_text += f"🔸 *{det_name}*:\n"
        result_text += f"   Нужно всего: {total_required} шт.\n"
        result_text += f"   В одном палете: {on_pallet} шт.\n"
        result_text += f"   ➤ Потребуется *{pallets_needed}* палет(а)\n"
        result_text += f"   ⏱ Время печати детали: {format_time(print_time_min)}\n\n"
        if print_time_min > max_print_time:
            max_print_time = print_time_min

    result_text += f"⏳ *Общее время печати модели (параллельная печать всех деталей):* {format_time(max_print_time)}\n"
    await message.answer(result_text, parse_mode="Markdown", reply_markup=main_menu)
    await state.clear()

# ------------------- Отмена -------------------
@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=main_menu)
