from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import (
    main_menu, cancel_keyboard, calendar_keyboard, tasks_list_keyboard,
    task_actions_keyboard, assignee_keyboard, name_key, resolve_name
)
from states import CreateTask, CreateOrder
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer, safe_edit
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

STALE_MSG = "Устарело, откройте список заново"


def _safe_int(text, min_value=0, max_value=10**12):
    """Безопасный разбор целого из строки (только ASCII-цифры). None при ошибке."""
    text = (text or "").strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    value = int(text)
    return value if min_value <= value <= max_value else None


def _last_int(data, min_value=0, max_value=10**12):
    """Целое после последнего '_' в callback_data (или None)."""
    return _safe_int((data or "").rsplit("_", 1)[-1], min_value, max_value)


def _parse_year_month(data, idx=3):
    """cal_*_prev_YYYY_M / cal_*_next_YYYY_M -> (year, month) или None."""
    parts = (data or "").split("_")
    if len(parts) <= idx + 1:
        return None
    year = _safe_int(parts[idx], 2000, 2100)
    month = _safe_int(parts[idx + 1], 1, 12)
    if year is None or month is None:
        return None
    return year, month


@router.message(F.text == "📋 Задачи")
async def tasks_menu(message: Message):
    await list_tasks(message)


async def list_tasks(message: Message, user_id: int = None):
    # Для callback-ов message.from_user — это бот, поэтому user_id передаём явно
    if user_id is None:
        user_id = message.from_user.id
    tasks = sheet.get_active_tasks(user_id)
    await message.answer(
        "Ваши задачи:" if tasks else "У вас нет активных задач. Создайте новую:",
        reply_markup=tasks_list_keyboard(tasks)
    )


@router.message(Command("new_task"))
async def cmd_new_task(message: Message, state: FSMContext):
    await create_task_start(message, state)


async def create_task_start(message: Message, state: FSMContext):
    await state.clear()
    await safe_answer(message, "Введите *название задачи*:", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(CreateTask.waiting_for_title)


@router.message(CreateTask.waiting_for_title, F.text, F.text != "❌ Отмена")
async def process_task_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title or len(title) > 200:
        await message.answer("❌ Название обязательно (до 200 символов).")
        return
    await state.update_data(task_title=title)

    models = sheet.get_all_models()
    found_model = None
    for model in models:
        if model.lower() in title.lower():
            found_model = model
            break

    if found_model:
        await safe_answer(
            message,
            f"🔍 Обнаружена модель *{escape_markdown(found_model)}* в названии задачи.\nХотите создать заказ?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Создать заказ", callback_data=f"auto_order_{name_key(found_model)}")],
                [InlineKeyboardButton(text="❌ Нет, только задача", callback_data="skip_order")]
            ])
        )
        await state.update_data(auto_model=found_model)
    else:
        await safe_answer(
            message,
            "Выберите *срок выполнения* на календаре:",
            parse_mode="Markdown",
            reply_markup=calendar_keyboard(datetime.now().year, datetime.now().month, prefix="cal_task")
        )
        await state.set_state(CreateTask.waiting_for_deadline)


@router.callback_query(F.data.startswith("auto_order_"))
async def auto_order(callback: CallbackQuery, state: FSMContext):
    # Имена моделей могут содержать '_' и кириллицу, поэтому в callback_data лежит ключ
    raw = callback.data[len("auto_order_"):]
    model_name = resolve_name(raw, sheet.get_all_models())
    if model_name is None:
        await callback.answer(STALE_MSG, show_alert=True)
        return
    await state.update_data(order_item=model_name, order_type="model")
    await safe_answer(
        callback.message,
        f"🛒 Заказ модели *{escape_markdown(model_name)}*\nВведите количество (целое число):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(CreateOrder.waiting_for_quantity)
    await callback.answer()


@router.callback_query(F.data == "skip_order")
async def skip_order(callback: CallbackQuery, state: FSMContext):
    await safe_answer(
        callback.message,
        "Выберите *срок выполнения* на календаре:",
        parse_mode="Markdown",
        reply_markup=calendar_keyboard(datetime.now().year, datetime.now().month, prefix="cal_task")
    )
    await state.set_state(CreateTask.waiting_for_deadline)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_task_prev_"))
async def calendar_task_prev(callback: CallbackQuery):
    ym = _parse_year_month(callback.data)
    if ym is None:
        await callback.answer("Ошибка формата")
        return
    year, month = ym
    if month == 1:
        month, year = 12, year - 1
    else:
        month -= 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_task"))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_task_next_"))
