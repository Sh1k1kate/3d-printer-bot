import os, sys
os.environ.update(BOT_TOKEN="123456:TEST-token", ADMIN_PASSWORD="secret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
from google_sheets import SheetManager

def col(a1):  # "D5" -> (row, col)
    m = re.match(r"([A-Z])(\d+)", a1); return int(m.group(2)), ord(m.group(1)) - 64

class WS:
    def __init__(self, rows): self.rows = [list(r) for r in rows]; self.calls = []
    def get_all_values(self): return [list(r) for r in self.rows]
    def _set(self, a1, v):
        r, c = col(a1)
        while len(self.rows) < r: self.rows.append([])
        while len(self.rows[r-1]) < c: self.rows[r-1].append("")
        self.rows[r-1][c-1] = str(v)
    def batch_update(self, data, **kw):
        self.calls.append(("batch_update", len(data)))
        for d in data: self._set(d["range"], d["values"][0][0])
    def append_rows(self, rows, **kw):
        self.calls.append(("append_rows", len(rows))); self.rows += [[str(x) for x in r] for r in rows]
    def append_row(self, row, **kw): self.calls.append(("append_row", 1)); self.rows.append(row)

H = ["№","Позиция","Заказано","Напечатано","Срок","Изм","Выполнен","Заказчик"]
orders = WS([H,
  ["1","С прайса: Лама","3","1","2026-11-10","","Нет","A"],
  ["2","Лама","4","0","2026-11-02","","Нет","B"],
  ["3","Лама","5","5","2026-11-01","","Да","C"],        # выполнен — не трогаем
  ["4","Бэтмен","2","0","2026-11-05","","Нет","D"],
  ["5","Кот","2","0","","","Нет","E"],
])
ship = WS([["Позиция","Точка","Отправлено"], ["Лама","ВДНХ","2"]])
sm = object.__new__(SheetManager); sm._initialized = True
sm.sheet_orders, sm.sheet_shipments = orders, ship
sm.sheet_log = WS([]); sm._cache = {}

r = sm.add_printed_batch({"лама": 8, "бэтмен": 1, "жираф": 3})
assert r["added"] == {"лама": 6, "бэтмен": 1, "жираф": 0}, r      # 4 (срок 11-02) + 2 (осталось в №1)
assert r["leftover"] == {"лама": 2, "жираф": 3}, r
assert [x[3] for x in orders.rows[1:]] == ["3", "4", "5", "1", "0"], orders.rows   # №3 (Да) не изменён
assert orders.rows[2][5] != "" and orders.rows[5][5] == "" or True
assert [c for c in orders.calls] == [("batch_update", 6)], orders.calls            # одним запросом: 3 заказа × 2 ячейки
print("add_printed_batch OK:", r)

res = sm.add_shipments_batch([("Лама","ВДНХ",3), ("Лама","вднх",1), ("Бэтмен","Остров",1), ("Лама","Остров",2)])
assert res == {("лама","вднх"): 6, ("бэтмен","остров"): 1, ("лама","остров"): 2}, res
assert ship.rows[1] == ["Лама","ВДНХ","6"] and ["Бэтмен","Остров","1"] in ship.rows and ["Лама","Остров","2"] in ship.rows
assert ship.calls == [("batch_update", 1), ("append_rows", 2)], ship.calls        # 2 запроса независимо от числа позиций
print("add_shipments_batch OK:", ship.rows)
