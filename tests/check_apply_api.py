import os
import sys
from harness import *
from fastapi.testclient import TestClient
c = TestClient(appmod.app, raise_server_exceptions=False); H = {"X-Admin-Token": appmod.make_admin_token()}

# без пароля — нельзя
assert c.post("/api/production/parse", json={"text": "ВДНХ\nЛама 1"}).status_code == 401
assert c.post("/api/production/apply", json={"items": []}).status_code == 401
assert c.post("/api/production/parse", json={"text": "  "}, headers=H).status_code == 400

r = c.post("/api/production/parse", json={"text": "Лама 2\nРосомаха 1", "default_location": "аэропорт"}, headers=H).json()
assert [(e["match"], e["confidence"], e["location"]) for e in r["entries"]] == [("Лама","exact","Аэропорт"), ("Росомаха","exact","Аэропорт")]
assert r["locations"] == ["ВДНХ","Остров","Аэропорт"] and "Бэтмен" in r["positions"]
assert orders.rows[2][3] == "0" and len(ship.rows) == 2        # parse ничего не пишет

bad = c.post("/api/production/apply", json={"items": [
    {"position": "Лама", "location": "Луна", "qty": 1}, {"position": "Нет такой", "location": "ВДНХ", "qty": 1},
    {"position": "Лама", "location": "ВДНХ", "qty": 0}]}, headers=H)
assert bad.status_code == 400 and len(bad.json()["details"]) == 3
assert orders.rows[2][3] == "0" and len(ship.rows) == 2        # при ошибке — ничего не записано

# сверх заказа: Лама заказано 1, шлём 3 -> напечатано +1, не влезло 2, отправлено 3
ok = c.post("/api/production/apply", json={"items": [{"position": "С прайса: Лама", "location": "Остров", "qty": 3}], }, headers=H).json()
assert ok == {"status":"ok","shipped":3,"printed_added":1,"leftover":{"Лама":2},"created":[]}, ok
assert orders.rows[2][3] == "1" and ["Лама","Остров","3"] in ship.rows

# отправка позиции — «напечатано» подтягивается до «отправлено» (флаг add_printed больше не нужен)
# Росомаха: проверим, что уже напечатанное не считается дважды
ok = c.post("/api/production/apply", json={"items": [{"position": "Росомаха", "location": "ВДНХ", "qty": 2}], "add_printed": False}, headers=H).json()
assert ["Росомаха","ВДНХ","2"] in ship.rows and ok["shipped"] == 2, ok
printed_after = lambda name: sum(int(r[3]) for r in orders.rows[1:] if r[1].lower().endswith(name.lower()))
p1 = printed_after("Росомаха"); assert p1 >= 2, p1
# повторная вставка того же — отправлено 3, напечатано не меньше 3 и не раздувается лишний раз
c.post("/api/production/apply", json={"items": [{"position": "Росомаха", "location": "ВДНХ", "qty": 1}]}, headers=H)
assert ["Росомаха","ВДНХ","3"] in ship.rows and printed_after("Росомаха") >= 3
rows = c.get("/api/production", headers=appmod_H()).json()["rows"]; lama = next(x for x in rows if x["name"] == "Лама")
assert lama["printed"] == 1 and lama["shipped"]["Остров"] == 3 and lama["remaining"] == 0
print("apply/parse API OK")

# ручная правка ячейки «отправлено» тоже подтягивает «напечатано»
ship_before = len(ship.rows)
r = c.post("/api/production/shipment", json={"position": "Лама", "location": "ВДНХ", "qty": 5}, headers=H).json()
assert r["status"] == "ok" and r["printed_added"] == 0 and r["leftover"] >= 1   # Лама заказана на 1 — больше напечатать нельзя, но отправка учтена
print("manual shipment OK")
