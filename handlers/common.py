from aiogram import Router, F, BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from config import ALLOWED_USERS
from keyboards import main_menu, MAIN_MENU_TEXTS
from aiogram.filters import StateFilter
import logging
import re

logger = logging.getLogger(__name__)

router = Router()


# ---------- Проверка доступа ----------
def is_allowed(user_id: int) -> bool:
    """Пустой/отсутствующий белый список = доступ закрыт для всех (fail closed)."""
    if not ALLOWED_USERS:
        return False
    return user_id in ALLOWED_USERS


class AccessMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        user_id = getattr(from_user, "id", None)
        if user_id is None:
            # События без отправителя (анонимные админы, каналы и т.п.) не пропускаем
            logger.warning("Событие без from_user отклонено")
            return None
        if not is_allowed(user_id):
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer("⛔ Доступ запрещён.", show_alert=True)
                else:
                    await event.answer("⛔ Доступ запрещён. Вы не авторизованы для использования этого бота.")
            except Exception as e:
                logger.warning(f"Не удалось сообщить об отказе в доступе: {e}")
            return None
        return await handler(event, data)


class ResetStateOnMenuMiddleware(BaseMiddleware):
    """
    Outer-middleware для dp.message: если пользователь прислал команду (текст на «/»)
    или нажал кнопку главного меню, сбрасывает его FSM-состояние ДО выбора хендлера,
    чтобы этот текст не попал в хендлер состояния как «ответ» (описание, название и т.п.).
    Кнопку «❌ Отмена» не трогает: её обрабатывают свои хендлеры.

    Подключение в app.py:  dp.message.outer_middleware(ResetStateOnMenuMiddleware())
    """

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        text = getattr(event, "text", None)
        if isinstance(text, str):
            t = text.strip()
            if t.startswith("/") or t in MAIN_MENU_TEXTS:
                state = data.get("state")
                if state is not None:
                    try:
                        if await state.get_state() is not None:
                            await state.clear()
                            # StateFilter читает «raw_state» из data, а не из хранилища
                            data["raw_state"] = None
                    except Exception as e:
                        logger.warning(f"Не удалось сбросить состояние: {e}")
        return await handler(event, data)


# ---------- Безопасная работа с Markdown ----------
def escape_markdown(text) -> str:
    """Экранирует спецсимволы Markdown V1 в пользовательских строках."""
    if text is None:
        return ""
    return re.sub(r"([_*`\[\]()~])", r"\\\1", str(text))


# Лимит Telegram на длину сообщения — 4096 символов; берём запас
MAX_MESSAGE_LEN = 4000


def split_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list:
    """Режет длинный текст на части <= limit символов по границам строк."""
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for line in text.split("\n"):
        # одну слишком длинную строку режем жёстко
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current or not chunks:
        chunks.append(current)
    return chunks


def _is_parse_error(e) -> bool:
    return "can't parse entities" in str(e)


async def safe_send(bot, chat_id: int, text: str, **kwargs):
    """Безопасная отправка: длинный текст — частями; при ошибке Markdown — plain-text."""
    chunks = split_message(text)
    markup = kwargs.pop("reply_markup", None)
    result = None
    for i, chunk in enumerate(chunks):
        kw = dict(kwargs)
        if markup is not None and i == len(chunks) - 1:
            kw["reply_markup"] = markup
        try:
            result = await bot.send_message(chat_id, chunk, **kw)
        except Exception as e:
            if _is_parse_error(e):
                logger.warning(f"Markdown parse error (send), fallback to plain: {e}")
                kw.pop("parse_mode", None)
                result = await bot.send_message(chat_id, chunk, **kw)
            else:
                raise
    return result


async def safe_edit(message, text: str, **kwargs):
    """
    Безопасное редактирование: при ошибке Markdown редактирует как plain-text.
    Если текст длиннее лимита — первая часть редактирует сообщение, остальные
    отправляются новыми сообщениями (клавиатура — на последней части).
    """
    chunks = split_message(text)
    markup = kwargs.pop("reply_markup", None)
    first_kwargs = dict(kwargs)
    if markup is not None and len(chunks) == 1:
        first_kwargs["reply_markup"] = markup
    try:
        result = await message.edit_text(chunks[0], **first_kwargs)
    except Exception as e:
        if _is_parse_error(e):
            logger.warning(f"Markdown parse error (edit), fallback to plain: {e}")
            first_kwargs.pop("parse_mode", None)
            try:
                result = await message.edit_text(chunks[0], **first_kwargs)
            except Exception as e2:
                logger.warning(f"Edit fallback error: {e2}")
                return None
        else:
            logger.warning(f"Edit error: {e}")
            return None
    for i, chunk in enumerate(chunks[1:], start=1):
        kw = dict(kwargs)
        if markup is not None and i == len(chunks) - 1:
            kw["reply_markup"] = markup
        try:
            result = await message.answer(chunk, **kw)
        except Exception as e:
            if _is_parse_error(e):
                kw.pop("parse_mode", None)
                result = await message.answer(chunk, **kw)
            else:
                raise
    return result


