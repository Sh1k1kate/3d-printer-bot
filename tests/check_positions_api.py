import os
import sys
from harness import *
from fastapi.testclient import TestClient
c = TestClient(appmod.app, raise_server_exceptions=False); H = {"X-Admin-Token": appmod.make_admin_token()}
today = appmod.moscow_now().strftime("%Y-%m-%d")
n_orders = len(orders.rows)

# --- 1. позиция из списка отправки, которой нет в заказах ---
body = {"items": [
    {"position": "Дельфинчик", "location": "ВДНХ", "qty": 2, "create": True},
    {"position": "дельфинчик", "location": "Остров", "qty": 1, "create": True},     # тот же товар в другую точку
    {"position": "Лама", "location": "ВДНХ", "qty": 1}], "add_printed": True}
# без create — ошибка, ничего не пишется
bad = c.post("/api/production/apply", json={"items": [{"position": "Дельфинчик", "location": "ВДНХ", "qty": 2}]}, headers=H)
assert bad.status_code == 400 and len(orders.rows) == n_orders and len(ship.rows) == 2
r = c.post("/api/production/apply", json=body, headers=H).json()
assert r["created"] == ["Дельфинчик"] and r["shipped"] == 4 and r["printed_added"] == 3 + 1, r   # 3 нового + 1 Лама
new = orders.rows[-1]
assert new[1:5] == ["Дельфинчик", "3", "3", today] and new[6:] == ["Нет", "Без заказа"] and new[0] == "9", new   # один заказ на сумму
assert len(orders.rows) == n_orders + 1
assert ["Дельфинчик", "ВДНХ", "2"] in ship.rows and ["Дельфинчик", "Остров", "1"] in ship.rows
rows = {x["name"]: x for x in c.get("/api/production", headers=appmod_H()).json()["rows"]}
d = rows["Дельфинчик"]; assert (d["ordered"], d["printed"], d["shipped_total"], d["remaining"]) == (3, 3, 3, 0)
print("create-from-shipment OK:", new)

# без галочки «напечатано»: заказ создаётся, но печать 0
r = c.post("/api/production/apply", json={"items": [{"position": "Осьминог", "location": "Аэропорт", "qty": 3, "create": True}], "add_printed": False}, headers=H).json()
assert r["created"] == ["Осьминог"] and r["printed_added"] == 0 and orders.rows[-1][1:4] == ["Осьминог", "3", "0"], (r, orders.rows[-1])
# create для уже существующей позиции не плодит дубль заказа
cnt = len(orders.rows)
r = c.post("/api/production/apply", json={"items": [{"position": "осьминог", "location": "ВДНХ", "qty": 1, "create": True}], "add_printed": False}, headers=H).json()
assert r["created"] == [] and len(orders.rows) == cnt
assert c.post("/api/production/apply", json={"items": [{"position": "x" * 101, "location": "ВДНХ", "qty": 1, "create": True}]}, headers=H).status_code == 400
print("create edge cases OK")

# --- 2. ручное добавление позиции ---
P = "/api/production/position"
assert c.post(P, json={"name": "Жираф", "ordered": 2}).status_code == 401
for bad in [{"name": "  ", "ordered": 2}, {"name": "Жираф", "ordered": 0}, {"name": "Жираф", "ordered": 2, "printed": 3},
            {"name": "Жираф", "ordered": 2, "printed": -1}, {"name": "Жираф", "ordered": 2, "deadline": "31.12.2026"}]:
    assert c.post(P, json=bad, headers=H).status_code == 400, bad
cnt = len(orders.rows)
r = c.post(P, json={"name": "С прайса: Жираф", "ordered": 5, "printed": 1, "deadline": "2026-12-01"}, headers=H).json()
assert r["status"] == "ok" and r["name"] == "Жираф" and orders.rows[-1][1:5] == ["Жираф", "5", "1", "2026-12-01"] and len(orders.rows) == cnt + 1
exp = (appmod.moscow_now() + appmod.timedelta(days=appmod.PRICE_ORDER_DEADLINE_DAYS)).strftime("%Y-%m-%d")
c.post(P, json={"name": "Слон", "ordered": 1}, headers=H); assert orders.rows[-1][4] == exp
print("add position OK")

# --- 3. убрать позицию ---
C = "/api/production/close"
assert c.post(C, json={"position": "Бэтмен"}).status_code == 401
assert c.post(C, json={"position": "Нет такого"}, headers=H).status_code == 404
shipped_before = [r for r in ship.rows if r[0] == "Бэтмен"]
r = c.post(C, json={"position": "бэтмен"}, headers=H).json()
assert r == {"status": "ok", "closed": 2, "name": "Бэтмен"}, r
assert all(o[6] == "Да" for o in orders.rows[1:] if o[1] == "Бэтмен") and "Бэтмен" not in {x["name"] for x in c.get("/api/production", headers=appmod_H()).json()["rows"]}
assert [r for r in ship.rows if r[0] == "Бэтмен"] == shipped_before            # отправки не тронуты
assert c.post(C, json={"position": "Бэтмен"}, headers=H).status_code == 404       # повторно — уже нет
print("close position OK")
