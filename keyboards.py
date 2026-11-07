from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta
import base64
import hashlib

# ---------- Короткие ключи для callback_data ----------
# Лимит Telegram на callback_data — 64 БАЙТА (кириллица = 2 байта на символ),
# поэтому имена моделей/наборов/деталей в callback_data не кладём, а передаём
# детерминированный ключ (10 символов base32 от sha1). Состояния в памяти не нужно:
# имя находится обратно среди актуальных списков из SheetManager.
NAME_KEY_LEN = 10
CALLBACK_DATA_MAX_BYTES = 64


def name_key(name) -> str:
    """Короткий (10 симв., a-z2-7) детерминированный ключ имени для callback_data."""
    digest = hashlib.sha1(str(name).encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii")[:NAME_KEY_LEN].lower()


def resolve_name(raw, names):
    """
    Обратный поиск: по значению из callback_data находит исходное имя среди `names`.
    Поддерживает старые кнопки (в callback_data лежало полное имя) — точное совпадение.
    Возвращает None, если имя не найдено.
    """
    if raw is None:
        return None
    names = [n for n in (names or []) if n is not None]
    if raw in names:
        return raw
    for n in names:
        if name_key(n) == raw:
            return n
    return None


def _btn_text(text, limit=60):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + "…"

# ---------- Главное меню ----------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список моделей и наборов")],
        [KeyboardButton(text="➕ Добавить модель")],
        [KeyboardButton(text="➕ Добавить набор")],
        [KeyboardButton(text="🛒 Создать заказ")],
        [KeyboardButton(text="📋 Задачи")],
        [KeyboardButton(text="📦 Мои заказы")],
        [KeyboardButton(text="🖨️ Допечатка"), KeyboardButton(text="📤 Отправка")],
        [KeyboardButton(text="💰 Прайс")],          # ✅ НОВАЯ
        [KeyboardButton(text="❓ Помощь")]
    ],
    resize_keyboard=True
)

# Тексты кнопок главного меню (используются middleware сброса FSM)
MAIN_MENU_TEXTS = frozenset(
    btn.text for row in main_menu.keyboard for btn in row
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)


# ✅ Инлайн-меню для кнопки «💰 Прайс»
def price_actions_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👀 Смотреть прайс", callback_data="pa_view")],
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="pa_add")],
        [InlineKeyboardButton(text="✏️ Редактировать прайс", callback_data="pa_edit")],
    ])


