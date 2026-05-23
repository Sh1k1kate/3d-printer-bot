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
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_models")]
    ])

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)