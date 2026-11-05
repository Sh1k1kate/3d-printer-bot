import os
import sys
from harness import *
from fastapi.testclient import TestClient
c = TestClient(appmod.app, raise_server_exceptions=False); H = {"X-Admin-Token": appmod.make_admin_token()}; U = "/api/production/ordered"
rowof = lambda oid: next(r for r in orders.rows[1:] if r[0] == oid)
prod = lambda name: next(x for x in c.get("/api/production", headers=appmod_H()).json()["rows"] if x["name"] == name)

assert c.post(U, json={"position": "Лама", "ordered": 2}).status_code == 401
for bad in (0, -1, 10001): assert c.post(U, json={"position": "Лама", "ordered": bad}, headers=H).status_code == 400, bad
assert c.post(U, json={"position": "Нет такой", "ordered": 2}, headers=H).status_code == 404
assert rowof("2")[2] == "1"                                              # ничего не записано

# 1 -> 2 (позиция «С прайса: Лама», заказ №2)
orders.calls.clear()
r = c.post(U, json={"position": "лама", "ordered": 2}, headers=H)
assert r.json() == {"status": "ok", "name": "Лама", "before": 1, "after": 2}, r.text
assert rowof("2")[2] == "2" and rowof("2")[5] != "" and orders.calls == [("batch_update", 2)], (rowof("2"), orders.calls)
p = prod("Лама"); assert (p["ordered"], p["remaining"]) == (2, 2)
print("1 -> 2 OK")

# два заказа Бэтмена (№6 срок 11-02, №7 срок 11-09): рост уходит в поздний, уменьшение снимает с позднего и закрывает его
assert c.post(U, json={"position": "Бэтмен", "ordered": 5}, headers=H).json()["after"] == 5
assert (rowof("6")[2], rowof("7")[2]) == ("1", "4")
r = c.post(U, json={"position": "Бэтмен", "ordered": 1}, headers=H); assert r.status_code == 200, r.text
assert rowof("7")[2] == "0" and rowof("7")[6] == "Да" and rowof("6")[2] == "1" and rowof("6")[6] == "Нет"
assert prod("Бэтмен")["ordered"] == 1 and prod("Бэтмен")["order_ids"] == ["6"]
print("multi-order OK")

# меньше напечатанного нельзя (Брелок: заказано 10, напечатано 2)
r = c.post(U, json={"position": "Брелок", "ordered": 1}, headers=H)
assert r.status_code == 400 and "напечатано" in r.json()["error"], r.text
assert rowof("4")[2] == "10"
assert c.post(U, json={"position": "Брелок", "ordered": 2}, headers=H).status_code == 200 and prod("Брелок")["remaining"] == 0
print("below-printed guard OK")