def items_inline_keyboard(models, kits):
    buttons = []
    for model in models:
        buttons.append([InlineKeyboardButton(text=_btn_text(f"📦 Модель: {model}"), callback_data=f"model_{name_key(model)}")])
    for kit in kits:
        buttons.append([InlineKeyboardButton(text=_btn_text(f"🎁 Набор: {kit}"), callback_data=f"kit_{name_key(kit)}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def model_action_keyboard(model_name):
    mk = name_key(model_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧮 Посчитать необходимое количество", callback_data=f"calc_{mk}")],
        [InlineKeyboardButton(text="✏️ Редактировать модель", callback_data=f"edit_model_{mk}")],
        [InlineKeyboardButton(text="🛒 Заказать эту модель", callback_data=f"order_model_{mk}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_items")]
    ])


def parts_inline_keyboard(model_name, parts_list):
    mk = name_key(model_name)
    buttons = []
    for det_name in parts_list:
        buttons.append([InlineKeyboardButton(text=_btn_text(det_name), callback_data=f"edit_part_{mk}|{name_key(det_name)}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад к модели", callback_data=f"model_{mk}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def part_parameters_keyboard(model_name, det_name):
    model_name = name_key(model_name)
    det_name = name_key(det_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название детали", callback_data=f"edit_param_{model_name}|{det_name}|name")],
        [InlineKeyboardButton(text="📦 Кол-во на палете", callback_data=f"edit_param_{model_name}|{det_name}|on_pallet")],
        [InlineKeyboardButton(text="🔢 Кол-во на единицу", callback_data=f"edit_param_{model_name}|{det_name}|per_unit")],
        [InlineKeyboardButton(text="⏱ Время палета", callback_data=f"edit_param_{model_name}|{det_name}|time")],
        [InlineKeyboardButton(text="⚖️ Грамм на палет", callback_data=f"edit_param_{model_name}|{det_name}|grams")],
        [InlineKeyboardButton(text="🔙 Назад к деталям", callback_data=f"edit_model_{model_name}")]
    ])


def kit_action_keyboard(kit_name):
    kit_name = name_key(kit_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Заказать этот набор", callback_data=f"order_kit_{kit_name}")],
        [InlineKeyboardButton(text="✏️ Редактировать набор", callback_data=f"edit_kit_{kit_name}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_items")]
    ])


def kit_parameters_keyboard(kit_name):
    kit_name = name_key(kit_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_kit_param_{kit_name}_name")],
        [InlineKeyboardButton(text="📋 Состав", callback_data=f"edit_kit_param_{kit_name}_items")],
        [InlineKeyboardButton(text="💰 Цена", callback_data=f"edit_kit_param_{kit_name}_price")],
        [InlineKeyboardButton(text="📄 Описание", callback_data=f"edit_kit_param_{kit_name}_desc")],
        [InlineKeyboardButton(text="🔙 Назад к набору", callback_data=f"kit_{kit_name}")]
    ])


def select_model_keyboard(models, page=0, per_page=10, prefix="add_kit_model"):
    total = len(models)
    start = page * per_page
    end = min(start + per_page, total)
    buttons = []
    for model in models[start:end]:
        buttons.append([InlineKeyboardButton(text=_btn_text(model), callback_data=f"{prefix}_{name_key(model)}")])
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
            text=_btn_text(f"❌ {model} x{qty}"),
            callback_data=f"remove_kit_item_{i}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить модель", callback_data="edit_kit_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад к набору", callback_data="back_to_kit")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _short_date(deadline):
    parts = str(deadline or "").split("-")
    return f"{parts[2]}.{parts[1]}" if len(parts) == 3 else (str(deadline) or "без срока")


def my_orders_inline_keyboard(orders):
    """Заказы (заказчик + срок) с позициями внутри; по кнопке открывается состав заказа."""
    from production import group_orders
    buttons = []
    for g in group_orders(orders):
        who = g["customer"] or "Без заказчика"
        left = f" · ещё {g['remaining']}" if g["remaining"] else ""
        text = f"📦 {who} · до {_short_date(g['deadline'])} · {len(g['positions'])} поз.{left}"
        buttons.append([InlineKeyboardButton(text=_btn_text(text), callback_data=f"og_{g['key']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def order_group_keyboard(group):
    buttons = []
    for p in group["positions"]:
        mark = "✅" if p["done"] else "🖨️"
        text = f"{mark} №{p['id']} {p['position']} ({p['printed']}/{p['ordered']})"
        buttons.append([InlineKeyboardButton(text=_btn_text(text), callback_data=f"view_order_{p['id']}")])
    if not group["done"]:
        buttons.append([InlineKeyboardButton(text="✅ Отметить весь заказ выполненным", callback_data=f"ogdone_{group['key']}")])
    buttons.append([InlineKeyboardButton(text="🔙 К заказам", callback_data="back_to_orders")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_order_keyboard(order_num):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Изменить напечатанное количество", callback_data=f"printed_{order_num}")],
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"complete_{order_num}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_orders")]
    ])


def calendar_keyboard(year, month, prefix="cal_order"):
    first_day = datetime(year, month, 1)
    start_weekday = first_day.weekday()
    month_days = (datetime(year, month+1, 1) - timedelta(days=1)).day if month < 12 else (datetime(year+1, 1, 1) - timedelta(days=1)).day
    month_names = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                   "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    header = f"{month_names[month-1]} {year}"
    nav_buttons = [
        InlineKeyboardButton(text="◀️", callback_data=f"{prefix}_prev_{year}_{month}"),
        InlineKeyboardButton(text=header, callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"{prefix}_next_{year}_{month}")
    ]
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row = [InlineKeyboardButton(text=day, callback_data="ignore") for day in week_days]
    buttons = [nav_buttons, row]
    row = []
    for _ in range(start_weekday):
        row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    for day in range(1, month_days+1):
        row.append(InlineKeyboardButton(text=str(day), callback_data=f"{prefix}_{year}_{month}_{day}"))
        if len(row) == 7:
            buttons.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def task_actions_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Взять задачу", callback_data=f"take_task_{task_id}")],
        [InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"complete_task_{task_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_tasks")]
    ])


