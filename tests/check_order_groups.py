import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from production import group_orders, order_group_key

O = [["1", "С прайса: Дракон", "3", "1", "2026-11-10", "", "Нет", "Ян (@a)"],
     ["2", "Кот", "2", "2", "2026-11-10", "", "Да", "Ян (@a)"],
     ["3", "Лис", "1", "0", "2026-11-10", "", "Нет", "ян (@A) "],       # регистр/пробелы не делят заказ
     ["4", "Кот", "2", "0", "2026-11-05", "", "Нет", "Оля"],
     ["5", "Х", "1", "1", "2026-11-10", "", "Нет", "Оля"],              # другой срок -> другой заказ
     ["6", "Y", "1", "1", "2026-11-01", "", "Да", ""]]
G = group_orders(O)
assert [g["ids"] for g in G] == [["4"], ["5"], ["1", "2", "3"], ["6"]], [g["ids"] for g in G]   # активные по сроку, выполненные в конце
g = G[2]
assert (g["ordered"], g["printed"], g["remaining"], g["done"], g["progress"]) == (6, 3, 3, False, 50)
assert g["positions"][0]["position"] == "Дракон" and g["positions"][1]["done"] and g["positions"][1]["remaining"] == 0
assert G[3]["done"] and G[3]["customer"] == "" and G[3]["remaining"] == 0
assert group_orders([]) == [] and group_orders([["1"]]) == []
assert order_group_key("A ", "d") == order_group_key("a", "d ") and len(order_group_key("a", "b")) == 8
print("order groups OK")

# ---- парсер состава заказа на реальном списке (55 позиций) ----
from production import parse_order_text
items, skipped, warn = parse_order_text(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "order_sample.txt"), encoding="utf-8").read())
assert (len(items), sum(i["qty"] for i in items), sum(i["qty"] * i["price"] for i in items)) == (55, 216, 337500) and not skipped and not warn
assert {i["name"] for i in items} >= {'Волан-Де-Морт', 'Лола "Острые Козырьки"', "Кот Сильвестр 51 см"}
print("order text parser OK")
