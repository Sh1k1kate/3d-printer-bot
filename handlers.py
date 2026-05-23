from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommand, BotCommandScopeDefault
from keyboards import (
    main_menu, models_inline_keyboard, model_action_keyboard,
    parts_inline_keyboard, part_parameters_keyboard, cancel_keyboard,
    calendar_keyboard, my_orders_inline_keyboard, edit_order_keyboard
)
from states import AddModel, EditModel, CreateOrder, EditOrder
from google_sheets import SheetManager
import re
from datetime import datetime

router = Router()
sheet = SheetManager()

# ---------- Функции форматирования ----------
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

# ---------- Установка команд ----------
async def set_commands(bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Показать справку"),
        BotCommand(command="new_order", description="Создать новый заказ"),
        BotCommand(command="my_orders", description="Мои заказы"),
        BotCommand(command="models", description="Список моделей"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

@router.message(Command("start"))
async def cmd_start(message: Message):
    sheet.init_sheet()
    await message.answer(
        "👋 Привет! Я бот для управления 3D-печатью.\n\n"
        "📌 Основные возможности:\n"
        "• Просмотр моделей и деталей\n"
        "• Добавление новых моделей\n"
        "• Расчёт палет, времени и граммовки\n"
        "• Создание заказов\n\n"
        "Используй кнопки меню или команды:\n"
        "/help - подробная справка",
        reply_markup=main_menu
    )
    await set_commands(message.bot)

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 *Справка по командам*\n\n"
        "/start - запустить бота\n"
        "/help - эта справка\n"
        "/models - список моделей\n"
        "/new_order - создать новый заказ\n"
        "/my_orders - просмотреть свои заказы\n\n"
        "📌 *Кнопки меню*\n"
        "• Список моделей – просмотр, расчёт, редактирование\n"
        "• Добавить модель – создание новой модели\n"
        "• Создать заказ – выбор модели и количества\n"
        "• Мои заказы – статус заказов\n"
        "• Помощь – эта справка\n\n"
        "🛠 *В группах* – бот отвечает на команды, упомяните его через @имя_бота"
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(Command("models"))
async def cmd_models(message: Message):
    await list_models(message)

@router.message(Command("new_order"))
async def cmd_new_order(message: Message, state: FSMContext):
    await create_order_start(message, state)

@router.message(Command("my_orders"))
async def cmd_my_orders(message: Message):
    await show_my_orders(message)

# ---------- Обработка текстовых кнопок ----------
@router.message(F.text == "❓ Помощь")
async def help_button(message: Message):
    await cmd_help(message)

@router.message(F.text == "🛒 Создать заказ")
async def create_order_start(message: Message, state: FSMContext):
    models = sheet.get_all_models()
    if not models:
        await message.answer("❌ Нет ни одной модели. Сначала добавьте модель через кнопку ➕.")
        return
    await state.set_state(CreateOrder.waiting_for_model)
    await message.answer(
        "✏️ Введите *название модели*, которую хотите заказать, или выберите из списка ниже:",
        parse_mode="Markdown",
        reply_markup=models_inline_keyboard(models)
    )

@router.message(F.text == "📦 Мои заказы")
async def show_my_orders(message: Message):
    orders = sheet.get_user_orders()
    if not orders:
        await message.answer("📭 У вас пока нет заказов. Создайте новый через кнопку 'Создать заказ'.")
        return
    await message.answer("Выберите заказ для просмотра или редактирования:", reply_markup=my_orders_inline_keyboard(orders))

# ---------- Добавление модели ----------
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
        await message.answer("Введите целое число (количество деталей):")
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
            "`Название кол-во_на_палете кол-во_на_единицу часы_палета минуты_палета грамм_на_палет`\n\n"
            "Пример: `Голова 16 1 8 47 200`",
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
    if len(parts) != 6:
        await message.answer(
            "❌ Неверный формат. Нужно 6 значений через пробел:\n"
            "`Название кол-во_на_палете кол-во_на_единицу часы минуты граммы`\n"
            "Пример: `Голова 16 1 8 47 200`\nПопробуйте ещё раз:"
        )
        return
    name = parts[0]
    try:
        on_pallet = int(parts[1])
        per_unit = int(parts[2])
        hours = int(parts[3])
        minutes = int(parts[4])
        grams = int(parts[5])
        time_pp = hours * 60 + minutes
    except ValueError:
        await message.answer("❌ Все значения должны быть числами. Попробуйте снова:")
        return

    data = await state.get_data()
    details_list = data.get("details_list", [])
    details_list.append((name, on_pallet, per_unit, time_pp, grams))
    await state.update_data(details_list=details_list, current_detail=data["current_detail"] + 1)
    await ask_next_detail(message, state)

# ---------- Список моделей ----------
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

# ---------- Заказ из карточки модели (исправлено) ----------
@router.callback_query(F.data.startswith("order_model_"))
async def order_this_model(callback: CallbackQuery, state: FSMContext):
    model_name = callback.data[len("order_model_"):]
    await state.update_data(order_model=model_name)
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()  # закрываем уведомление
    await callback.message.answer(   # новое сообщение, не редактируем
        f"🛒 Заказ модели *{model_name}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

# ---------- Создание заказа (FSM) ----------
@router.callback_query(CreateOrder.waiting_for_model, F.data.startswith("model_"))
async def process_order_model_from_callback(callback: CallbackQuery, state: FSMContext):
    model_name = callback.data[6:]
    await state.update_data(order_model=model_name)
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
    await callback.message.answer(
        f"🛒 Заказ модели *{model_name}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.message(CreateOrder.waiting_for_model, F.text != "❌ Отмена")
async def process_order_model_text(message: Message, state: FSMContext):
    model_name = message.text.strip()
    models = sheet.get_all_models()
    if model_name not in models:
        await message.answer("❌ Модель не найдена. Введите точное название из списка.")
        return
    await state.update_data(order_model=model_name)
    await state.set_state(CreateOrder.waiting_for_quantity)
    await message.answer(
        f"🛒 Заказ модели *{model_name}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
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
    await state.set_state(CreateOrder.waiting_for_deadline)
    now = datetime.now()
    await message.answer(
        "Выберите срок заказа на календаре:",
        reply_markup=calendar_keyboard(now.year, now.month)
    )

# ---------- Календарь ----------
@router.callback_query(F.data.startswith("cal_prev_"))
async def calendar_prev(callback: CallbackQuery):
    data = callback.data.split("_")
    year = int(data[2])
    month = int(data[3])
    if month == 1:
        month = 12
        year -= 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month))
    await callback.answer()

@router.callback_query(F.data.startswith("cal_next_"))
async def calendar_next(callback: CallbackQuery):
    data = callback.data.split("_")
    year = int(data[2])
    month = int(data[3])
    if month == 12:
        month = 1
        year += 1
    else:
        month += 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month))
    await callback.answer()

@router.callback_query(F.data.startswith("cal_day_"))
async def calendar_day(callback: CallbackQuery, state: FSMContext):
    data = callback.data.split("_")
    year = int(data[2])
    month = int(data[3])
    day = int(data[4])
    selected_date = datetime(year, month, day).strftime("%Y-%m-%d")
    user_data = await state.get_data()
    model_name = user_data.get("order_model")
    quantity = user_data.get("order_quantity")
    if not model_name or not quantity:
        await callback.answer("Ошибка: данные заказа потеряны. Начните заново.", show_alert=True)
        await state.clear()
        return
    try:
        order_num = sheet.add_order(model_name, quantity, selected_date)
        await callback.message.edit_text(
            f"✅ Заказ №{order_num} создан!\n\n"
            f"Модель: {model_name}\n"
            f"Количество: {quantity} шт.\n"
            f"Срок: {selected_date}\n"
            f"Статус: в работе",
            reply_markup=main_menu
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {e}")
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()

# ---------- Редактирование модели (без изменений) ----------
@router.callback_query(F.data.startswith("edit_model_"))
async def edit_model_parts(callback: CallbackQuery):
    model_name = callback.data[len("edit_model_"):]
    details_with_rows = sheet.get_model_details_with_rows(model_name)
    if not details_with_rows:
        await callback.answer("Нет деталей для редактирования", show_alert=True)
        return
    parts_list = [det_name for (_, det_name, _, _, _, _) in details_with_rows]
    await callback.message.edit_text(
        f"✏️ Редактирование модели *{model_name}*\nВыберите деталь:",
        parse_mode="Markdown",
        reply_markup=parts_inline_keyboard(model_name, parts_list)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_part_"))
async def edit_part_parameters(callback: CallbackQuery):
    data = callback.data[len("edit_part_"):]
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
    data = callback.data[len("edit_param_"):]
    last_underscore = data.rfind('_')
    if last_underscore == -1:
        await callback.answer("Ошибка формата")
        return
    param = data[last_underscore+1:]
    rest = data[:last_underscore]
    parts = rest.split('_')
    if len(parts) < 2:
        await callback.answer("Ошибка формата")
        return
    model_name = parts[0]
    det_name = '_'.join(parts[1:])

    part_info = sheet.get_part_row_and_data(model_name, det_name)
    if not part_info:
        await callback.answer("Деталь не найдена", show_alert=True)
        return
    row_idx, on_pallet, per_unit, time_pp, grams_pp = part_info

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
        current_value = format_time(time_pp)
        prompt = "Введите новое *время печати одного палета* в формате `часы минуты`\nПример: `8 47`"
    elif param == "grams":
        current_value = f"{grams_pp} г"
        prompt = "Введите новый *расход граммов на один палет* (целое число):"
    else:
        await callback.answer("Неизвестный параметр")
        return

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

    if None in (row_idx, param, model_name, det_name):
        await message.answer("❌ Ошибка: данные потеряны. Попробуйте ещё раз.", reply_markup=main_menu)
        await state.clear()
        return

    new_text = message.text.strip()

    try:
        if param == "name":
            existing = sheet.get_model_details_with_rows(model_name)
            for (_, dname, _, _, _, _) in existing:
                if dname == new_text:
                    await message.answer("❌ Деталь с таким именем уже существует. Введите другое название.")
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
            hours = int(parts[0])
            minutes = int(parts[1])
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
            await message.answer(f"✅ Расход граммов на палет обновлён: *{new_int}* г", parse_mode="Markdown")
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
    await message.answer(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    await message.answer("Вы можете продолжить редактирование или выбрать другое действие.", reply_markup=main_menu)

@router.message(StateFilter(EditModel.waiting_for_new_value), F.text == "❌ Отмена")
async def cancel_edit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Редактирование отменено.", reply_markup=main_menu)

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
    await message.answer(result_text, parse_mode="Markdown", reply_markup=main_menu)
    await state.clear()

# ---------- Заказы: просмотр, редактирование ----------
@router.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: CallbackQuery):
    order_num = callback.data.split("_")[-1]
    order = sheet.get_order_by_number(order_num)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    num, model, qty, printed, deadline, modified, status = order[:7]
    text = f"📄 *Заказ №{num}*\n"
    text += f"Модель: {model}\n"
    text += f"Заказано: {qty} шт.\n"
    text += f"Напечатано: {printed} шт.\n"
    text += f"Осталось: {int(qty)-int(printed)} шт.\n"
    text += f"Срок: {deadline}\n"
    text += f"Статус: {'✅ Выполнен' if status.lower() == 'да' else '⏳ В работе'}"
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=edit_order_keyboard(num))
    await callback.answer()

@router.callback_query(F.data == "back_to_orders")
async def back_to_orders(callback: CallbackQuery):
    orders = sheet.get_user_orders()
    if orders:
        await callback.message.edit_text("Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await callback.message.edit_text("Заказов нет.")
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
    order = sheet.get_order_by_number(order_num)
    if order:
        num, model, qty, printed, deadline, modified, status = order[:7]
        text = f"📄 *Заказ №{num}*\n"
        text += f"Модель: {model}\n"
        text += f"Заказано: {qty} шт.\n"
        text += f"Напечатано: {printed} шт.\n"
        text += f"Срок: {deadline}\n"
        text += f"Статус: ✅ Выполнен"
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=edit_order_keyboard(num))
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu)
    await callback.answer()

# ---------- Отмена ----------
@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=main_menu)
