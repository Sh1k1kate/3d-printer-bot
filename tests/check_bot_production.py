import os, sys, types, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_TOKEN", "123:abc")
class _Sheet:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: []
gs = types.ModuleType("google_sheets"); gs.SheetManager = _Sheet; gs.moscow_now = __import__("datetime").datetime.now
sys.modules["google_sheets"] = gs
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
import handlers.production as hp
import keyboards as kb
from states import ShipmentText, PrintMore
from production import distribute_printed

class FakeSheet:
    def __init__(s):
        s.orders = [["1", "Дракон", "4", "1", "2026-11-10", "", "Нет", "Ян"], ["2", "Дракон", "2", "0", "2026-11-20", "", "Нет", "Оля"],
                    ["3", "Лама", "3", "3", "2026-11-10", "", "Нет", "Ян"], ["4", "Медведь милашка", "6", "0", "2026-11-12", "", "Нет", "Ян"]]
        s.ship = {}; s.created = []
    def get_active_orders(s): return s.orders
    def get_price_items(s): return []
    def get_shipments(s): return dict(s.ship)
    def add_printed_batch(s, q):
        added, left = {}, {}
        for pos, qty in q.items():
            ords = [{"id": o[0], "row": i, "ordered": int(o[2]), "printed": int(o[3]), "deadline": o[4]} for i, o in enumerate(s.orders) if o[1].lower() == pos]
            ch, l = distribute_printed(ords, qty)
            for c in ch: s.orders[c["row"]][3] = str(c["printed"])
            added[pos] = sum(c["added"] for c in ch)
            if l: left[pos] = l
        return {"added": added, "leftover": left}
    def add_shipments_batch(s, items):
        for p, l, q in items: s.ship[(p.lower(), l.lower())] = s.ship.get((p.lower(), l.lower()), 0) + q
    def add_orders_batch(s, items): s.created += [i[0] for i in items]; s.orders += [[str(10 + n), i[0], str(i[1]), str(i[2]), i[3], "", "Нет", i[4]] for n, i in enumerate(items)]; return []
fs = FakeSheet(); hp.sheet = fs

out = []
async def f_answer(msg, text, **kw): out.append(("answer", text, kw.get("reply_markup")))
async def f_edit(msg, text, **kw): out.append(("edit", text, kw.get("reply_markup")))
hp.safe_answer, hp.safe_edit = f_answer, f_edit

class Msg:
    def __init__(s, text=None): s.text = text; s.sent = []
    async def answer(s, text, **kw): out.append(("msg", text, kw.get("reply_markup")))
class CB:
    def __init__(s, data): s.data = data; s.message = Msg(); s.answers = []
    async def answer(s, text=None, show_alert=False): s.answers.append((text, show_alert))
state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))
cbdata = lambda mk: [b.callback_data for row in mk.inline_keyboard for b in row]

