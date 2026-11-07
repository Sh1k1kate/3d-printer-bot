import os
import sys, types, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_TOKEN", "123:abc")

class _Sheet:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: []
gs = types.ModuleType("google_sheets"); gs.SheetManager = _Sheet; gs.moscow_now = __import__("datetime").datetime.now
sys.modules["google_sheets"] = gs
# stub config if it needs env/credentials
try:
    import config  # noqa
except Exception:
    cfg = types.ModuleType("config"); cfg.ALLOWED_USERS = [1]
    sys.modules["config"] = cfg

import importlib
for m in ("start","admin","models","kits","orders","tasks","price","client_bot","common"):
    importlib.import_module(f"handlers.{m}")
print("handler modules import OK")
from handlers.common import ResetStateOnMenuMiddleware, escape_markdown  # noqa

import keyboards as kb
long = lambda c: (c * 100)[:100]
M, K, P = long("Модель_ж"), long("Набор_ы"), long("Деталь_я")
kbs = [
    kb.items_inline_keyboard([M, long("Яя")], [K]),
    kb.model_action_keyboard(M), kb.parts_inline_keyboard(M, [P]),
    kb.part_parameters_keyboard(M, P), kb.kit_action_keyboard(K),
    kb.kit_parameters_keyboard(K),
    kb.select_model_keyboard([M] * 25, page=1, prefix="add_kit_model"),
    kb.select_model_keyboard([M] * 25, page=1, prefix="edit_kit_model"),
    kb.show_current_items_keyboard([(M, 5)]), kb.edit_part_keyboard([P], M),
    kb.edit_param_keyboard(M, P), kb.detail_param_keyboard(3, M),
    kb.my_orders_inline_keyboard([("1", M, "1", "0")]), kb.edit_order_keyboard(123456),
    kb.calendar_keyboard(2026, 11), kb.calendar_keyboard(2026, 12),
    kb.task_actions_keyboard(99999), kb.tasks_list_keyboard([(1, M, "2026-01-01", "", "", "active")]),
    kb.assignee_keyboard([(123456789012, M)]), kb.add_model_action_keyboard(),
    kb.price_actions_keyboard(),
]
n = bad = 0
for k in kbs:
    for row in k.inline_keyboard:
        for b in row:
            if b.callback_data is None: continue
            n += 1
            l = len(b.callback_data.encode("utf-8"))
            if l > 64:
                bad += 1; print("TOO LONG", l, b.callback_data[:80])
# round trip
names = [M, K, "a_b"]
assert kb.resolve_name(kb.name_key(M), names) == M and kb.resolve_name("a_b", names) == "a_b"
assert kb.resolve_name("zzzzzzzzzz", names) is None
# price.py callbacks built in handler
from handlers import price
assert len(f"ep_del_confirm:{10**7}:{kb.name_key(M)}".encode()) <= 64
assert price._parse_price_value("99,9") == "99.9" and price._parse_price_value("-1") is None
assert price._parse_price_value("1e9") is None and price._parse_price_value("١٢") is None
print(f"checked {n} callback_data values, {bad} over 64 bytes")
sys.exit(1 if bad else 0)
