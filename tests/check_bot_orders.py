import os, sys, types, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_TOKEN", "123:abc")
class _Sheet:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: []
gs = types.ModuleType("google_sheets"); gs.SheetManager = _Sheet; sys.modules["google_sheets"] = gs
import handlers.orders as ho
import keyboards as kb

ORDERS = [["1", "Дракон", "3", "1", "2026-11-10", "", "Нет", "Ян"], ["2", "Кот", "2", "2", "2026-11-10", "", "Нет", "Ян"],
          ["3", "Лис", "1", "0", "2026-11-12", "", "Нет", "Оля"]]
class Fake:
    def __init__(s): s.completed = []
    def get_active_orders(s): return [o for o in ORDERS if o[0] not in s.completed]
    def mark_orders_completed(s, ns): s.completed.extend(str(n) for n in ns); return len(list(ns))
ho.sheet = Fake()

markup = kb.my_orders_inline_keyboard(ho.sheet.get_active_orders())
btns = [b for row in markup.inline_keyboard for b in row]
assert [b.callback_data[:3] for b in btns[:2]] == ["og_", "og_"] and "2 поз." in btns[0].text and "до 10.11" in btns[0].text, [b.text for b in btns]
assert all(len(b.callback_data.encode()) <= 64 for b in btns)
key = btns[0].callback_data

class Msg:
    def __init__(s): s.sent = []
class CB:
    def __init__(s, data): s.data = data; s.message = Msg(); s.answers = []
    async def answer(s, text=None, show_alert=False): s.answers.append((text, show_alert))
edits = []
async def fake_edit(msg, text, **kw): edits.append((text, kw.get("reply_markup")))
ho.safe_edit = fake_edit

async def run():
    cb = CB(key); await ho.view_order_group(cb)
    text, mk = edits[-1]
    assert "Ян" in text and "Дракон" in text and "Кот" in text and "1/3" in text, text
    data = [b.callback_data for row in mk.inline_keyboard for b in row]
    assert "view_order_1" in data and "view_order_2" in data and any(d.startswith("ogdone_") for d in data)
    cb2 = CB("ogdone_" + key[3:]); await ho.complete_order_group(cb2)
    assert sorted(ho.sheet.completed) == ["1", "2"], ho.sheet.completed          # закрыты все позиции заказа
    assert "поз." in cb2.answers[0][0]
    cb3 = CB(key); await ho.view_order_group(cb3)                                   # заказ уже закрыт
    assert cb3.answers[-1][1] is True
    n = len(ho.sheet.completed); cb4 = CB("ogdone_" + key[3:]); await ho.complete_order_group(cb4)
    assert len(ho.sheet.completed) == n and cb4.answers[-1][1] is True
asyncio.run(run())
print("bot order groups OK")
