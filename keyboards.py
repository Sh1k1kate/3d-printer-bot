from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

# ---------- Главное меню ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список моделей и наборов")],
        [KeyboardButton(text="➕ Добавить модель")],
        [KeyboardButton(text="➕ Добавить набор")],
        [KeyboardButton(text="🛒 Создать заказ")],
        [KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# ---------- Список элементов (модели + наборы) ----------
def items_inline_keyboard(models, kits):
    buttons = []
    for model in models:
        buttons.append([InlineKeyboardButton(text=f"📦 Модель: {model}", callback_data=f"model_{model}")])
    for kit in kits:
        buttons.append([InlineKeyboardButton(text=f"🎁 Набор: {kit}", callback_data=f"kit_{kit}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- Карточка модели ----------
def model_action_keyboard(model_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧮 Посчитать необходимое количество", callback_data=f"calc_{model_name}")],
        [InlineKeyboardButton(text="✏️ Редактировать модель", callback_data=f"edit_model_{model_name}")],
        [InlineKeyboardButton(text="🛒 Заказать эту модель", callback_data=f"order_model_{model_name}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_items")]
    ])

# ---------- Редактирование модели ----------
def parts_inline_keyboard(model_name, parts_list):
    buttons = [[InlineKeyboardButton(text=det, callback_data=f"edit_part_{model_name}_{det}")] for det in parts_list]
    buttons.append([InlineKeyboardButton(text="🔙 Назад к модели", callback_data=f"model_{model_name}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def part_parameters_keyboard(model_name, det_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название детали", callback_data=f"edit_param_{model_name}_{det_name}_name")],
        [InlineKeyboardButton(text="📦 Кол-во на палете", callback_data=f"edit_param_{model_name}_{det_name}_on_pallet")],
        [InlineKeyboardButton(text="🔢 Кол-во на единицу модели", callback_data=f"edit_param_{model_name}_{det_name}_per_unit")],
        [InlineKeyboardButton(text="⏱ Время палета (часы минуты)", callback_data=f"edit_param_{model_name}_{det_name}_time")],
        [InlineKeyboardButton(text="⚖️ Грамм на палет", callback_data=f"edit_param_{model_name}_{det_name}_grams")],
        [InlineKeyboardButton(text="🔙 Назад к деталям", callback_data=f"edit_model_{model_name}")]
    ])

# ---------- Карточка набора ----------
def kit_action_keyboard(kit_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Заказать этот набор", callback_data=f"order_kit_{kit_name}")],
        [InlineKeyboardButton(text="✏️ Редактировать набор", callback_data=f"edit_kit_{kit_name}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_items")]
    ])

def kit_parameters_keyboard(kit_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_kit_param_{kit_name}_name")],
        [InlineKeyboardButton(text="📋 Состав", callback_data=f"edit_kit_param_{kit_name}_items")],
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit_kit_param_{kit_name}_price")],
        [InlineKeyboardButton(text="📄 Описание", callback_data=f"edit_kit_param_{kit_name}_desc")],
        [InlineKeyboardButton(text="🔙 Назад к набору", callback_data=f"kit_{kit_name}")]
    ])

# ---------- Выбор моделей для набора (с пагинацией) ----------
def select_model_keyboard(models, page=0, per_page=10, prefix="add_kit_model"):
    total = len(models)
    start = page * per_page
    end = min(start + per_page, total)
    buttons = []
    for model in models[start:end]:
        buttons.append([InlineKeyboardButton(text=model, callback_data=f"{prefix}_{model}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}_page_{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{(total-1)//per_page + 1 if total else 1}", callback_data="ignore"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}_page_{page+1}"))
    if nav:
        buttons.append(nav)
    if prefix == "add_kit_model":
        buttons.append([InlineKeyboardButton(text="✅ Готово", callback_data="add_kit_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def show_current_items_keyboard(items):
    buttons = []
    for i, (model, qty) in enumerate(items):
        buttons.append([InlineKeyboardButton(
            text=f"❌ {model} x{qty}",
            callback_data=f"remove_kit_item_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить модель", callback_data="edit_kit_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад к набору", callback_data="back_to_kit")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- Заказы ----------
def my_orders_inline_keyboard(orders):
    buttons = []
    for order in orders:
        if len(order) >= 4:
            order_num = order[0]
            model = order[1]
            buttons.append([InlineKeyboardButton(text=f"Заказ №{order_num} - {model}", callback_data=f"view_order_{order_num}")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def edit_order_keyboard(order_num):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Изменить напечатанное количество", callback_data=f"printed_{order_num}")],
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"complete_{order_num}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_orders")]
    ])

# ---------- Календарь ----------
def calendar_keyboard(year, month):
    first_day = datetime(year, month, 1)
    start_weekday = first_day.weekday()  # 0 = понедельник
    month_days = (datetime(year, month+1, 1) - timedelta(days=1)).day if month < 12 else (datetime(year+1, 1, 1) - timedelta(days=1)).day
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Окторябрь", "Ноябрь", "Декабрь"]
    header = f"{month_names[month-1]} {year}"
    nav_buttons = [
        InlineKeyboardButton(text="◀️", callback_data=f"cal_prev_{year}_{month}"),
        InlineKeyboardButton(text=header, callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_next_{year}_{month}")
    ]
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row = [InlineKeyboardButton(text=day, callback_data="ignore") for day in week_days]
    buttons = [nav_buttons, row]
    row = []
    for _ in range(start_weekday):
        row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    for day in range(1, month_days+1):
        row.append(InlineKeyboardButton(text=str(day), callback_data=f"cal_day_{year}_{month}_{day}"))
        if len(row) == 7:
            buttons.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------- Клавиатуры для задач ----------
def task_actions_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Взять задачу", callback_data=f"take_task_{task_id}")],
        [InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"complete_task_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_tasks")]
    ])

def tasks_list_keyboard(tasks, page=0, per_page=5):
    """
    tasks: список задач в виде списка словарей или кортежей.
    Возвращает клавиатуру с кнопками задач и пагинацией.
    """
    buttons = []
    start = page * per_page
    end = min(start + per_page, len(tasks))
    for task in tasks[start:end]:
        # task: (task_id, title, deadline, assignee, status)
        task_id, title, deadline, assignee, status = task
        text = f"{title} (до {deadline})"
        if assignee:
            text += f" 👤{assignee}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"view_task_{task_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tasks_page_{page-1}"))
    if end < len(tasks):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tasks_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="➕ Создать задачу", callback_data="create_task")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)