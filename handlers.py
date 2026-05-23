from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from keyboards import main_menu, models_inline_keyboard, model_action_keyboard, cancel_keyboard
from states import AddModel
from google_sheets import SheetManager

router = Router()
sheet = SheetManager()

def format_model_info(model_name, details):
    text = f"📦 *{model_name}*\n\n"
    for i, (det_name, on_pallet, per_unit, print_time) in enumerate(details, 1):
        text += f"🔹 *Деталь {i}:* {det_name}\n"
        text += f"   └ На палете: {on_pallet} шт.\n"
        text += f"   └ Нужно на единицу модели: {per_unit} шт.\n"
        if print_time:
            text += f"   └ Время печати: {print_time} мин.\n"
        text += "\n"
    return text

@router.message(Command("start"))
async def cmd_start(message: Message):
    sheet.init_sheet()
    await message.answer(
        "👋 Привет! Я помогу рассчитать необходимое количество палет для 3D-печати.\n\nИспользуй кнопки ниже 👇",
        reply_markup=main_menu
    )

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
            "Введите данные через запятую:\n"
            "`Название, количество на палете, количество на единицу модели, время печати (минут)`\n\n"
            "Пример: `Голова, 16, 1, 120`",
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
    parts = [p.strip() for p in message.text.split(",")]
    if len(parts) != 4:
        await message.answer(
            "❌ Неверный формат. Нужно 4 значения через запятую:\n"
            "`Название, кол-во на палете, кол-во на единицу, время печати (мин)`\nПопробуйте ещё раз:"
        )
        return
    name = parts[0]
    try:
        on_pallet = int(parts[1])
        per_unit = int(parts[2])
        print_time = float(parts[3])
    except ValueError:
        await message.answer("❌ Количество и время должны быть числами. Попробуйте снова:")
        return

    data = await state.get_data()
    details_list = data.get("details_list", [])
    details_list.append((name, on_pallet, per_unit, print_time))
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
    for det_name, on_pallet, per_unit, _ in details:
        if on_pallet <= 0 or per_unit <= 0:
            result_text += f"⚠️ *{det_name}*: не заполнено кол-во на палете или на единицу. Расчёт невозможен.\n\n"
            continue
        total_required = per_unit * quantity
        pallets_needed = (total_required + on_pallet - 1) // on_pallet
        result_text += f"🔸 *{det_name}*:\n   Нужно всего: {total_required} шт.\n   В одном палете: {on_pallet} шт.\n   ➤ Потребуется *{pallets_needed}* палет(а)\n\n"

    await message.answer(result_text, parse_mode="Markdown", reply_markup=main_menu)
    await state.clear()

@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=main_menu)
