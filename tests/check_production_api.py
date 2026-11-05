import os, sys
os.environ.update(BOT_TOKEN="123456:TEST-token", ADMIN_PASSWORD="secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from production import build_production_rows

# --- 1. агрегация (исправленный ассерт порядка) ---
orders = [
    ["1", "С прайса: Дракон", "10", "4", "2026-11-05", "", "Нет", "A"],
    ["2", "дракон", "5", "5", "2026-11-03", "", "Нет", "B"],
    ["3", "Набор: Новый год", "3", "3", "2026-11-01", "", "Нет", "C"],
    ["4", "Кот", "2", "0", "", "", "Нет", ""],
    ["5", "Кракозябра", "abc", "", "2026-11-02", "", "Нет", ""],
    ["6"],
]
price = [{"name": "Дракон", "photo": "https://x/d.jpg"}, {"name": "Кот", "photo": ""}]
ship = {("дракон", "вднх"): 3, ("дракон", "остров"): 2, ("набор: новый год", "аэропорт"): 3}
rows = build_production_rows(orders, price, ship, ["ВДНХ", "Остров", "Аэропорт"])
d = {r["name"]: r for r in rows}
assert d["Дракон"]["ordered"] == 15 and d["Дракон"]["printed"] == 9 and d["Дракон"]["remaining"] == 6
assert d["Дракон"]["deadline"] == "2026-11-03" and d["Дракон"]["photo"] == "https://x/d.jpg"
assert d["Дракон"]["shipped"] == {"ВДНХ": 3, "Остров": 2, "Аэропорт": 0} and d["Дракон"]["shipped_total"] == 5
assert d["Набор: Новый год"]["remaining"] == 0 and d["Кракозябра"]["ordered"] == 0
assert all(r["remaining"] > 0 for r in rows[:2]) and all(r["remaining"] == 0 for r in rows[2:])
assert sorted(sum((r["order_ids"] for r in rows), [])) == ["1", "2", "3", "4", "5"]
print("aggregation OK:", [r["name"] for r in rows])

# --- 2. эндпоинты с подставным SheetManager ---

# заглушка Google Sheets: хендлеры бота создают SheetManager при импорте
import types, datetime as _dt
gs = types.ModuleType("google_sheets")
class _SM:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None
gs.SheetManager = _SM
gs.moscow_now = lambda: _dt.datetime.now()
sys.modules["google_sheets"] = gs
import app as appmod
from fastapi.testclient import TestClient

class Fake:
    def __init__(self): self.ship = dict(ship); self.calls = []
    def get_active_orders(self): return orders
    def get_price_items(self): return price
    def get_shipments(self): return self.ship
    def set_shipment(self, p, l, q):
        self.calls.append((p, l, q)); self.ship[(p.lower(), l.lower())] = q; return True
    def get_price_item_by_row(self, r): return None

fake = Fake(); appmod.sheet_manager = fake
c = TestClient(appmod.app, raise_server_exceptions=False)
appmod_H = lambda: {"X-Admin-Token": appmod.make_admin_token()}

r = c.get("/api/production", headers=appmod_H()); j = r.json()
assert r.status_code == 200 and j["locations"] == ["ВДНХ", "Остров", "Аэропорт"], r.text
assert j["rows"][0]["name"] in ("Дракон", "Кот")
print("GET /api/production OK, rows:", len(j["rows"]))

h = {"X-Admin-Token": appmod.make_admin_token()}
body = {"position": "С прайса: Дракон", "location": "вднх", "qty": 7}
assert c.post("/api/production/shipment", json=body).status_code == 401       # без пароля
assert c.post("/api/production/shipment", json=body, headers={"X-Admin-Token": "bad"}).status_code == 401
r = c.post("/api/production/shipment", json=body, headers=h)
assert r.status_code == 200 and fake.calls[-1] == ("Дракон", "ВДНХ", 7), (r.text, fake.calls)
assert c.post("/api/production/shipment", json={**body, "location": "Луна"}, headers=h).status_code == 400
assert c.post("/api/production/shipment", json={**body, "qty": -1}, headers=h).status_code == 400
assert c.post("/api/production/shipment", json={**body, "position": "  "}, headers=h).status_code == 400
dr = next(x for x in c.get("/api/production", headers=appmod_H()).json()["rows"] if x["name"] == "Дракон")
assert dr["shipped"]["ВДНХ"] == 7
print("POST /api/production/shipment OK (auth, validation, round-trip)")

p = c.get("/production"); assert p.status_code == 200 and "Допечатка" in p.text
assert "Disallow: /production" in c.get("/robots.txt").text
assert 'href="/production"' in c.get("/tracker").text
print("pages OK")
