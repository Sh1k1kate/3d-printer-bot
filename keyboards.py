from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Список моделей")],
        [KeyboardButton(text="➕ Добавить модель")]
    ],
    resize_keyboard=True
)

def models_inline_keyboard(models_list):
    buttons = [[InlineKeyboardButton(text=model, callback_data=f"model_{model}")] for model in models_list]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def model_action_keyboard(model_name):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧮 Посчитать необходимое количество", callback_data=f"calc_{model_name}")],
        [InlineKeyboardButton(text="✏️ Редактировать модель", callback_data=f"edit_model_{model_name}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_models")]
    ])

def parts_inline_keyboard(model_name, parts_list):
    """
    parts_list: list of (det_name, row_index) или просто det_name
    Возвращает клавиатуру с кнопками деталей.
    """
    buttons = []
    for det_name in parts_list:
        buttons.append([InlineKeyboardButton(text=det_name, callback_data=f"edit_part_{model_name}_{det_name}")])
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

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)