async def run():
    # --- допечатка ---
    await hp.show_toprint(Msg("🖨️ Допечатка"), state)
    text, mk = out[-1][1], out[-1][2]
    assert text.index("Дракон") < text.index("Медведь милашка") and "Лама" not in text, text     # ближайший срок выше, готовое скрыто
    assert "осталось 5" in text and "осталось 6" in text
    assert all(len(d.encode()) <= 64 for d in cbdata(mk))
    key = kb.name_key("Дракон"); assert f"pp_{key}" in cbdata(mk)
    cb = CB(f"pp_{key}"); await hp.open_position(cb)
    t, mk = out[-1][1], out[-1][2]; assert "Осталось: 5" in t and f"ppadd_{key}_1" in cbdata(mk) and f"ppadd_{key}_5" in cbdata(mk)
    cb = CB(f"ppadd_{key}_3"); await hp.quick_add(cb)
    assert [o[3] for o in fs.orders[:2]] == ["4", "0"], fs.orders[:2]            # 1 заказ закрыт по ближайшему сроку (+3 в первый)
    assert "Осталось: 2" in out[-1][1]
    await hp.quick_add(CB(f"ppadd_{key}_2")); assert [o[3] for o in fs.orders[:2]] == ["4", "2"] and "готово" in out[-1][1]
    cb = CB("ppadd_aaaaaaaaaa_1"); await hp.quick_add(cb); assert cb.answers[-1][1] is True       # устаревший ключ
    # ввод числа
    mkey = kb.name_key("Медведь милашка")
    await hp.ask_number(CB(f"ppnum_{mkey}"), state); assert await state.get_state() == PrintMore.waiting_for_qty.state
    await hp.got_number(Msg("abc"), state); assert "целое число" in out[-1][1] and await state.get_state()
    await hp.got_number(Msg("4"), state); assert fs.orders[3][3] == "4" and await state.get_state() is None

    # --- отправка ---
    await hp.start_shipment(Msg("📤 Отправка"), state); assert await state.get_state() == ShipmentText.waiting_for_text.state
    await hp.got_shipment_text(Msg("1. Лама 1 шт"), state); assert "точка" in out[-1][1] and await state.get_state() == ShipmentText.waiting_for_text.state
    txt = "ВДНХ\n1. Медведь милашка 2 шт\n2. Дракон\nОстров\n3. Какой-то зверь 1 шт\n4. Лола 5"
    await hp.got_shipment_text(Msg(txt), state)
    t, mk = out[-1][1], out[-1][2]
    assert "✅ Медведь милашка — 2" in t and "✅ Дракон — 1" in t and "Какой-то зверь" in t and await state.get_state() == ShipmentText.confirming.state
    d = cbdata(mk); assert {"shipok_0", "shipok_1", "shipcancel"} <= set(d)
    cb = CB("shipok_0"); await hp.ship_confirm(cb, state)
    assert fs.ship[("медведь милашка", "вднх")] == 2 and fs.ship[("дракон", "вднх")] == 1 and not any(k[1] == "остров" for k in fs.ship)   # неизвестное не записано
    assert fs.orders[3][3] == "4" and "отправлено 3" in out[-2][1] and "напечатано +" not in out[-2][1] and await state.get_state() is None   # уже напечатано 4 ≥ отправлено 2 — не считаем дважды
    cb = CB("shipok_0"); await hp.ship_confirm(cb, state); assert fs.ship[("дракон", "вднх")] == 1           # повторное нажатие ничего не пишет
    # отправлено больше, чем напечатано -> «напечатано» подтягивается (4 напечатано, отправлено 2+3=5)
    await hp.start_shipment(Msg("/ship"), state); await hp.got_shipment_text(Msg("Аэропорт\nМедведь милашка 3"), state)
    await hp.ship_confirm(CB("shipok_0"), state)
    assert fs.orders[3][3] == "5" and "напечатано +1" in out[-2][1], (fs.orders[3], out[-2][1])
    # с созданием заказа для нераспознанного
    await hp.start_shipment(Msg("/ship"), state)
    await hp.got_shipment_text(Msg("Остров\nЗверь-новичок 3 шт"), state)
    assert "shipok_1" in cbdata(out[-1][2]) and "shipok_0" not in cbdata(out[-1][2])
    await hp.ship_confirm(CB("shipok_1"), state)
    assert fs.created == ["Зверь-новичок"] and fs.ship[("зверь-новичок", "остров")] == 3 and "Созданы заказы" in out[-2][1]
    # только нераспознанное и мусор
    await hp.start_shipment(Msg("/ship"), state); await hp.got_shipment_text(Msg("ВДНХ\n!!!"), state)
asyncio.run(run())
for row in kb.main_menu.keyboard: pass
assert any(b.text == "🖨️ Допечатка" for r in kb.main_menu.keyboard for b in r) and "🖨️ Допечатка" in kb.MAIN_MENU_TEXTS
print("bot production OK")
