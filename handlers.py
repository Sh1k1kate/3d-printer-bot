from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, BotCommand, BotCommandScopeDefault
from keyboards import (
    main_menu, items_inline_keyboard, model_action_keyboard,
    parts_inline_keyboard, part_parameters_keyboard, cancel_keyboard,
    calendar_keyboard, my_orders_inline_keyboard, edit_order_keyboard,
    kit_action_keyboard, kit_parameters_keyboard,
    select_model_keyboard, show_current_items_keyboard,
    tasks_list_keyboard, task_actions_keyboard, assignee_keyboard
)
from states import AddModel, EditModel, CreateOrder, EditOrder, AddKit, EditKit, CreateTask
from google_sheets import SheetManager
from config import ALLOWED_USERS
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = Router()
sheet = SheetManager()

# ---------- Форматирование ----------
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

def format_kit_info(kit_name, kit_data):
    name, items_text, price, desc = kit_data
    text = f"🎁 *Набор: {name}*\n\n"
    text += f"📋 *Состав:* {items_text}\n"
    if price:
        text += f"💰 *Цена:* {price} руб.\n"
    if desc:
        text += f"📄 *Описание:* {desc}\n"
    return text

# ---------- Функция проверки доступа ----------
def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

# ---------- Middleware для проверки доступа ----------
@router.message()
async def check_access_message(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await message.answer("⛔ Доступ запрещён. Вы не авторизованы для использования этого бота.")
        return
    await router.propagate_event("message", message, state=state)

@router.callback_query()
async def check_access_callback(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await router.propagate_event("callback_query", callback, state=state)

# ---------- Команды ----------
async def set_commands(bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Показать справку"),
        BotCommand(command="new_order", description="Создать новый заказ"),
        BotCommand(command="my_orders", description="Мои заказы"),
        BotCommand(command="items", description="Список моделей и наборов"),
        BotCommand(command="tasks", description="Список задач"),
        BotCommand(command="new_task", description="Создать новую задачу"),
        BotCommand(command="id", description="Ваш Telegram ID"),
        BotCommand(command="subscribe", description="Подписаться на общие уведомления"),
        BotCommand(command="unsubscribe", description="Отписаться от общих уведомлений"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())

@router.message(Command("start"))
async def cmd_start(message: Message):
    if not is_allowed(message.from_user.id):
        return
    sheet.init_sheet()
    user_id = message.from_user.id
    name = message.from_user.full_name or str(user_id)
    if sheet.add_subscriber(user_id, name):
        logger.info(f"Пользователь {user_id} ({name}) автоматически подписан")
    await message.answer(
        "👋 Привет! Я бот для управления 3D-печатью и задачами.\n\n"
        "📌 Основные возможности:\n"
        "• Просмотр моделей и наборов\n"
        "• Добавление новых моделей и наборов\n"
        "• Расчёт палет, времени и граммовки\n"
        "• Создание заказов (модель или набор)\n"
        "• Управление задачами (создание, назначение, уведомления)\n\n"
        "✅ Вы автоматически подписаны на общие уведомления о задачах.\n"
        "Используй команды:\n"
        "/help - подробная справка",
        reply_markup=main_menu
    )
    await set_commands(message.bot)

@router.message(Command("help"))
async def cmd_help(message: Message):
    if not is_allowed(message.from_user.id):
        return
    help_text = (
        "📖 *Справка по командам*\n\n"
        "/start - запустить бота\n"
        "/help - эта справка\n"
        "/items - список моделей и наборов\n"
        "/new_order - создать новый заказ\n"
        "/my_orders - просмотреть свои заказы\n"
        "/tasks - список задач\n"
        "/new_task - создать новую задачу\n"
        "/id - ваш Telegram ID (для назначения задач)\n"
        "/subscribe - подписаться на общие уведомления\n"
        "/unsubscribe - отписаться от общих уведомлений\n\n"
        "📌 *Кнопки меню*\n"
        "• Список моделей и наборов – просмотр, расчёт, редактирование\n"
        "• Добавить модель – создание новой модели\n"
        "• Добавить набор – создание нового набора\n"
        "• Создать заказ – выбор модели или набора и количества\n"
        "• Задачи – просмотр активных задач\n"
        "• Мои заказы – статус заказов\n"
        "• Помощь – эта справка\n\n"
        "🛠 *В группах* – бот отвечает на команды, упомяните его через @имя_бота"
    )
    await message.answer(help_text, parse_mode="Markdown")

@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    if not is_allowed(message.from_user.id):
        return
    user_id = message.from_user.id
    name = message.from_user.full_name or str(user_id)
    if sheet.add_subscriber(user_id, name):
        await message.answer("✅ Вы подписались на общие уведомления о задачах.")
    else:
        await message.answer("ℹ️ Вы уже подписаны на уведомления.")

@router.message(Command("unsubscribe"))
async def cmd_unsubscribe(message: Message):
    if not is_allowed(message.from_user.id):
        return
    user_id = message.from_user.id
    if sheet.remove_subscriber(user_id):
        await message.answer("✅ Вы отписались от общих уведомлений.")
    else:
        await message.answer("ℹ️ Вы не были подписаны на уведомления.")

@router.message(Command("items"))
async def cmd_items(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await list_items(message)

@router.message(Command("new_order"))
async def cmd_new_order(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await create_order_start(message, state)

@router.message(Command("my_orders"))
async def cmd_my_orders(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await show_my_orders(message)

@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await list_tasks(message)

@router.message(Command("new_task"))
async def cmd_new_task(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await create_task_start(message, state)

@router.message(Command("id"))
async def cmd_id(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await message.answer(f"Ваш Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")

# ---------- Кнопки ----------
@router.message(F.text == "❓ Помощь")
async def help_button(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await cmd_help(message)

@router.message(F.text == "🛒 Создать заказ")
async def create_order_start(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    models, kits = sheet.get_all_items()
    if not models and not kits:
        await message.answer("❌ Нет ни одной модели или набора. Сначала добавьте их.")
        return
    await state.set_state(CreateOrder.waiting_for_model)
    await message.answer(
        "✏️ Выберите модель или набор для заказа:",
        parse_mode="Markdown",
        reply_markup=items_inline_keyboard(models, kits)
    )

@router.message(F.text == "📋 Список моделей и наборов")
async def list_items(message: Message):
    if not is_allowed(message.from_user.id):
        return
    models, kits = sheet.get_all_items()
    if not models and not kits:
        await message.answer("Пока ничего нет. Добавьте модель или набор.")
        return
    await message.answer("Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))

@router.message(F.text == "📋 Задачи")
async def tasks_menu(message: Message):
    if not is_allowed(message.from_user.id):
        return
    await list_tasks(message)

# ---------- Добавление модели (с опциональными параметрами) ----------
@router.message(F.text == "➕ Добавить модель")
async def add_model_start(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Введите *название модели*:", reply_markup=cancel_keyboard)
    await state.set_state(AddModel.waiting_for_model_name)

@router.message(AddModel.waiting_for_model_name, F.text != "❌ Отмена")
async def process_model_name(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    model_name = message.text.strip()
    await state.update_data(model_name=model_name)
    await message.answer("Сколько *деталей* входит в эту модель? (введите число)")
    await state.set_state(AddModel.waiting_for_details_count)

@router.message(AddModel.waiting_for_details_count, F.text != "❌ Отмена")
async def process_details_count(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("Введите целое число (количество деталей):")
        return
    count = int(message.text)
    if count <= 0:
        await message.answer("Количество должно быть больше 0.")
        return
    await state.update_data(details_count=count, current_detail=0, details_list=[])
    await ask_detail_name(message, state)

async def ask_detail_name(message: Message, state: FSMContext):
    data = await state.get_data()
    current = data["current_detail"]
    total = data["details_count"]
    if current < total:
        await message.answer(
            f"📌 *Деталь {current+1} из {total}*\nВведите *название детали* (обязательно):",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(AddModel.waiting_for_detail_name)
    else:
        model_name = data["model_name"]
        details_list = data["details_list"]
        sheet.add_model(model_name, details_list)
        await message.answer(f"✅ Модель *{model_name}* успешно добавлена!", reply_markup=main_menu)
        await state.clear()

@router.message(AddModel.waiting_for_detail_name, F.text != "❌ Отмена")
async def process_detail_name(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название детали обязательно. Введите название:")
        return
    data = await state.get_data()
    details_list = data.get("details_list", [])
    details_list.append((name, "", "", "", ""))
    await state.update_data(details_list=details_list, current_detail=data["current_detail"] + 1)
    await ask_on_pallet(message, state)

async def ask_on_pallet(message: Message, state: FSMContext):
    await message.answer(
        "Введите *количество на палете* (целое число) или нажмите Enter / введите `нет`, чтобы пропустить:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddModel.waiting_for_on_pallet)

@router.message(AddModel.waiting_for_on_pallet, F.text != "❌ Отмена")
async def process_on_pallet(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    text = message.text.strip()
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        if not text.isdigit():
            await message.answer("❌ Введите целое число или пропустите (Enter / 'нет').")
            return
        value = text
    data = await state.get_data()
    details_list = data["details_list"]
    if details_list:
        last = list(details_list[-1])
        last[1] = value
        details_list[-1] = tuple(last)
        await state.update_data(details_list=details_list)
    await ask_per_unit(message, state)

async def ask_per_unit(message: Message, state: FSMContext):
    await message.answer(
        "Введите *количество на единицу модели* (целое число) или пропустите:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddModel.waiting_for_per_unit)

@router.message(AddModel.waiting_for_per_unit, F.text != "❌ Отмена")
async def process_per_unit(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    text = message.text.strip()
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        if not text.isdigit():
            await message.answer("❌ Введите целое число или пропустите.")
            return
        value = text
    data = await state.get_data()
    details_list = data["details_list"]
    if details_list:
        last = list(details_list[-1])
        last[2] = value
        details_list[-1] = tuple(last)
        await state.update_data(details_list=details_list)
    await ask_time(message, state)

async def ask_time(message: Message, state: FSMContext):
    await message.answer(
        "Введите *время печати* в формате `часы минуты` (например, `8 47`) или пропустите:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddModel.waiting_for_time)

@router.message(AddModel.waiting_for_time, F.text != "❌ Отмена")
async def process_time(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    text = message.text.strip()
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        parts = text.split()
        if len(parts) != 2:
            await message.answer("❌ Введите два числа: часы и минуты (например, `8 47`) или пропустите.")
            return
        try:
            hours = int(parts[0])
            minutes = int(parts[1])
            if hours < 0 or minutes < 0 or minutes >= 60:
                raise ValueError
            value = str(hours * 60 + minutes)
        except:
            await message.answer("❌ Неверный формат. Введите два числа (часы и минуты) или пропустите.")
            return
    data = await state.get_data()
    details_list = data["details_list"]
    if details_list:
        last = list(details_list[-1])
        last[3] = value
        details_list[-1] = tuple(last)
        await state.update_data(details_list=details_list)
    await ask_grams(message, state)

async def ask_grams(message: Message, state: FSMContext):
    await message.answer(
        "Введите *граммовку на палет* (целое число) или пропустите:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddModel.waiting_for_grams)

@router.message(AddModel.waiting_for_grams, F.text != "❌ Отмена")
async def process_grams(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    text = message.text.strip()
    if text.lower() in ("", "нет", "-", "0"):
        value = ""
    else:
        if not text.isdigit():
            await message.answer("❌ Введите целое число или пропустите.")
            return
        value = text
    data = await state.get_data()
    details_list = data["details_list"]
    if details_list:
        last = list(details_list[-1])
        last[4] = value
        details_list[-1] = tuple(last)
        await state.update_data(details_list=details_list)
    await ask_detail_name(message, state)

# ---------- Просмотр модели или набора ----------
@router.callback_query(F.data.startswith("model_"))
async def show_model_details(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
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

@router.callback_query(F.data.startswith("kit_"))
async def show_kit_details(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    kit_name = callback.data[4:]
    kit_data = sheet.get_kit_details(kit_name)
    if not kit_data:
        await callback.answer("Набор не найден", show_alert=True)
        return
    text = format_kit_info(kit_name, kit_data)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
    except:
        await callback.message.edit_text(text, reply_markup=kit_action_keyboard(kit_name))
    await callback.answer()

@router.callback_query(F.data == "back_to_items")
async def back_to_items(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    models, kits = sheet.get_all_items()
    if models or kits:
        await callback.message.edit_text("Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))
    else:
        await callback.message.edit_text("Ничего нет.")
    await callback.answer()

# ---------- Добавление набора ----------
@router.message(F.text == "➕ Добавить набор")
async def add_kit_start(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    models = sheet.get_all_models()
    if not models:
        await message.answer("❌ Сначала добавьте хотя бы одну модель через кнопку '➕ Добавить модель'.")
        return
    await message.answer("Введите *название набора*:", reply_markup=cancel_keyboard)
    await state.set_state(AddKit.waiting_for_kit_name)

@router.message(AddKit.waiting_for_kit_name, F.text != "❌ Отмена")
async def process_kit_name(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    kit_name = message.text.strip()
    existing = sheet.get_all_kits()
    if kit_name in existing:
        await message.answer("❌ Набор с таким названием уже существует. Введите другое.")
        return
    await state.update_data(kit_name=kit_name, kit_items=[])
    models = sheet.get_all_models()
    await message.answer(
        f"Набор *{kit_name}*\n\nТеперь добавляйте модели в набор. Выберите модель из списка:",
        parse_mode="Markdown",
        reply_markup=select_model_keyboard(models, prefix="add_kit_model")
    )
    await state.set_state(AddKit.waiting_for_item)

@router.callback_query(AddKit.waiting_for_item, F.data.startswith("add_kit_model_"))
async def add_kit_select_model(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data[15:]
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
    await callback.message.answer(
        f"Модель *{model_name}*\nВведите количество (целое число) для этого набора:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(AddKit.waiting_for_quantity_for_item)
    await callback.answer()

@router.message(AddKit.waiting_for_quantity_for_item, F.text != "❌ Отмена")
async def add_kit_process_quantity(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
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
    await message.answer(f"✅ Добавлено: {model_name} x{qty}. Выберите следующую модель или нажмите 'Готово'.")
    models = sheet.get_all_models()
    await message.answer("Выберите модель для добавления:", reply_markup=select_model_keyboard(models, prefix="add_kit_model"))
    await state.set_state(AddKit.waiting_for_item)

@router.callback_query(AddKit.waiting_for_item, F.data == "add_kit_done")
async def add_kit_done(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    data = await state.get_data()
    items = data.get("kit_items", [])
    if not items:
        await callback.answer("Вы не добавили ни одной модели.", show_alert=True)
        return
    items_text = ", ".join([f"{model} x{count}" for model, count in items])
    await state.update_data(kit_items_text=items_text)
    await callback.message.answer("Введите *цену набора* (число, можно 0):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddKit.waiting_for_price)
    await callback.answer()

@router.message(AddKit.waiting_for_price, F.text != "❌ Отмена")
async def process_kit_price(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    try:
        price = float(message.text.replace(',', '.'))
    except:
        await message.answer("❌ Введите число (цену).")
        return
    await state.update_data(kit_price=price)
    await message.answer("Введите *описание набора* (или 'нет', чтобы пропустить):", parse_mode="Markdown")
    await state.set_state(AddKit.waiting_for_description)

@router.message(AddKit.waiting_for_description, F.text != "❌ Отмена")
async def process_kit_description(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    desc = message.text.strip()
    if desc.lower() == "нет":
        desc = ""
    data = await state.get_data()
    kit_name = data["kit_name"]
    items_text = data["kit_items_text"]
    price = data["kit_price"]
    sheet.add_kit(kit_name, items_text, price, desc)
    await message.answer(f"✅ Набор *{kit_name}* успешно добавлен!", reply_markup=main_menu)
    await state.clear()

@router.message(StateFilter(AddKit), F.text == "❌ Отмена")
async def cancel_add_kit(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Добавление набора отменено.", reply_markup=main_menu)

# ---------- Редактирование модели ----------
@router.callback_query(F.data.startswith("edit_model_"))
async def edit_model_parts(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    model_name = callback.data[11:]
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
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data[10:]
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
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data[11:]
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
    if not is_allowed(message.from_user.id):
        return
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
    try:
        await message.answer(text, parse_mode="Markdown", reply_markup=model_action_keyboard(model_name))
    except:
        await message.answer(text, reply_markup=model_action_keyboard(model_name))
    await message.answer("Вы можете продолжить редактирование или выбрать другое действие.", reply_markup=main_menu)

@router.message(StateFilter(EditModel.waiting_for_new_value), F.text == "❌ Отмена")
async def cancel_edit_model(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Редактирование модели отменено.", reply_markup=main_menu)

# ---------- Редактирование набора ----------
@router.callback_query(F.data.startswith("edit_kit_"))
async def edit_kit_start(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    kit_name = callback.data[9:]
    kit_data = sheet.get_kit_details(kit_name)
    if not kit_data:
        await callback.answer("Набор не найден", show_alert=True)
        return
    await callback.message.edit_text(
        f"✏️ Редактирование набора *{kit_name}*\nВыберите, что изменить:",
        parse_mode="Markdown",
        reply_markup=kit_parameters_keyboard(kit_name)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_kit_param_"))
async def edit_kit_param_start(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
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
        await callback.message.edit_text(
            f"📋 *Текущий состав набора {kit_name}:*\n" +
            ("\n".join([f"• {model} x{qty}" for model, qty in items]) if items else "Пока пусто"),
            parse_mode="Markdown",
            reply_markup=show_current_items_keyboard(items)
        )
        await state.set_state(EditKit.waiting_for_item_edit)
        await callback.answer()
        return
    elif param == "price":
        current = kit_data[2]
        prompt = "Введите новую *цену* (число):"
        await ask_edit_kit_value(callback, state, kit_name, param, current, prompt)
    elif param == "desc":
        current = kit_data[3] if len(kit_data) > 3 else ""
        prompt = "Введите новое *описание* (или 'нет' для пустого):"
        await ask_edit_kit_value(callback, state, kit_name, param, current, prompt)
    else:
        await callback.answer("Неизвестный параметр")

async def ask_edit_kit_value(callback, state, kit_name, param, current, prompt):
    await state.update_data(
        edit_kit_name=kit_name,
        edit_kit_param=param,
        edit_kit_current=current
    )
    await callback.message.answer(
        f"{prompt}\n\nТекущее значение: *{current}*",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditKit.waiting_for_new_value)
    await callback.answer()

@router.callback_query(EditKit.waiting_for_item_edit, F.data == "edit_kit_add")
async def edit_kit_add_model(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    models = sheet.get_all_models()
    if not models:
        await callback.answer("Нет доступных моделей", show_alert=True)
        return
    await callback.message.edit_text(
        "Выберите модель для добавления в набор:",
        reply_markup=select_model_keyboard(models, prefix="edit_kit_model")
    )
    await state.update_data(edit_kit_action="add")
    await callback.answer()

@router.callback_query(EditKit.waiting_for_item_edit, F.data.startswith("edit_kit_model_"))
async def edit_kit_select_model(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data[15:]
    if data.startswith("page_"):
        page = int(data.split('_')[1])
        models = sheet.get_all_models()
        await callback.message.edit_reply_markup(
            reply_markup=select_model_keyboard(models, page=page, prefix="edit_kit_model")
        )
        await callback.answer()
        return
    model_name = data
    await state.update_data(edit_selected_model=model_name)
    await callback.message.answer(
        f"Модель *{model_name}*\nВведите количество (целое число) для этого набора:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(EditKit.waiting_for_quantity_edit)
    await callback.answer()

@router.message(EditKit.waiting_for_quantity_edit, F.text != "❌ Отмена")
async def edit_kit_process_quantity(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
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
    await message.answer(f"✅ Добавлено: {model_name} x{qty}. Текущий состав обновлён.")
    await message.answer(
        f"📋 *Текущий состав набора {kit_name}:*",
        parse_mode="Markdown",
        reply_markup=show_current_items_keyboard(items)
    )
    await state.set_state(EditKit.waiting_for_item_edit)

@router.callback_query(EditKit.waiting_for_item_edit, F.data.startswith("remove_kit_item_"))
async def edit_kit_remove_item(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
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
    await callback.message.edit_text(
        f"🗑️ Удалено: {removed[0]} x{removed[1]}\n\n📋 *Текущий состав набора {kit_name}:*",
        parse_mode="Markdown",
        reply_markup=show_current_items_keyboard(items)
    )
    await callback.answer()

@router.callback_query(EditKit.waiting_for_item_edit, F.data == "back_to_kit")
async def edit_kit_back_to_kit(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    data = await state.get_data()
    kit_name = data.get("edit_kit_name")
    if not kit_name:
        await callback.answer("Ошибка")
        return
    kit_data = sheet.get_kit_details(kit_name)
    if kit_data:
        text = format_kit_info(kit_name, kit_data)
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
        except:
            await callback.message.edit_text(text, reply_markup=kit_action_keyboard(kit_name))
    await state.clear()
    await callback.answer()

@router.message(EditKit.waiting_for_new_value, F.text != "❌ Отмена")
async def process_edit_kit_param(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
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
        await message.answer(f"✅ Название набора изменено на *{new_value}*", parse_mode="Markdown")
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
        try:
            await message.answer(text, parse_mode="Markdown", reply_markup=kit_action_keyboard(kit_name))
        except:
            await message.answer(text, reply_markup=kit_action_keyboard(kit_name))
    await message.answer("Вы можете продолжить редактирование.", reply_markup=main_menu)

@router.message(StateFilter(EditKit), F.text == "❌ Отмена")
async def cancel_edit_kit(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Редактирование набора отменено.", reply_markup=main_menu)

# ---------- Заказ модели или набора ----------
@router.callback_query(F.data.startswith("order_model_"))
async def order_this_model(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    model_name = callback.data[12:]
    await state.update_data(order_item=model_name, order_type="model")
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
    await callback.message.answer(
        f"🛒 Заказ модели *{model_name}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.callback_query(F.data.startswith("order_kit_"))
async def order_this_kit(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    kit_name = callback.data[10:]
    await state.update_data(order_item=kit_name, order_type="kit")
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
    await callback.message.answer(
        f"🛒 Заказ набора *{kit_name}*\nВведите количество наборов (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.callback_query(CreateOrder.waiting_for_model, F.data.startswith("model_"))
async def process_order_model_from_callback(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    model_name = callback.data[6:]
    await state.update_data(order_item=model_name, order_type="model")
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
    await callback.message.answer(
        f"🛒 Заказ модели *{model_name}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.callback_query(CreateOrder.waiting_for_model, F.data.startswith("kit_"))
async def process_order_kit_from_callback(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    kit_name = callback.data[4:]
    await state.update_data(order_item=kit_name, order_type="kit")
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()
    await callback.message.answer(
        f"🛒 Заказ набора *{kit_name}*\nВведите количество наборов (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )

@router.message(CreateOrder.waiting_for_model, F.text != "❌ Отмена")
async def process_order_model_text(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await message.answer("❌ Пожалуйста, выберите элемент из списка кнопками.")
    models, kits = sheet.get_all_items()
    if models or kits:
        await message.answer("Выберите элемент:", reply_markup=items_inline_keyboard(models, kits))

@router.message(CreateOrder.waiting_for_quantity, F.text != "❌ Отмена")
async def process_order_quantity(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
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
        reply_markup=calendar_keyboard(now.year, now.month, prefix="cal_order")
    )

# ---------- Календарь для заказов ----------
@router.callback_query(F.data.startswith("cal_order_prev_"))
async def calendar_order_prev(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
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
    if not is_allowed(callback.from_user.id):
        return
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
    if not is_allowed(callback.from_user.id):
        return
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
    if not item_name or not quantity:
        await callback.answer("Ошибка: данные заказа потеряны.", show_alert=True)
        await state.clear()
        return
    position = item_name if order_type == "model" else f"Набор: {item_name}"
    try:
        order_num = sheet.add_order(position, quantity, selected_date)
        await callback.message.answer(
            f"✅ Заказ №{order_num} создан!\n\n"
            f"Позиция: {position}\n"
            f"Количество: {quantity} шт.\n"
            f"Срок: {selected_date}\n"
            f"Статус: в работе",
            reply_markup=main_menu
        )
        await callback.message.delete()
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await callback.answer()

# ---------- Календарь для задач ----------
@router.callback_query(F.data.startswith("cal_task_prev_"))
async def calendar_task_prev(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data.split("_")
    year = int(data[3])
    month = int(data[4])
    if month == 1:
        month = 12
        year -= 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_task"))
    await callback.answer()

@router.callback_query(F.data.startswith("cal_task_next_"))
async def calendar_task_next(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data.split("_")
    year = int(data[3])
    month = int(data[4])
    if month == 12:
        month = 1
        year += 1
    else:
        month += 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_task"))
    await callback.answer()

@router.callback_query(F.data.startswith("cal_task_"))
async def calendar_task_day(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    current_state = await state.get_state()
    if current_state != CreateTask.waiting_for_deadline:
        await callback.answer("Ошибка: неверное состояние", show_alert=True)
        return
    data = callback.data.split("_")
    year = int(data[2])
    month = int(data[3])
    day = int(data[4])
    selected_date = datetime(year, month, day).strftime("%Y-%m-%d")
    await state.update_data(task_deadline=selected_date)
    await callback.message.answer(
        "Введите *время выполнения* в формате `ЧЧ:ММ` (например, `19:00`):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(CreateTask.waiting_for_time)
    await callback.message.delete()
    await callback.answer()

@router.message(CreateTask.waiting_for_time, F.text != "❌ Отмена")
async def process_task_time(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    time_str = message.text.strip()
    if not re.match(r'^\d{2}:\d{2}$', time_str):
        await message.answer("❌ Неверный формат. Введите время в формате `ЧЧ:ММ`, например `19:00`.")
        return
    hours, minutes = time_str.split(':')
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        await message.answer("❌ Неверное время. Часы 0-23, минуты 0-59.")
        return
    await state.update_data(task_time=time_str)
    subscribers = sheet.get_subscribers_with_names()
    if not subscribers:
        await message.answer(
            "В вашем списке подписчиков пока никого нет. Введите *исполнителя* вручную:\n"
            "• `общая` – для всех подписчиков\n"
            "• `число` – Telegram ID (узнайте через /id)\n"
            "• или оставьте пустым (общая)",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateTask.waiting_for_assignee_manual)
    else:
        await message.answer(
            "Выберите *исполнителя* из списка подписчиков:",
            reply_markup=assignee_keyboard(subscribers)
        )
        await state.set_state(CreateTask.waiting_for_assignee_selection)

@router.callback_query(CreateTask.waiting_for_assignee_selection, F.data.startswith("assignee_"))
async def select_assignee(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    data = callback.data
    if data == "assignee_common":
        assignee_user_id = None
        await callback.answer("Выбрана общая задача")
    elif data == "assignee_manual":
        await callback.message.answer(
            "Введите *исполнителя* вручную:\n"
            "• `общая` – для всех подписчиков\n"
            "• `число` – Telegram ID (узнайте через /id)\n"
            "• или оставьте пустым (общая)",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateTask.waiting_for_assignee_manual)
        await callback.answer()
        return
    elif data.startswith("assignee_page_"):
        page = int(data.split("_")[-1])
        subscribers = sheet.get_subscribers_with_names()
        await callback.message.edit_reply_markup(reply_markup=assignee_keyboard(subscribers, page))
        await callback.answer()
        return
    elif data.startswith("assignee_"):
        user_id = int(data.split("_")[1])
        assignee_user_id = user_id
        await callback.answer(f"Выбран пользователь с ID {user_id}")
    else:
        await callback.answer("Неизвестная команда")
        return

    user_data = await state.get_data()
    title = user_data.get("task_title")
    deadline = user_data.get("task_deadline")
    time_str = user_data.get("task_time")
    if not title or not deadline or not time_str:
        await callback.message.answer("❌ Ошибка: не хватает данных. Начните заново /new_task.", reply_markup=main_menu)
        await state.clear()
        await callback.answer()
        return

    sheet.add_task(title, deadline, time_str, assignee_user_id)
    await callback.message.answer(
        f"✅ Задача *{title}* создана!\n📅 Срок: {deadline} {time_str}\n👤 Исполнитель: {assignee_user_id if assignee_user_id else 'Общая (все подписчики)'}",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()
    await callback.answer()

@router.message(CreateTask.waiting_for_assignee_manual, F.text != "❌ Отмена")
async def process_assignee_manual(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    assignee_text = message.text.strip()
    assignee_user_id = None
    if assignee_text.lower() == "общая" or assignee_text == "":
        assignee_user_id = None
    elif assignee_text.isdigit():
        assignee_user_id = int(assignee_text)
    else:
        assignee_user_id = assignee_text

    data = await state.get_data()
    title = data.get("task_title")
    deadline = data.get("task_deadline")
    time_str = data.get("task_time")
    if not title or not deadline or not time_str:
        await message.answer("❌ Ошибка: не хватает данных. Начните заново /new_task.", reply_markup=main_menu)
        await state.clear()
        return

    sheet.add_task(title, deadline, time_str, assignee_user_id)
    await message.answer(
        f"✅ Задача *{title}* создана!\n📅 Срок: {deadline} {time_str}\n👤 Исполнитель: {assignee_user_id if assignee_user_id else 'Общая (все подписчики)'}",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()

@router.message(StateFilter(CreateTask.waiting_for_assignee_manual, CreateTask.waiting_for_assignee_selection), F.text == "❌ Отмена")
async def cancel_create_task(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Создание задачи отменено.", reply_markup=main_menu)

# ---------- Остальные обработчики задач ----------
async def list_tasks(message: Message):
    user_id = message.from_user.id
    tasks = sheet.get_active_tasks(user_id)
    await message.answer(
        "Ваши задачи:" if tasks else "У вас нет активных задач. Создайте новую:",
        reply_markup=tasks_list_keyboard(tasks)
    )

async def create_task_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Введите *название задачи*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(CreateTask.waiting_for_title)

@router.message(CreateTask.waiting_for_title, F.text != "❌ Отмена")
async def process_task_title(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    title = message.text.strip()
    await state.update_data(task_title=title)
    await message.answer(
        "Выберите *срок выполнения* на календаре:",
        parse_mode="Markdown",
        reply_markup=calendar_keyboard(datetime.now().year, datetime.now().month, prefix="cal_task")
    )
    await state.set_state(CreateTask.waiting_for_deadline)

@router.callback_query(F.data.startswith("view_task_"))
async def view_task(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    task_id = int(callback.data.split("_")[-1])
    task = sheet.get_task_by_id(task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    text = f"📌 *{task['title']}*\n"
    text += f"📅 Срок: {task['deadline']} {task['time']}\n"
    text += f"👤 Исполнитель: {task['assignee'] if task['assignee'] else 'Общая'}\n"
    text += f"Статус: {'✅ Выполнена' if task['status'] != 'active' else '⏳ Активна'}"
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=task_actions_keyboard(task_id))
    except:
        await callback.message.edit_text(text, reply_markup=task_actions_keyboard(task_id))
    await callback.answer()

@router.callback_query(F.data.startswith("take_task_"))
async def take_task(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    task_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    task = sheet.get_task_by_id(task_id)
    if not task or task['status'] != 'active':
        await callback.answer("Задача неактивна или не найдена", show_alert=True)
        return
    if task['assignee'] and str(task['assignee']).isdigit() and int(task['assignee']) != user_id:
        await callback.answer("Эта задача уже назначена другому пользователю", show_alert=True)
        return
    sheet.update_task_field(task_id, 'assignee', user_id)
    await callback.answer("Вы стали исполнителем задачи!", show_alert=True)
    task = sheet.get_task_by_id(task_id)
    text = f"📌 *{task['title']}*\n📅 Срок: {task['deadline']} {task['time']}\n👤 Исполнитель: {user_id}\nСтатус: ⏳ Активна"
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=task_actions_keyboard(task_id))
    except:
        await callback.message.edit_text(text, reply_markup=task_actions_keyboard(task_id))

@router.callback_query(F.data.startswith("complete_task_"))
async def complete_task(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    task_id = int(callback.data.split("_")[-1])
    task = sheet.get_task_by_id(task_id)
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    if task['status'] != 'active':
        await callback.answer("Задача уже выполнена", show_alert=True)
        return
    user_id = callback.from_user.id
    if task['assignee'] and str(task['assignee']).isdigit() and int(task['assignee']) != user_id:
        await callback.answer("Вы не являетесь исполнителем этой задачи", show_alert=True)
        return
    result = sheet.update_task_field(task_id, 'status', 'completed')
    if not result:
        await callback.answer("Ошибка при обновлении статуса", show_alert=True)
        return
    await callback.answer("Задача отмечена выполненной!", show_alert=True)
    task = sheet.get_task_by_id(task_id)
    text = f"📌 *{task['title']}*\n📅 Срок: {task['deadline']} {task['time']}\n👤 Исполнитель: {task['assignee'] if task['assignee'] else 'Общая'}\nСтатус: ✅ Выполнена"
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except:
        await callback.message.edit_text(text)

@router.callback_query(F.data == "back_to_tasks")
async def back_to_tasks(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    await list_tasks(callback.message)
    await callback.answer()

@router.callback_query(F.data.startswith("tasks_page_"))
async def tasks_page(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    page = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    tasks = sheet.get_active_tasks(user_id)
    if not tasks:
        await callback.answer("Нет задач", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=tasks_list_keyboard(tasks, page))
    await callback.answer()

@router.callback_query(F.data == "create_task")
async def create_task_callback(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    await create_task_start(callback.message, state)
    await callback.answer()

# ---------- Расчёт ----------
@router.callback_query(F.data.startswith("calc_"))
async def start_calculation(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
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
    if not is_allowed(message.from_user.id):
        return
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

# ---------- Заказы ----------
@router.message(F.text == "📦 Мои заказы")
async def show_my_orders(message: Message):
    if not is_allowed(message.from_user.id):
        return
    orders = sheet.get_active_orders()
    if not orders:
        await message.answer("📭 У вас нет активных заказов. Создайте новый через кнопку 'Создать заказ'.")
        return
    await message.answer("Выберите заказ для просмотра или редактирования:", reply_markup=my_orders_inline_keyboard(orders))

@router.callback_query(F.data.startswith("view_order_"))
async def view_order(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    order_num = callback.data.split("_")[-1]
    order = sheet.get_order_by_number(order_num)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    num, position, qty, printed, deadline, modified, status = order[:7]
    text = f"📄 *Заказ №{num}*\n"
    text += f"Позиция: {position}\n"
    text += f"Заказано: {qty} шт.\n"
    text += f"Напечатано: {printed} шт.\n"
    text += f"Осталось: {int(qty)-int(printed)} шт.\n"
    text += f"Срок: {deadline}\n"
    text += f"Статус: {'✅ Выполнен' if status.lower() == 'да' else '⏳ В работе'}\n\n"
    if position.startswith("Набор: "):
        kit_name = position[7:]
        kit_data = sheet.get_kit_details(kit_name)
        if kit_data:
            text += f"🎁 *Состав набора:* {kit_data[1]}\n"
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=edit_order_keyboard(num))
    except:
        await callback.message.edit_text(text, reply_markup=edit_order_keyboard(num))
    await callback.answer()

@router.callback_query(F.data == "back_to_orders")
async def back_to_orders(callback: CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return
    orders = sheet.get_active_orders()
    if orders:
        await callback.message.edit_text("Выберите заказ:", reply_markup=my_orders_inline_keyboard(orders))
    else:
        await callback.message.edit_text("Нет активных заказов.")
    await callback.answer()

@router.callback_query(F.data.startswith("printed_"))
async def start_edit_printed(callback: CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return
    order_num = callback.data.split("_")[-1]
    await state.update_data(edit_order_num=order_num)
    await callback.message.answer("Введите новое количество напечатанных экземпляров (целое число):", reply_markup=cancel_keyboard)
    await state.set_state(EditOrder.waiting_for_new_printed)
    await callback.answer()

@router.message(EditOrder.waiting_for_new_printed, F.text != "❌ Отмена")
async def process_edit_printed(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
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
    if not is_allowed(callback.from_user.id):
        return
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
    if not is_allowed(callback.from_user.id):
        return
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu)
    await callback.answer()

# ---------- Отмена ----------
@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        return
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=main_menu)