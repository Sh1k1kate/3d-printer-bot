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
ok = c.post("/api/production/apply", json={"items": [{"position": "С прайса: Лама", "location": "Остров", "qty": 3}], "add_printed": True}, headers=H).json()
assert ok == {"status":"ok","shipped":3,"printed_added":1,"leftover":{"Лама":2},"created":[]}, ok
assert orders.rows[2][3] == "1" and ["Лама","Остров","3"] in ship.rows

# без галочки «напечатано» — только отправка
before = [r[3] for r in orders.rows]
ok = c.post("/api/production/apply", json={"items": [{"position": "Росомаха", "location": "ВДНХ", "qty": 2}], "add_printed": False}, headers=H).json()
assert ok["printed_added"] == 0 and [r[3] for r in orders.rows] == before and ["Росомаха","ВДНХ","2"] in ship.rows
# повторная вставка того же — добавляется, а не затирается (предпросмотр защищает от дублей)
c.post("/api/production/apply", json={"items": [{"position": "Росомаха", "location": "ВДНХ", "qty": 1}], "add_printed": False}, headers=H)
assert ["Росомаха","ВДНХ","3"] in ship.rows
rows = c.get("/api/production", headers=appmod_H()).json()["rows"]; lama = next(x for x in rows if x["name"] == "Лама")
assert lama["printed"] == 1 and lama["shipped"]["Остров"] == 3 and lama["remaining"] == 0
print("apply/parse API OK")
