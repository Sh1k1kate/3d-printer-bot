from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, BotCommand, BotCommandScopeDefault
from keyboards import main_menu
from google_sheets import SheetManager
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()


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
        BotCommand(command="subscribe", description="Подписаться на уведомления"),
        BotCommand(command="unsubscribe", description="Отписаться от уведомлений"),
        BotCommand(command="settings", description="Настройки уведомлений"),
    ]
    await bot.set_my_commands(commands, scope=BotCommandScopeDefault())


@router.message(Command("start"))
async def cmd_start(message: Message):
    try:
        if hasattr(sheet, "init_sheet"):
            sheet.init_sheet()
    except Exception as e:
        logger.warning(f"init_sheet failed: {e}")

    user_id = message.from_user.id
    name = message.from_user.full_name or str(user_id)
    if sheet.add_subscriber(user_id, name):
        logger.info(f"Пользователь {user_id} ({name}) автоматически подписан")
    await message.answer(
        "👋 Привет! Я бот для управления 3D-печатью и задачами.\n\n"
        "📌 Возможности:\n"
        "• Модели и наборы\n"
        "• Заказы (модель или набор)\n"
        "• Задачи с уведомлениями\n"
        "• Просмотр статуса принтеров\n\n"
        "/help – подробная справка",
        reply_markup=main_menu
    )
    await set_commands(message.bot)

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📖 *Справка по командам*\n\n"
        "/start – запустить бота\n"
        "/help – эта справка\n"
        "/items – список моделей и наборов\n"
        "/new_order – создать новый заказ\n"
        "/my_orders – мои заказы\n"
        "/tasks – список задач\n"
        "/new_task – создать задачу\n"
        "/id – ваш Telegram ID\n"
        "/subscribe, /unsubscribe – подписка на уведомления\n"
        "/settings – настройки уведомлений"
    )
    await message.answer(help_text, parse_mode="Markdown")


@router.message(Command("items"))
async def cmd_items(message: Message):
    from handlers.models import list_items
    await list_items(message)


@router.message(Command("new_order"))
async def cmd_new_order(message: Message, state: FSMContext):
    from handlers.orders import create_order_start
    await create_order_start(message, state)


@router.message(Command("my_orders"))
async def cmd_my_orders(message: Message):
    from handlers.orders import show_my_orders
    await show_my_orders(message)


@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    from handlers.tasks import list_tasks
    await list_tasks(message)