async def calendar_task_next(callback: CallbackQuery):
    ym = _parse_year_month(callback.data)
    if ym is None:
        await callback.answer("Ошибка формата")
        return
    year, month = ym
    if month == 12:
        month, year = 1, year + 1
    else:
        month += 1
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, prefix="cal_task"))
    await callback.answer()


@router.callback_query(F.data.startswith("cal_task_"))
async def calendar_task_day(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state != CreateTask.waiting_for_deadline:
        await callback.answer("Ошибка: неверное состояние", show_alert=True)
        return
    parts = callback.data.split("_")
    try:
        if len(parts) != 5:
            raise ValueError
        year, month, day = (_safe_int(parts[2], 2000, 2100), _safe_int(parts[3], 1, 12), _safe_int(parts[4], 1, 31))
        selected_date = datetime(year, month, day).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        await callback.answer("Ошибка формата", show_alert=True)
        return
    await state.update_data(task_deadline=selected_date)
    await safe_answer(
        callback.message,
        "Введите *время выполнения* в формате `ЧЧ:ММ` (например, `19:00`):",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard
    )
    await state.set_state(CreateTask.waiting_for_time)
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()


@router.message(CreateTask.waiting_for_time, F.text, F.text != "❌ Отмена")
async def process_task_time(message: Message, state: FSMContext):
    time_str = message.text.strip()
    if not re.fullmatch(r'[0-9]{2}:[0-9]{2}', time_str):
        await message.answer("❌ Неверный формат. Введите `ЧЧ:ММ`, например `19:00`.")
        return
    hours, minutes = time_str.split(':')
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        await message.answer("❌ Часы 0-23, минуты 0-59.")
        return
    await state.update_data(task_time=time_str)
    subscribers = sheet.get_subscribers_with_names()
    if not subscribers:
        await message.answer(
            "В вашем списке подписчиков пока никого нет. Введите *исполнителя* вручную:\n"
            "• `общая` – для всех подписчиков\n"
            "• `число` – Telegram ID (узнайте через /id)",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateTask.waiting_for_assignee_manual)
    else:
        await message.answer("Выберите *исполнителя*:", reply_markup=assignee_keyboard(subscribers))
        await state.set_state(CreateTask.waiting_for_assignee_selection)


async def send_interactive_notification(bot, task_id, title, deadline, time_str, assignee_user_id):
    safe_title = escape_markdown(title)
    if assignee_user_id is None:
        subscribers = sheet.get_all_subscribers()
        if subscribers:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👤 Взять задачу", callback_data=f"take_task_{task_id}")],
                [InlineKeyboardButton(text="⏰ Напомнить через час", callback_data=f"remind_task_{task_id}")],
                [InlineKeyboardButton(text="🔔 Список задач", callback_data="tasks_menu")]
            ])
            for sub in subscribers:
                try:
                    await bot.send_message(
                        sub,
                        f"📌 *Новая общая задача*\n\n"
                        f"Название: {safe_title}\n"
                        f"Срок: {deadline} {time_str}",
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление {sub}: {e}")
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить выполненной", callback_data=f"complete_task_{task_id}")],
            [InlineKeyboardButton(text="⏰ Напомнить через час", callback_data=f"remind_task_{task_id}")]
        ])
        try:
            await bot.send_message(
                assignee_user_id,
                f"📌 *Новая задача назначена вам*\n\n"
                f"Название: {safe_title}\n"
                f"Срок: {deadline} {time_str}",
                parse_mode="Markdown",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление исполнителю {assignee_user_id}: {e}")


@router.callback_query(F.data.startswith("remind_task_"))
async def remind_task(callback: CallbackQuery):
    task_id = _last_int(callback.data)
    task = sheet.get_task_by_id(task_id) if task_id is not None else None
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    await callback.answer("⏰ Напомню через час!", show_alert=True)


@router.callback_query(F.data == "tasks_menu")
async def tasks_menu_callback(callback: CallbackQuery):
    await list_tasks(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(CreateTask.waiting_for_assignee_selection, F.data.startswith("assignee_"))
async def select_assignee(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "assignee_common":
        assignee_user_id = None
        await callback.answer("Выбрана общая задача")
    elif data == "assignee_manual":
        await safe_answer(
            callback.message,
            "Введите *исполнителя* вручную:\n"
            "• `общая` – для всех подписчиков\n"
            "• `число` – Telegram ID (узнайте через /id)",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard
        )
        await state.set_state(CreateTask.waiting_for_assignee_manual)
        await callback.answer()
        return
    elif data.startswith("assignee_page_"):
        page = _last_int(data, 0, 10_000)
        if page is None:
            await callback.answer("Ошибка формата")
            return
        subscribers = sheet.get_subscribers_with_names()
        await callback.message.edit_reply_markup(reply_markup=assignee_keyboard(subscribers, page))
        await callback.answer()
        return
    elif data.startswith("assignee_"):
        user_id = _safe_int(data[len("assignee_"):], 1)
        if user_id is None:
            await callback.answer("Ошибка формата")
            return
        assignee_user_id = user_id
        await callback.answer(f"Выбран пользователь {user_id}")
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

    task_id = sheet.add_task(title, deadline, time_str, assignee_user_id)
    await send_interactive_notification(callback.bot, task_id, title, deadline, time_str, assignee_user_id)

    await safe_answer(
        callback.message,
        f"✅ Задача *{escape_markdown(title)}* создана!\n📅 Срок: {deadline} {time_str}\n"
        f"👤 Исполнитель: {assignee_user_id if assignee_user_id else 'Общая (все подписчики)'}",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()
    await callback.answer()


@router.message(CreateTask.waiting_for_assignee_manual, F.text, F.text != "❌ Отмена")
async def process_assignee_manual(message: Message, state: FSMContext):
    assignee_text = message.text.strip()
    if assignee_text.lower() == "общая" or assignee_text == "":
        assignee_user_id = None
    elif _safe_int(assignee_text, 1) is not None:
        assignee_user_id = int(assignee_text)
    else:
        await message.answer("❌ Введите `общая` или числовой Telegram ID.", parse_mode="Markdown")
        return

    data = await state.get_data()
    title = data.get("task_title")
    deadline = data.get("task_deadline")
    time_str = data.get("task_time")
    if not title or not deadline or not time_str:
        await message.answer("❌ Ошибка: не хватает данных.", reply_markup=main_menu)
        await state.clear()
        return

    task_id = sheet.add_task(title, deadline, time_str, assignee_user_id)
    await send_interactive_notification(message.bot, task_id, title, deadline, time_str, assignee_user_id)

    await safe_answer(
        message,
        f"✅ Задача *{escape_markdown(title)}* создана!\n📅 Срок: {deadline} {time_str}\n"
        f"👤 Исполнитель: {assignee_user_id if assignee_user_id else 'Общая (все подписчики)'}",
        parse_mode="Markdown",
        reply_markup=main_menu
    )
    await state.clear()


@router.callback_query(F.data.startswith("view_task_"))
async def view_task(callback: CallbackQuery):
    task_id = _last_int(callback.data)
    task = sheet.get_task_by_id(task_id) if task_id is not None else None
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    safe_title = escape_markdown(task["title"])
    text = f"📌 *{safe_title}*\n"
    text += f"📅 Срок: {task['deadline']}"
    if task.get('time'):
        text += f" {task['time']}"
    text += f"\n👤 Исполнитель: {task['assignee'] if task['assignee'] else 'Общая'}\n"
    text += f"Статус: {'✅ Выполнена' if task['status'] != 'active' else '⏳ Активна'}"
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=task_actions_keyboard(task_id))
    await callback.answer()


@router.callback_query(F.data.startswith("take_task_"))
async def take_task(callback: CallbackQuery):
    task_id = _last_int(callback.data)
    user_id = callback.from_user.id
    task = sheet.get_task_by_id(task_id) if task_id is not None else None
    if not task or task['status'] != 'active':
        await callback.answer("Задача неактивна", show_alert=True)
        return
    if task['assignee'] and str(task['assignee']).isdigit() and int(task['assignee']) != user_id:
        await callback.answer("Задача назначена другому", show_alert=True)
        return
    sheet.update_task_field(task_id, 'assignee', user_id)
    await callback.answer("Вы стали исполнителем!", show_alert=True)
    task = sheet.get_task_by_id(task_id)
    text = f"📌 *{escape_markdown(task['title'])}*\n📅 Срок: {task['deadline']} {task['time']}\n👤 Исполнитель: {user_id}\nСтатус: ⏳ Активна"
    await safe_edit(callback.message, text, parse_mode="Markdown", reply_markup=task_actions_keyboard(task_id))


# Регэксп вместо startswith: orders.py обрабатывает complete_<номер заказа>, а здесь complete_task_<id>
@router.callback_query(F.data.regexp(r"^complete_task_[0-9]+$"))
async def complete_task(callback: CallbackQuery):
    task_id = _last_int(callback.data)
    task = sheet.get_task_by_id(task_id) if task_id is not None else None
    if not task:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    if task['status'] != 'active':
        await callback.answer("Задача уже выполнена", show_alert=True)
        return
    user_id = callback.from_user.id
    if task['assignee'] and str(task['assignee']).isdigit() and int(task['assignee']) != user_id:
        await callback.answer("Вы не исполнитель этой задачи", show_alert=True)
        return
    result = sheet.update_task_field(task_id, 'status', 'completed')
    if not result:
        await callback.answer("Ошибка обновления", show_alert=True)
        return
    await callback.answer("Задача выполнена!", show_alert=True)
    task = sheet.get_task_by_id(task_id)
    text = f"📌 *{escape_markdown(task['title'])}*\n📅 Срок: {task['deadline']} {task['time']}\n👤 Исполнитель: {task['assignee'] if task['assignee'] else 'Общая'}\nСтатус: ✅ Выполнена"
    await safe_edit(callback.message, text, parse_mode="Markdown")


@router.callback_query(F.data == "back_to_tasks")
async def back_to_tasks(callback: CallbackQuery):
    await list_tasks(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("tasks_page_"))
async def tasks_page(callback: CallbackQuery):
    page = _last_int(callback.data, 0, 10_000)
    if page is None:
        await callback.answer("Ошибка формата")
        return
    user_id = callback.from_user.id
    tasks = sheet.get_active_tasks(user_id)
    if not tasks:
        await callback.answer("Нет задач", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=tasks_list_keyboard(tasks, page))
    await callback.answer()


@router.callback_query(F.data == "create_task")
async def create_task_callback(callback: CallbackQuery, state: FSMContext):
    await create_task_start(callback.message, state)
    await callback.answer()


@router.message(StateFilter(CreateTask.waiting_for_assignee_manual, CreateTask.waiting_for_assignee_selection), F.text == "❌ Отмена")
async def cancel_create_task(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Создание задачи отменено.", reply_markup=main_menu)