def tasks_list_keyboard(tasks, page=0, per_page=5):
    buttons = []
    start = page * per_page
    end = min(start + per_page, len(tasks))
    for task in tasks[start:end]:
        if len(task) == 6:
            task_id, title, deadline, time_str, assignee, status = task
        else:
            task_id, title, deadline, assignee, status = task
            time_str = ""
        text = f"{title} (до {deadline}"
        if time_str:
            text += f" {time_str}"
        text += ")"
        if assignee:
            text += f" 👤{assignee}"
        buttons.append([InlineKeyboardButton(text=_btn_text(text), callback_data=f"view_task_{task_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tasks_page_{page-1}"))
    if end < len(tasks):
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tasks_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="➕ Создать задачу", callback_data="create_task")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def assignee_keyboard(subscribers, page=0, per_page=5):
    total = len(subscribers)
    start = page * per_page
    end = min(start + per_page, total)
    buttons = []
    for user_id, name in subscribers[start:end]:
        buttons.append([InlineKeyboardButton(text=_btn_text(name), callback_data=f"assignee_{user_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"assignee_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"assignee_page_{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([
        InlineKeyboardButton(text="🌐 Общая (все подписчики)", callback_data="assignee_common"),
        InlineKeyboardButton(text="✏️ Ввести ID вручную", callback_data="assignee_manual")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def add_model_action_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить деталь", callback_data="add_detail")],
        [InlineKeyboardButton(text="✅ Завершить добавление", callback_data="finish_model")]
    ])


def detail_param_keyboard(detail_index, model_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Кол-во на палете", callback_data=f"set_on_pallet_{detail_index}")],
        [InlineKeyboardButton(text="🔢 Кол-во на единицу", callback_data=f"set_per_unit_{detail_index}")],
        [InlineKeyboardButton(text="⏱ Время печати", callback_data=f"set_time_{detail_index}")],
        [InlineKeyboardButton(text="⚖️ Граммовка", callback_data=f"set_grams_{detail_index}")],
        [InlineKeyboardButton(text="✅ Готово (деталь сохранена)", callback_data=f"save_detail_{detail_index}")]
    ])


def edit_part_keyboard(parts_list, model_name):
    mk = name_key(model_name)
    buttons = []
    for det_name in parts_list:
        buttons.append([InlineKeyboardButton(text=_btn_text(det_name), callback_data=f"edit_part_{mk}|{name_key(det_name)}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"model_{mk}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_param_keyboard(model_name, det_name):
    model_name = name_key(model_name)
    det_name = name_key(det_name)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data=f"edit_param_{model_name}|{det_name}|name")],
        [InlineKeyboardButton(text="📦 Кол-во на палете", callback_data=f"edit_param_{model_name}|{det_name}|on_pallet")],
        [InlineKeyboardButton(text="🔢 Кол-во на единицу", callback_data=f"edit_param_{model_name}|{det_name}|per_unit")],
        [InlineKeyboardButton(text="⏱ Время печати", callback_data=f"edit_param_{model_name}|{det_name}|time")],
        [InlineKeyboardButton(text="⚖️ Граммовка", callback_data=f"edit_param_{model_name}|{det_name}|grams")],
        [InlineKeyboardButton(text="🗑 Удалить деталь", callback_data=f"edit_param_{model_name}|{det_name}|delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"edit_model_{model_name}")]
    ])
