import os
import base64
import logging
import aiohttp
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from keyboards import cancel_keyboard, main_menu, price_actions_keyboard
from states import AddPrice, EditPrice
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer, safe_edit

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

DRIVE_UPLOAD_URL = os.getenv("DRIVE_UPLOAD_URL", "")
DRIVE_UPLOAD_SECRET = os.getenv("DRIVE_UPLOAD_SECRET", "")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
PER_PAGE = 8

_user_categories = {}
_user_items_by_cat = {}
_user_edit_categories = {}
_user_edit_items_by_cat = {}


# ============================================================
# ТОЧКА ВХОДА: Reply-кнопка «💰 Прайс»
# ============================================================
@router.message(F.text == "💰 Прайс")
async def price_menu_button(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💰 *Прайс-лист*\n\nЧто хотите сделать?",
        parse_mode="Markdown",
        reply_markup=price_actions_keyboard(),
    )


@router.callback_query(F.data == "pa_view")
async def pa_view(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show_price_categories(callback.from_user.id, target=callback.message)
    await callback.answer()


@router.callback_query(F.data == "pa_add")
async def pa_add(callback: CallbackQuery, state: FSMContext):
    # Запускаем тот же флоу, что и /add_price
    await state.clear()
    await safe_answer(
        callback.message,
        "🛒 *Добавление товара в прайс*\n\nВведите *название товара*:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(AddPrice.waiting_for_name)
    await callback.answer()


@router.callback_query(F.data == "pa_edit")
async def pa_edit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = callback.from_user.id
    items = _refresh_edit_cache(uid)
    if not items:
        await safe_answer(callback.message, "Прайс пока пуст. Добавьте товары.", parse_mode="Markdown")
        await callback.answer()
        return
    kb = _build_edit_categories_keyboard(uid)
    try:
        await callback.message.edit_text(
            "✏️ *Редактирование прайса*\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        await callback.message.answer(
            "✏️ *Редактирование прайса*\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    await callback.answer()


# ============================================================
# HELPERS
# ============================================================
def _format_item_caption(it):
    lines = [f"*{escape_markdown(it.get('name') or '')}*"]
    if it.get("category"):
        lines.append(f"_{escape_markdown(it['category'])}_")
    if it.get("description"):
        lines.append("")
        lines.append(escape_markdown(it["description"]))
    if it.get("retail"):
        lines.append(f"\n💰 Розница: *{it['retail']} ₽*")
    if it.get("wholesale"):
        wf = f" (от {it['wholesale_from']} шт)" if it.get("wholesale_from") else ""
        lines.append(f"📦 Опт: {it['wholesale']} ₽{wf}")
    return "\n".join(lines)


def _format_edit_item_text(it):
    lines = [f"✏️ *{escape_markdown(it.get('name') or '—')}*"]
    lines.append(f"🏷 {escape_markdown(it.get('category') or 'Без категории')}")
    if it.get("retail"):
        lines.append(f"💰 Розница: *{it['retail']} ₽*")
    else:
        lines.append("💰 Розница: —")
    if it.get("wholesale"):
        wf = f" (от {it['wholesale_from']} шт)" if it.get("wholesale_from") else ""
        lines.append(f"📦 Опт: {it['wholesale']} ₽{wf}")
    else:
        lines.append("📦 Опт: —")
    if it.get("description"):
        desc = it["description"]
        if len(desc) > 200:
            desc = desc[:200] + "…"
        lines.append("")
        lines.append(escape_markdown(desc))
    lines.append("")
    lines.append("📷 Фото: есть" if it.get("photo") else "📷 Фото: нет")
    return "\n".join(lines)


async def _upload_photo_to_drive(file_bytes: bytes, mime: str, filename: str):
    if not DRIVE_UPLOAD_URL or not DRIVE_UPLOAD_SECRET:
        return None
    if len(file_bytes) > MAX_IMAGE_SIZE:
        return None
    b64 = base64.b64encode(file_bytes).decode("ascii")
    payload = {
        "secret": DRIVE_UPLOAD_SECRET,
        "filename": filename,
        "mime": mime,
        "image": b64,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                DRIVE_UPLOAD_URL, json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Drive upload status {resp.status}")
                    return None
                data = await resp.json()
                if data.get("ok"):
                    return data.get("url")
                logger.error(f"Drive upload error: {data.get('error')}")
                return None
    except Exception as e:
        logger.error(f"Drive upload exception: {e}")
        return None


async def _show_price_categories(uid: int, target):
    """Показ категорий прайса — общая логика для /price и кнопки."""
    items = sheet.get_price_items()
    if not items:
        await target.answer("Прайс пока пуст.")
        return
    categories = sorted({(it.get("category") or "Без категории") for it in items}, key=lambda s: s.lower())
    _user_categories[uid] = categories
    _user_items_by_cat[uid] = {
        c: [it for it in items if (it.get("category") or "Без категории") == c]
        for c in categories
    }
    kb = _build_categories_keyboard(uid)
    text = (
        f"💰 *Прайс-лист*\n\n"
        f"Всего товаров: {len(items)}\n"
        f"Категорий: {len(categories)}\n\n"
        f"Выберите категорию:"
    )
    await target.answer(text, parse_mode="Markdown", reply_markup=kb)


# ============================================================
# НАВИГАЦИЯ ПО КАТЕГОРИЯМ (/price и pa_view)
# ============================================================
def _build_categories_keyboard(uid):
    cats = _user_categories.get(uid) or []
    items_by_cat = _user_items_by_cat.get(uid) or {}
    buttons = []
    for i, c in enumerate(cats):
        count = len(items_by_cat.get(c, []))
        buttons.append([InlineKeyboardButton(text=f"{c} ({count})", callback_data=f"pr_cat:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_category_items_keyboard(uid, cat_idx, page):
    cats = _user_categories.get(uid) or []
    items_by_cat = _user_items_by_cat.get(uid) or {}
    if cat_idx >= len(cats):
        return None, None, None, None
    cat = cats[cat_idx]
    items = items_by_cat.get(cat, [])
    total = len(items)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * PER_PAGE:(page + 1) * PER_PAGE]

    buttons = []
    for it in chunk:
        row_idx = it.get("row_index")
        if row_idx is None:
            continue
        label = it.get("name") or "—"
        if it.get("retail"):
            label += f" — {it['retail']}₽"
        buttons.append([InlineKeyboardButton(text=label[:64], callback_data=f"pr_item:{row_idx}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"pr_page:{cat_idx}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"pr_page:{cat_idx}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="pr_back_cats")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"📂 *{escape_markdown(cat)}*\n\nТоваров: {total}"
    return kb, text, cat, items


@router.message(Command("price"))
async def cmd_price(message: Message):
    await _show_price_categories(message.from_user.id, target=message)


@router.callback_query(F.data == "pr_back_cats")
async def back_to_cats(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in _user_categories:
        items = sheet.get_price_items()
        categories = sorted({(it.get("category") or "Без категории") for it in items}, key=lambda s: s.lower())
        _user_categories[uid] = categories
        _user_items_by_cat[uid] = {
            c: [it for it in items if (it.get("category") or "Без категории") == c]
            for c in categories
        }
    kb = _build_categories_keyboard(uid)
    try:
        await callback.message.edit_text("💰 *Прайс-лист*\n\nВыберите категорию:",
                                         parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer("💰 *Прайс-лист*\n\nВыберите категорию:",
                                      parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("pr_cat:"))
async def show_category(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        cat_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    kb, text, _, _ = _build_category_items_keyboard(uid, cat_idx, 0)
    if not kb:
        await callback.answer("Устарело, начните заново /price", show_alert=True)
        return
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("pr_page:"))
async def paginate_category(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        _, cat_idx, page = callback.data.split(":")
        cat_idx, page = int(cat_idx), int(page)
    except Exception:
        await callback.answer("Ошибка")
        return
    kb, text, _, _ = _build_category_items_keyboard(uid, cat_idx, page)
    if not kb:
        await callback.answer("Ошибка")
        return
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("pr_item:"))
async def show_item(callback: CallbackQuery):
    try:
        row_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    it = sheet.get_price_item_by_row(row_idx)
    if not it:
        await callback.answer("Товар не найден", show_alert=True)
        return
    caption = _format_item_caption(it)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К категориям", callback_data="pr_back_cats")],
    ])
    photo = (it.get("photo") or "").strip()
    if photo:
        try:
            await callback.message.answer_photo(photo, caption=caption,
                                                parse_mode="Markdown", reply_markup=kb)
            await callback.answer()
            return
        except Exception as e:
            logger.warning(f"Не удалось отправить фото: {e}")
    await callback.message.answer(caption, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


# ============================================================
# /add_price — ДОБАВЛЕНИЕ
# ============================================================
@router.message(Command("add_price"))
async def add_price_start(message: Message, state: FSMContext):
    await state.clear()
    await safe_answer(
        message,
        "🛒 *Добавление товара в прайс*\n\nВведите *название товара*:",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard,
    )
    await state.set_state(AddPrice.waiting_for_name)


@router.message(AddPrice.waiting_for_name, F.text != "❌ Отмена")
async def price_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return
    await state.update_data(name=name)
    await safe_answer(message, "Введите *описание* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_description)


@router.message(AddPrice.waiting_for_description, F.text != "❌ Отмена")
async def price_desc(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() == "нет":
        desc = ""
    await state.update_data(description=desc)
    await safe_answer(message, "Введите *URL фото* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_photo)


@router.message(AddPrice.waiting_for_photo, F.text != "❌ Отмена")
async def price_photo(message: Message, state: FSMContext):
    photo = message.text.strip()
    if photo.lower() == "нет":
        photo = ""
    await state.update_data(photo=photo)
    await safe_answer(message, "Введите *розничную цену* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_retail)


@router.message(AddPrice.waiting_for_retail, F.text != "❌ Отмена")
async def price_retail(message: Message, state: FSMContext):
    text = message.text.strip()
    retail = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(retail=retail)
    await safe_answer(message, "Введите *оптовую цену* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_wholesale)


@router.message(AddPrice.waiting_for_wholesale, F.text != "❌ Отмена")
async def price_wholesale(message: Message, state: FSMContext):
    text = message.text.strip()
    wholesale = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(wholesale=wholesale)
    await safe_answer(message, "Введите *минимальное количество для опта* (число или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_wholesale_from)


@router.message(AddPrice.waiting_for_wholesale_from, F.text != "❌ Отмена")
async def price_wholesale_from(message: Message, state: FSMContext):
    text = message.text.strip()
    wholesale_from = "" if text.lower() in ("нет", "-", "") else text
    await state.update_data(wholesale_from=wholesale_from)
    cats = sheet.get_price_categories()
    if cats:
        cats_text = ", ".join(cats[:15])
        await safe_answer(
            message,
            f"Введите *категорию* (или 'нет'):\nСуществующие: {escape_markdown(cats_text)}",
            parse_mode="Markdown",
            reply_markup=cancel_keyboard,
        )
    else:
        await safe_answer(message, "Введите *категорию* (или 'нет'):", parse_mode="Markdown", reply_markup=cancel_keyboard)
    await state.set_state(AddPrice.waiting_for_category)


@router.message(AddPrice.waiting_for_category, F.text != "❌ Отмена")
async def price_category(message: Message, state: FSMContext):
    cat = message.text.strip()
    if cat.lower() == "нет":
        cat = "Без категории"
    data = await state.get_data()
    ok = sheet.add_price_item(
        data["name"], data.get("description", ""), data.get("photo", ""),
        data.get("retail", ""), data.get("wholesale", ""),
        data.get("wholesale_from", ""), cat,
    )
    if ok:
        await safe_answer(
            message,
            f"✅ Товар *{escape_markdown(data['name'])}* добавлен в прайс!",
            parse_mode="Markdown",
            reply_markup=main_menu,
        )
    else:
        await message.answer("❌ Не удалось добавить товар.", reply_markup=main_menu)
    await state.clear()


@router.message(StateFilter(AddPrice), F.text == "❌ Отмена")
async def cancel_add_price(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добавление товара отменено.", reply_markup=main_menu)


# ============================================================
# /edit_price — РЕДАКТИРОВАНИЕ
# ============================================================
EDIT_FIELDS = {
    "name": "📝 Название",
    "description": "📄 Описание",
    "photo": "📷 Фото",
    "retail": "💰 Розница",
    "wholesale": "📦 Опт",
    "wholesale_from": "📦 Опт от",
    "category": "🏷 Категория",
}

EDIT_PROMPTS = {
    "name": "Введите новое *название*:",
    "description": "Введите новое *описание* (или 'нет', чтобы очистить):",
    "photo": "Отправьте *фото* сообщением или введите *URL* (или 'нет', чтобы удалить):",
    "retail": "Введите новую *розничную цену* (число или 'нет'):",
    "wholesale": "Введите новую *оптовую цену* (число или 'нет'):",
    "wholesale_from": "Введите *минимальное количество для опта* (число или 'нет'):",
    "category": "Введите новую *категорию* (или 'нет' → 'Без категории'):",
}


def _build_edit_categories_keyboard(uid):
    cats = _user_edit_categories.get(uid) or []
    items_by_cat = _user_edit_items_by_cat.get(uid) or {}
    buttons = []
    for i, c in enumerate(cats):
        count = len(items_by_cat.get(c, []))
        buttons.append([InlineKeyboardButton(text=f"{c} ({count})", callback_data=f"ep_cat:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_edit_category_items_keyboard(uid, cat_idx, page):
    cats = _user_edit_categories.get(uid) or []
    items_by_cat = _user_edit_items_by_cat.get(uid) or {}
    if cat_idx >= len(cats):
        return None, None
    cat = cats[cat_idx]
    items = items_by_cat.get(cat, [])
    total = len(items)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * PER_PAGE:(page + 1) * PER_PAGE]

    buttons = []
    for it in chunk:
        row_idx = it.get("row_index")
        if row_idx is None:
            continue
        label = it.get("name") or "—"
        if it.get("retail"):
            label += f" — {it['retail']}₽"
        buttons.append([InlineKeyboardButton(text=label[:64], callback_data=f"ep_item:{row_idx}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"ep_page:{cat_idx}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"ep_page:{cat_idx}:{page+1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="🔙 К категориям", callback_data="ep_back_cats")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"✏️ *{escape_markdown(cat)}*\n\nТоваров: {total}\nВыберите товар для редактирования:"
    return kb, text


def _build_edit_item_keyboard(row_idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data=f"ep_edit:{row_idx}:name")],
        [InlineKeyboardButton(text="📄 Описание", callback_data=f"ep_edit:{row_idx}:description")],
        [InlineKeyboardButton(text="📷 Фото", callback_data=f"ep_edit:{row_idx}:photo")],
        [InlineKeyboardButton(text="💰 Розница", callback_data=f"ep_edit:{row_idx}:retail")],
        [InlineKeyboardButton(text="📦 Опт", callback_data=f"ep_edit:{row_idx}:wholesale")],
        [InlineKeyboardButton(text="📦 Опт от", callback_data=f"ep_edit:{row_idx}:wholesale_from")],
        [InlineKeyboardButton(text="🏷 Категория", callback_data=f"ep_edit:{row_idx}:category")],
        [InlineKeyboardButton(text="🗑 Удалить товар", callback_data=f"ep_del:{row_idx}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="ep_back_cats")],
    ])


def _refresh_edit_cache(uid):
    items = sheet.get_price_items()
    categories = sorted({(it.get("category") or "Без категории") for it in items}, key=lambda s: s.lower())
    _user_edit_categories[uid] = categories
    _user_edit_items_by_cat[uid] = {
        c: [it for it in items if (it.get("category") or "Без категории") == c]
        for c in categories
    }
    return items


async def _show_item_card(target, row_idx: int, is_callback: bool = True):
    it = sheet.get_price_item_by_row(row_idx)
    if not it:
        if is_callback:
            await target.answer("Товар не найден — возможно, страница устарела", show_alert=True)
        else:
            await target.answer("Товар не найден.")
        return
    text = _format_edit_item_text(it)
    kb = _build_edit_item_keyboard(row_idx)
    if is_callback:
        try:
            await target.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception:
            await target.answer(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=kb)


@router.message(Command("edit_price"))
async def cmd_edit_price(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    items = _refresh_edit_cache(uid)
    if not items:
        await message.answer("Прайс пока пуст. Добавьте товары через /add_price.")
        return
    kb = _build_edit_categories_keyboard(uid)
    await message.answer(
        "✏️ *Редактирование прайса*\n\nВыберите категорию:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@router.callback_query(F.data == "ep_back_cats")
async def ep_back_cats(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = callback.from_user.id
    if uid not in _user_edit_categories:
        _refresh_edit_cache(uid)
    kb = _build_edit_categories_keyboard(uid)
    try:
        await callback.message.edit_text(
            "✏️ *Редактирование прайса*\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        await callback.message.answer(
            "✏️ *Редактирование прайса*\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_cat:"))
async def ep_show_category(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        cat_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    kb, text = _build_edit_category_items_keyboard(uid, cat_idx, 0)
    if not kb:
        await callback.answer("Устарело, начните заново /edit_price", show_alert=True)
        return
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ep_page:"))
async def ep_paginate(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        _, cat_idx, page = callback.data.split(":")
        cat_idx, page = int(cat_idx), int(page)
    except Exception:
        await callback.answer("Ошибка")
        return
    kb, text = _build_edit_category_items_keyboard(uid, cat_idx, page)
    if not kb:
        await callback.answer("Ошибка")
        return
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ep_item:"))
async def ep_show_item(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        row_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    await _show_item_card(callback.message, row_idx, is_callback=True)
    await callback.answer()


@router.callback_query(F.data.startswith("ep_edit:"))
async def ep_edit_field(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split(":")
        if len(parts) != 3:
            raise ValueError
        row_idx = int(parts[1])
        field = parts[2]
    except Exception:
        await callback.answer("Ошибка")
        return

    if field not in EDIT_FIELDS:
        await callback.answer("Неизвестное поле")
        return

    it = sheet.get_price_item_by_row(row_idx)
    if not it:
        await callback.answer("Товар не найден", show_alert=True)
        return

    await state.update_data(edit_row_idx=row_idx, edit_field=field)
    await state.set_state(EditPrice.waiting_for_value)

    prompt = EDIT_PROMPTS[field]
    await safe_answer(
        callback.message,
        f"{prompt}\n\nТекущее значение:\n`{escape_markdown(str(it.get(field) or '—'))}`",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard,
    )
    await callback.answer()


@router.message(EditPrice.waiting_for_value, F.text == "❌ Отмена")
async def ep_cancel_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    row_idx = data.get("edit_row_idx")
    await state.clear()
    if row_idx:
        await _show_item_card(message, row_idx, is_callback=False)
    else:
        await message.answer("Редактирование отменено.", reply_markup=main_menu)


@router.message(EditPrice.waiting_for_value, F.photo)
async def ep_edit_photo_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    row_idx = data.get("edit_row_idx")
    if field != "photo":
        await message.answer("Сейчас ожидается текстовое значение. Отправьте текст или нажмите ❌ Отмена.")
        return
    if not DRIVE_UPLOAD_URL or not DRIVE_UPLOAD_SECRET:
        await message.answer("❌ Загрузка фото в Drive не настроена (нет DRIVE_UPLOAD_URL/SECRET).")
        return

    photo = message.photo[-1]
    try:
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        content = file_bytes.read()
    except Exception as e:
        await message.answer(f"❌ Не удалось скачать фото: {e}")
        return

    wait_msg = await message.answer("⏳ Загружаю фото в Google Drive…")
    url = await _upload_photo_to_drive(content, "image/jpeg", f"price_{row_idx}.jpg")
    if not url:
        await wait_msg.edit_text("❌ Не удалось загрузить фото в Drive.")
        return

    ok = sheet.update_price_item(row_idx, "photo", url)
    if not ok:
        await wait_msg.edit_text("❌ Не удалось сохранить URL фото.")
        return

    await wait_msg.edit_text("✅ Фото обновлено!")
    await state.clear()
    _refresh_edit_cache(message.from_user.id)
    await _show_item_card(message, row_idx, is_callback=False)


@router.message(EditPrice.waiting_for_value, F.text != "❌ Отмена")
async def ep_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    row_idx = data.get("edit_row_idx")
    if not field or row_idx is None:
        await message.answer("❌ Ошибка: данные потеряны.")
        await state.clear()
        return

    raw = message.text.strip()
    clear = raw.lower() in ("нет", "-", "")

    new_value = ""
    if field == "name":
        if clear:
            await message.answer("❌ Название не может быть пустым.")
            return
        new_value = raw
    elif field == "description":
        new_value = "" if clear else raw
    elif field == "photo":
        if not clear and not (raw.startswith("http://") or raw.startswith("https://")):
            await message.answer(
                "❌ Введите URL (http:// или https://), отправьте фото сообщением, либо 'нет'."
            )
            return
        new_value = "" if clear else raw
    elif field in ("retail", "wholesale"):
        new_value = "" if clear else raw
    elif field == "wholesale_from":
        if clear:
            new_value = ""
        else:
            if not raw.isdigit():
                await message.answer("❌ Введите целое число или 'нет'.")
                return
            new_value = raw
    elif field == "category":
        new_value = "Без категории" if clear else raw
    else:
        await message.answer("❌ Неизвестное поле.")
        await state.clear()
        return

    ok = sheet.update_price_item(row_idx, field, new_value)
    if not ok:
        await message.answer("❌ Не удалось сохранить изменение.")
        return

    await message.answer(f"✅ {EDIT_FIELDS[field]}: обновлено.")
    await state.clear()
    _refresh_edit_cache(message.from_user.id)
    await _show_item_card(message, row_idx, is_callback=False)


@router.callback_query(F.data.startswith("ep_del:"))
async def ep_delete_confirm(callback: CallbackQuery):
    try:
        row_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    it = sheet.get_price_item_by_row(row_idx)
    if not it:
        await callback.answer("Товар не найден", show_alert=True)
        return
    text = (
        f"🗑 *Удалить товар?*\n\n"
        f"*{escape_markdown(it.get('name') or '—')}*\n"
        f"Категория: {escape_markdown(it.get('category') or 'Без категории')}\n\n"
        f"Это действие нельзя отменить."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"ep_del_confirm:{row_idx}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"ep_item:{row_idx}")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ep_del_confirm:"))
async def ep_delete_do(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        row_idx = int(callback.data.split(":")[1])
    except Exception:
        await callback.answer("Ошибка")
        return
    ok = sheet.delete_price_item(row_idx)
    if not ok:
        await callback.answer("Не удалось удалить", show_alert=True)
        return
    await callback.answer("Товар удалён", show_alert=True)
    _refresh_edit_cache(callback.from_user.id)
    kb = _build_edit_categories_keyboard(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "🗑 Товар удалён.\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except Exception:
        await callback.message.answer(
            "🗑 Товар удалён.\n\nВыберите категорию:",
            parse_mode="Markdown",
            reply_markup=kb,
        )
