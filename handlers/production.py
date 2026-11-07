"""Допечатка и отправка в боте — то же, что страница /production.

🖨️ Допечатка: что осталось напечатать по позициям (все активные заказы вместе), кнопки «+N напечатано»
              распределяют штуки по заказам позиции (ближайший срок первым).
📤 Отправка:  вставка текста «ВДНХ / 1. Медведь милашка 2 шт …» → предпросмотр → запись отправок
              (и, по кнопке, «напечатано»).

В callback_data лежат короткие ключи позиций (name_key), а не названия: лимит Telegram — 64 байта.
Состояния между шагами хранятся только в FSM-памяти, поэтому устаревшие кнопки отвечают «откройте заново».
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from google_sheets import SheetManager
from keyboards import main_menu, cancel_keyboard, name_key, resolve_name, _btn_text
from production import parse_shipment_text, match_name
from production_service import (
    SHIPMENT_LOCATIONS, ShipmentError, apply_shipments, production_rows,
)
from states import PrintMore, ShipmentText
from .common import safe_answer, safe_edit

logger = logging.getLogger(__name__)
router = Router()
sheet = SheetManager()

MAX_LIST_BUTTONS = 60
MAX_QTY = 100_000
QUICK_ADD = (1, 2, 5, 10)
STALE = "Список изменился — откройте «🖨️ Допечатка» заново"


def _short_date(deadline):
    parts = str(deadline or "").split("-")
    return f"{parts[2]}.{parts[1]}" if len(parts) == 3 else ""


def _safe_int(text, lo=1, hi=MAX_QTY):
    text = (text or "").strip()
    if not text or not text.isascii() or not text.isdigit():
        return None
    v = int(text)
    return v if lo <= v <= hi else None


def _rows():
    return production_rows(sheet)


def _find(rows, key):
    names = [r["name"] for r in rows]
    name = resolve_name(key, names)
    return next((r for r in rows if r["name"] == name), None) if name else None


# ---------------------------------------------------------------------------
# 🖨️ Допечатка
# ---------------------------------------------------------------------------
def _toprint_text_and_kb(rows):
    todo = [r for r in rows if r["remaining"] > 0]
    if not todo:
        return "Всё напечатано. 🎉", None
    total = sum(r["remaining"] for r in todo)
    lines = [f"🖨️ Допечатать: {len(todo)} поз., {total} шт\n(ближайший срок — выше)\n"]
    buttons = []
    for r in todo[:MAX_LIST_BUTTONS]:
        dl = f" · до {_short_date(r['deadline'])}" if r["deadline"] else ""
        lines.append(f"• {r['name']} — {r['printed']}/{r['ordered']}, осталось {r['remaining']}{dl}")
        buttons.append([InlineKeyboardButton(text=_btn_text(f"{r['name']} · ещё {r['remaining']}"),
                                             callback_data=f"pp_{name_key(r['name'])}")])
    if len(todo) > MAX_LIST_BUTTONS:
        lines.append(f"…и ещё {len(todo) - MAX_LIST_BUTTONS} поз. (кнопки показаны для первых {MAX_LIST_BUTTONS})")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


def _position_text_and_kb(r):
    ship = ", ".join(f"{loc} {q}" for loc, q in r["shipped"].items() if q) or "ничего"
    text = (f"🖨️ {r['name']}\n"
            f"Заказано: {r['ordered']}\nНапечатано: {r['printed']}\nОсталось: {r['remaining']}\n"
            f"Отправлено: {r['shipped_total']} ({ship})"
            + (f"\nСрок: {r['deadline']}" if r["deadline"] else ""))
    key = name_key(r["name"])
    row = [InlineKeyboardButton(text=f"+{n}", callback_data=f"ppadd_{key}_{n}")
           for n in QUICK_ADD if n <= max(r["remaining"], 1)]
    kb = [row] if row else []
    if r["remaining"] > 0:
        kb.append([InlineKeyboardButton(text=f"✅ Всё напечатано (+{r['remaining']})", callback_data=f"ppadd_{key}_{r['remaining']}")])
    kb.append([InlineKeyboardButton(text="✏️ Другое число", callback_data=f"ppnum_{key}")])
    kb.append([InlineKeyboardButton(text="🔙 К списку", callback_data="pp_list")])
    return text, InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(F.text == "🖨️ Допечатка")
@router.message(Command("toprint"))
async def show_toprint(message: Message, state: FSMContext):
    await state.clear()
    text, kb = _toprint_text_and_kb(_rows())
    await safe_answer(message, text, reply_markup=kb)


@router.callback_query(F.data == "pp_list")
async def back_to_toprint(callback: CallbackQuery):
    text, kb = _toprint_text_and_kb(_rows())
    await safe_edit(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^pp_[a-z2-7]{10}$"))
async def open_position(callback: CallbackQuery):
    r = _find(_rows(), callback.data[3:])
    if not r:
        await callback.answer(STALE, show_alert=True)
        return
    text, kb = _position_text_and_kb(r)
    await safe_edit(callback.message, text, reply_markup=kb)
    await callback.answer()


async def _add_printed(rows, r, qty):
    """Прибавляет напечатанное и возвращает (добавлено, не влезло в заказы)."""
    res = sheet.add_printed_batch({r["name"].lower(): qty})
    return res["added"].get(r["name"].lower(), 0), res["leftover"].get(r["name"].lower(), 0)


@router.callback_query(F.data.regexp(r"^ppadd_[a-z2-7]{10}_[0-9]{1,6}$"))
async def quick_add(callback: CallbackQuery):
    _, key, n = callback.data.split("_")
    qty = _safe_int(n)
    rows = _rows()
    r = _find(rows, key)
    if not r or not qty:
        await callback.answer(STALE, show_alert=True)
        return
    added, left = await _add_printed(rows, r, qty)
    note = f"+{added} напечатано" + (f" (ещё {left} не влезло в заказы)" if left else "")
    await callback.answer(note, show_alert=bool(left))
    fresh = _find(_rows(), key)
    if fresh and fresh["remaining"] > 0:
        text, kb = _position_text_and_kb(fresh)
        await safe_edit(callback.message, text, reply_markup=kb)
    else:
        text, kb = _toprint_text_and_kb(_rows())
        await safe_edit(callback.message, f"✅ {r['name']} — готово.\n\n{text}", reply_markup=kb)


@router.callback_query(F.data.regexp(r"^ppnum_[a-z2-7]{10}$"))
async def ask_number(callback: CallbackQuery, state: FSMContext):
    r = _find(_rows(), callback.data[6:])
    if not r:
        await callback.answer(STALE, show_alert=True)
        return
    await state.set_state(PrintMore.waiting_for_qty)
    await state.update_data(key=callback.data[6:])
    await callback.message.answer(f"Сколько штук «{r['name']}» напечатано? (целое число, осталось {r['remaining']})",
                                  reply_markup=cancel_keyboard)
    await callback.answer()


@router.message(PrintMore.waiting_for_qty, F.text, F.text != "❌ Отмена")
async def got_number(message: Message, state: FSMContext):
    qty = _safe_int(message.text)
    if qty is None:
        await message.answer(f"Нужно целое число от 1 до {MAX_QTY}.")
        return
    key = (await state.get_data()).get("key")
    rows = _rows()
    r = _find(rows, key)
    await state.clear()
    if not r:
        await message.answer(STALE, reply_markup=main_menu)
        return
    added, left = await _add_printed(rows, r, qty)
    await message.answer(f"✅ {r['name']}: +{added} напечатано" + (f"\n⚠️ {left} шт не влезло в заказы (больше заказанного)" if left else ""),
                         reply_markup=main_menu)
    fresh = _find(_rows(), key)
    if fresh and fresh["remaining"] > 0:
        text, kb = _position_text_and_kb(fresh)
        await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# 📤 Отправка: вставка текста
# ---------------------------------------------------------------------------
@router.message(F.text == "📤 Отправка")
@router.message(Command("ship"))
async def start_shipment(message: Message, state: FSMContext):
    await state.set_state(ShipmentText.waiting_for_text)
    await message.answer(
        "Пришлите список отправки одним сообщением: строка с названием точки "
        f"({', '.join(SHIPMENT_LOCATIONS)}), ниже позиции вида «1. Медведь милашка 2 шт». "
        "Без количества считаю 1 шт. Точек в тексте может быть несколько.",
        reply_markup=cancel_keyboard)


def _build_preview(entries, names):
    """entries -> (ok, partial, unknown, no_location): сопоставление с активными позициями."""
    ok, partial, unknown, no_loc = [], [], [], []
    for e in entries:
        if not e["location"]:
            no_loc.append(e)
            continue
        match, conf, cands = match_name(e["name"], names)
        item = {**e, "match": match, "conf": conf, "cands": cands}
        if conf in ("exact", "near"):
            ok.append(item)
        elif conf == "partial":
            partial.append(item)
        else:
            unknown.append(item)
    return ok, partial, unknown, no_loc


@router.message(ShipmentText.waiting_for_text, F.text, F.text != "❌ Отмена")
async def got_shipment_text(message: Message, state: FSMContext):
    entries = parse_shipment_text(message.text, SHIPMENT_LOCATIONS)
    if not entries:
        await message.answer("Не нашёл ни одной позиции. Пришлите список ещё раз или нажмите «❌ Отмена».")
        return
    names = [r["name"] for r in _rows()]
    ok, partial, unknown, no_loc = _build_preview(entries, names)
    if no_loc:
        await message.answer("Не у всех позиций указана точка. Добавьте строку с названием точки "
                             f"({', '.join(SHIPMENT_LOCATIONS)}) перед списком и пришлите заново.")
        return

    lines = [f"📤 Проверьте отправку ({len(ok)} поз. к записи):\n"]
    cur = None
    for it in ok:
        if it["location"] != cur:
            cur = it["location"]; lines.append(f"\n📍 {cur}")
        approx = "" if it["conf"] == "exact" else f"  (≈ из «{it['name']}»)"
        lines.append(f"✅ {it['match']} — {it['qty']} шт{approx}")
    if partial:
        lines.append("\n⚠️ Похоже на позицию, но не уверен (НЕ записываю):")
        lines += [f"≈ «{it['name']}» — {it['qty']} шт → «{it['match']}»?" for it in partial]
    if unknown:
        lines.append("\n❌ Нет среди активных заказов:")
        lines += [f"• {it['name']} — {it['qty']} шт ({it['location']})" for it in unknown]
    if partial or unknown:
        lines.append("\nЧтобы записать неуверенные — поправьте названия в тексте и пришлите заново.")

    items = [{"position": i["match"], "location": i["location"], "qty": i["qty"], "create": False} for i in ok]
    extra = [{"position": i["name"], "location": i["location"], "qty": i["qty"], "create": True} for i in unknown]
    if not items and not extra:
        await message.answer("\n".join(lines))
        return
    await state.set_state(ShipmentText.confirming)
    await state.update_data(items=items, extra=extra)

    kb = []
    if items:
        kb.append([InlineKeyboardButton(text="✅ Записать отправку", callback_data="shipok_0_0")])
        kb.append([InlineKeyboardButton(text="✅ Записать + добавить в «напечатано»", callback_data="shipok_1_0")])
    if extra:
        kb.append([InlineKeyboardButton(text=f"➕ Всё, и создать заказы ({len(extra)} нов. поз.)", callback_data="shipok_0_1")])
        kb.append([InlineKeyboardButton(text="➕ То же + «напечатано»", callback_data="shipok_1_1")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="shipcancel")])
    await safe_answer(message, "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@router.callback_query(F.data == "shipcancel")
async def ship_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(callback.message, "Отправка отменена.")
    await callback.answer()
    await callback.message.answer("Главное меню", reply_markup=main_menu)


@router.callback_query(StateFilter(ShipmentText.confirming), F.data.regexp(r"^shipok_[01]_[01]$"))
async def ship_confirm(callback: CallbackQuery, state: FSMContext):
    _, printed, create = callback.data.split("_")
    data = await state.get_data()
    items = list(data.get("items") or [])
    if create == "1":
        items += list(data.get("extra") or [])
    if not items:
        await callback.answer(STALE, show_alert=True)
        return
    await state.clear()          # сразу: повторное нажатие не запишет отправку второй раз
    try:
        res = apply_shipments(sheet, items, add_printed=printed == "1")
    except ShipmentError as e:
        await safe_edit(callback.message, "❌ " + str(e) + "\n" + "\n".join(e.details))
        await callback.answer()
        return
    except Exception as e:
        logger.error(f"ship_confirm: {e}", exc_info=e)
        await safe_edit(callback.message, "❌ Ошибка записи. Проверьте таблицу «Отправки» перед повтором — часть данных могла записаться.")
        await callback.answer()
        return
    text = f"✅ Записано: отправлено {res['shipped']} шт"
    if printed == "1":
        text += f", напечатано +{res['printed_added']}"
    if res["created"]:
        text += "\n➕ Созданы заказы «Без заказа»: " + ", ".join(res["created"])
    if res["leftover"]:
        text += "\n⚠️ Не влезло в заказы: " + ", ".join(f"{k} — {v}" for k, v in res["leftover"].items())
    await safe_edit(callback.message, text)
    await callback.answer()
    await callback.message.answer("Главное меню", reply_markup=main_menu)
