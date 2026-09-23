from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import cancel_keyboard, main_menu
from states import AddPrice
from google_sheets import SheetManager
from .common import escape_markdown, safe_answer, safe_edit
import logging

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

# Кеш для инлайн-навигации: user_id → категории и товары
_user_categories = {}
_user_items_by_cat = {}

PER_PAGE = 8


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


# ---------- КОМАНДА /price ----------
@router.message(Command("price"))
async def cmd_price(message: Message):
    uid = message.from_user.id
    items = sheet.get_price_items()
    if not items:
        await message.answer("Прайс пока пуст.")
        return
    categories = sorted({(it.get("category") or "Без категории") for it in items}, key=lambda s: s.lower())
    _user_categories[uid] = categories
    _user_items_by_cat[uid] = {
        c: [it for it in items if (it.get("category") or "Без категории") == c]
        for c in categories
    }
    kb = _build_categories_keyboard(uid)
    await message.answer(
        f"💰 *Прайс-лист*\n\nВсего товаров: {len(items)}\nКатегорий: {len(categories)}\n\nВыберите категорию:",
        parse_mode="Markdown",
        reply_markup=kb,
    )


@router.callback_query(F.data == "pr_back_cats")
async def back_to_cats(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid not in _user_categories:
        # Пересобираем
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
    kb, text, cat, items = _build_category_items_keyboard(uid, cat_idx, 0) or (None, None, None, None)
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
    kb, text, cat, items = _build_category_items_keyboard(uid, cat_idx, page) or (None, None, None, None)
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


# ---------- /add_price (добавление из бота) ----------
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