async def safe_answer(message, text: str, **kwargs):
    """Безопасный ответ: длинный текст — частями (клавиатура на последней); ошибка Markdown — plain-text."""
    chunks = split_message(text)
    markup = kwargs.pop("reply_markup", None)
    result = None
    for i, chunk in enumerate(chunks):
        kw = dict(kwargs)
        if markup is not None and i == len(chunks) - 1:
            kw["reply_markup"] = markup
        try:
            result = await message.answer(chunk, **kw)
        except Exception as e:
            if _is_parse_error(e):
                logger.warning(f"Markdown parse error (answer), fallback to plain: {e}")
                kw.pop("parse_mode", None)
                result = await message.answer(chunk, **kw)
            else:
                raise
    return result


# ---------- Игнор пустых callback (календарь, заголовки) ----------
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery):
    await callback.answer()


# ---------- Универсальный обработчик "❌ Отмена" ----------
@router.message(F.text == "❌ Отмена")
async def cancel_handler(message: Message, state: FSMContext):
    """
    Срабатывает в любом состоянии и вне его.
    Всегда возвращает пользователя в главное меню.
    """
    current_state = await state.get_state()
    if current_state is None:
        # Пользователь вне какого-либо процесса — просто подтверждаем
        await message.answer("Вы уже в главном меню.", reply_markup=main_menu)
        return
    await state.clear()
    await message.answer("Операция отменена.", reply_markup=main_menu)


# ---------- Нетекстовое сообщение (фото, стикер...) внутри диалога ----------
@router.message(~StateFilter(None), ~F.text)
async def non_text_in_state(message: Message):
    await message.answer("Ожидается текстовое сообщение. Введите значение или нажмите «❌ Отмена».")


# ---------- Fallback для необработанных callback ----------
@router.callback_query()
async def fallback_callback(callback: CallbackQuery):
    logger.warning(f"Необработанный callback: {callback.data} (от {callback.from_user.id})")
    try:
        await callback.answer(
            "⚠️ Кнопка устарела. Откройте меню заново командой /start.",
            show_alert=True
        )
    except Exception:
        pass


# ---------- Fallback для прочих сообщений ----------
@router.message()
async def fallback_message(message: Message):
    if message.text:
        logger.warning(f"Необработанное сообщение от {message.from_user.id}: {message.text[:50]}")
        if message.text.startswith("/"):
            await message.answer("🤔 Неизвестная команда. Введите /help для списка команд.")
        else:
            await message.answer(
                "🤔 Я не понял команду. Используйте кнопки меню или введите /help.",
                reply_markup=main_menu
            )


# ---------- Вспомогательные функции ----------
def format_time(minutes: int) -> str:
    if minutes <= 0:
        return "—"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours}ч"
    return f"{hours}ч {mins}мин"


def format_model_info(model_name, details):
    safe_name = escape_markdown(model_name)
    text = f"📦 *{safe_name}*\n\n"
    for i, (det_name, on_pallet, per_unit, time_pp, grams_pp) in enumerate(details, 1):
        safe_det = escape_markdown(det_name)
        text += f"🔹 *Деталь {i}:* {safe_det}\n"
        text += f"   └ На палете: {on_pallet} шт.\n"
        text += f"   └ Нужно на единицу модели: {per_unit} шт.\n"
        text += f"   └ Время печати 1 палета: {format_time(time_pp)}\n"
        text += f"   └ Грамм на 1 палет: {grams_pp} г\n\n"
    return text


def format_kit_info(kit_name, kit_data):
    name, items_text, price, desc = kit_data
    safe_name = escape_markdown(name)
    safe_items = escape_markdown(items_text)
    safe_desc = escape_markdown(desc)
    text = f"🎁 *Набор: {safe_name}*\n\n"
    text += f"📋 *Состав:* {safe_items}\n"
    if price:
        text += f"💰 *Цена:* {price} руб.\n"
    if desc:
        text += f"📄 *Описание:* {safe_desc}\n"
    return text


def parse_callback_data(data: str, separator: str = "|") -> list:
    if separator in data:
        return data.split(separator)
    return data.split("_")
