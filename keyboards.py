from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

# Главное меню (Reply-кнопки)
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список моделей")],
        [KeyboardButton(text="➕ Добавить модель")],
        [KeyboardButton(text="🛒 Создать заказ")],
        [KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Клавиатура отмены
cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)

# ---------- Модели ----------
def models_inline_keyboard(models_list):
    buttons = [[InlineKeyboardButton(text=model, callback_data=f"model_{model}")] for model in models_list]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def model_action_keyboard(model_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧮 Посчитать необходимое количество", callback_data=f"calc_{model_name}")],
        [InlineKeyboardButton(text="✏️ Редактировать модель", callback_data=f"edit_model_{model_name}")],
        [InlineKeyboardButton(text="🛒 Заказать эту модель", callback_data=f"order_model_{model_name}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_models")]
    ])

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

# ---------- Заказы ----------
def my_orders_inline_keyboard(orders):
    """
    orders: список заказов, каждый элемент - список [номер, модель, заказано, напечатано, срок, дата_изменения, выполнен]
    """
    buttons = []
    for order in orders:
        if len(order) >= 4:
            order_num = order[0]
            model = order[1]
            # Показываем только незавершённые или все? Пока все
            buttons.append([InlineKeyboardButton(text=f"Заказ №{order_num} - {model}", callback_data=f"view_order_{order_num}")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def edit_order_keyboard(order_num):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Изменить напечатанное количество", callback_data=f"printed_{order_num}")],
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"complete_{order_num}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_orders")]
    ])

# ---------- Календарь ----------
def calendar_keyboard(year, month):
    """Создаёт инлайн-клавиатуру календаря для выбора даты."""
    first_day = datetime(year, month, 1)
    start_weekday = first_day.weekday()  # понедельник=0, воскресенье=6
    # Количество дней в месяце
    if month == 12:
        next_month = datetime(year+1, 1, 1)
    else:
        next_month = datetime(year, month+1, 1)
    month_days = (next_month - timedelta(days=1)).day
    # Заголовок с месяцем и годом
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    header = f"{month_names[month-1]} {year}"
    # Кнопки навигации
    nav_buttons = [
        InlineKeyboardButton(text="◀️", callback_data=f"cal_prev_{year}_{month}"),
        InlineKeyboardButton(text=header, callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_next_{year}_{month}")
    ]
    # Дни недели
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    week_row = [InlineKeyboardButton(text=day, callback_data="ignore") for day in week_days]
    # Заполнение ячеек
    calendar_rows = [nav_buttons, week_row]
    row = []
    # Пустые ячейки до первого дня
    for _ in range(start_weekday):
        row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    for day in range(1, month_days+1):
        row.append(InlineKeyboardButton(text=str(day), callback_data=f"cal_day_{year}_{month}_{day}"))
        if len(row) == 7:
            calendar_rows.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        calendar_rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=calendar_rows)
