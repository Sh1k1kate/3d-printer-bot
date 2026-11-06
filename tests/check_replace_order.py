import os
from harness import *   # noqa
from fastapi.testclient import TestClient

class WS2(WS):
    def __init__(s, rows, id_=1): super().__init__(rows); s.id = id_
H = ["Номер заказа", "Позиция", "Кол-во заказано", "Кол-во напечатано", "Срок заказа", "Дата", "Выполнен", "Заказчик"]
orders = WS2([H, ["1", "Старое", "5", "2", "2026-10-31", "", "Нет", "Без заказа"], ["2", "Готовое", "1", "1", "2026-10-01", "", "Да", "Оля"],
              ["3", "Старое2", "2", "0", "2026-10-31", "", "Нет", "Без заказа"]], 10)
ships = WS2([["Позиция", "Точка", "Отправлено"], ["старое", "вднх", "2"]], 20)
archives = {}
class Spread:
    def batch_update(s, body):
        for rq in body["requests"]:
            r = rq["deleteDimension"]["range"]; ws = {10: orders, 20: ships}[r["sheetId"]]
            del ws.rows[r["startIndex"]:r["endIndex"]]
sm = object.__new__(Real); sm._initialized = True; sm._cache = {}
sm.sheet_orders, sm.sheet_shipments, sm.sheet, sm.sheet_log = orders, ships, Spread(), WS([])
sm._ensure_worksheet = lambda title, rows, cols, header: archives.setdefault(title, WS2([list(header)]))

res = sm.replace_active_orders([("Паста", 4), ("Кукуруза", 10)], "2026-11-20", "Клиент", clear_shipments=True)
assert res == {"archived": 2, "created": [4, 5], "shipments_cleared": 1}, res
assert [r[1] for r in orders.rows[1:]] == ["Готовое", "Паста", "Кукуруза"], orders.rows        # выполненное не тронуто, старые активные убраны
assert orders.rows[2][2:5] == ["4", "0", "2026-11-20"] and orders.rows[2][7] == "Клиент"
arch = archives["Заказы (архив)"].rows
assert [r[1] for r in arch[1:]] == ["Старое", "Старое2"] and arch[0][-1] == "Архивировано" and arch[1][-1]
assert ships.rows == [["Позиция", "Точка", "Отправлено"]] and archives["Отправки (архив)"].rows[1][0] == "старое"
# без очистки отправок
ships.rows.append(["паста", "остров", "1"])
res = sm.replace_active_orders([("Лама", 2)], "2026-12-01", "Другой")
assert res["archived"] == 2 and res["shipments_cleared"] == 0 and len(ships.rows) == 2 and [r[1] for r in orders.rows[1:]] == ["Готовое", "Лама"]

# ---- API ----
c = TestClient(appmod.app, raise_server_exceptions=False)
H_ = {"X-Admin-Token": appmod.make_admin_token()}
class FSM:
    calls = []
    def get_price_items(s): return [{"name": 'Лола «Острые Козырьки»', "photo": ""}, {"name": "Паста", "photo": ""}]
    def get_active_orders(s): return [["1", "A", "1", "0", "d", "", "Нет", "Кл"], ["2", "B", "1", "0", "d", "", "Нет", "Кл"]]
    def replace_active_orders(s, items, dl, cust, clr): s.calls.append((items, dl, cust, clr)); return {"archived": 2, "created": [9], "shipments_cleared": 0}
appmod.sheet_manager = FSM()
assert c.post("/api/production/order/preview", json={"text": "x"}).status_code == 401
r = c.post("/api/production/order/preview", headers=H_, json={"text": '• Лола "Острые Козырьки" — 2 шт × 4000 ₽ = 8000 ₽\n• Паста — 4 шт × 1000 ₽ = 4000 ₽\n• Новая — 1 шт × 10 ₽ = 99 ₽\nИтого'}).json()
assert r["total_qty"] == 7 and r["total_sum"] == 8000 + 4000 + 10 and r["will_archive_rows"] == 2 and r["will_archive_orders"] == 1
assert [i["name"] for i in r["items"]] == ['Лола «Острые Козырьки»', "Паста", "Новая"] and r["not_in_price"] == ["Новая"]
assert r["skipped"] == ["Итого"] and len(r["warnings"]) == 1
ok = {"customer": "Кл", "deadline": "2026-11-20", "items": [{"position": "Паста", "qty": 4}], "confirm": True}
post = lambda **kw: c.post("/api/production/order/replace", headers=H_, json={**ok, **kw})
assert post(confirm=False).status_code == 400 and post(customer=" ").status_code == 400 and post(deadline="20.11.2026").status_code == 400
assert post(items=[]).status_code == 400 and post(items=[{"position": "A", "qty": 0}]).status_code == 400
assert post(items=[{"position": "A", "qty": 1}, {"position": "a", "qty": 1}]).status_code == 400 and not FSM.calls
r = post(); assert r.status_code == 200 and r.json()["created"] == [9] and FSM.calls[0][0] == [("Паста", 4)]
print("replace order OK")
