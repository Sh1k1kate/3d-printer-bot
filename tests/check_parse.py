import os
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from production import parse_shipment_text, match_name, distribute_printed, name_key
TEXT = """ВДНХ


1. Медведь милашка 2 шт
2. Лама 1 шт
3. Дельфинчик 1 шт 
4. Осьминог 3 шт
5. Кликеры 10 шт
6. Брелоки 10 шт
7. Стич Скейтер 1 шт
9. Микеланджело 1 шт
10. Леонардо 1 шт 
11. Джерри «Острые козырьки» 1 шт
14. Гарри Поттер 1 шт
15. Лола «Острые Козырьки»
16. Кот Сильвестр Красный 1 шт
17. Том в Урбан стиле красный 1 шт
18. Бэтмен 1 шт
19. Даффи Дак 1 шт 
20. Пеннивайз 1 шт
"""
LOC = ["ВДНХ", "Остров", "Аэропорт"]
e = parse_shipment_text(TEXT, LOC)
assert len(e) == 17 and all(x["location"] == "ВДНХ" for x in e)
got = {x["name"]: x["qty"] for x in e}
assert got["Медведь милашка"] == 2 and got["Кликеры"] == 10 and got["Брелоки"] == 10 and got["Стич Скейтер"] == 1
assert got["Лола «Острые Козырьки»"] == 1 and got["Джерри «Острые козырьки»"] == 1 and got["Леонардо"] == 1
assert sum(x["qty"] for x in e) == 2+1+1+3+10+10+1+1+1+1+1+1+1+1+1+1+1
print("parse OK:", len(e), "строк, всего", sum(x["qty"] for x in e), "шт")

# несколько секций, разные форматы количества, секция без номеров, регистр/двоеточие
e2 = parse_shipment_text("остров:\nЛама x3\nКот 2\nаэропорт\n1) Лама 4 шт.\nЖираф", LOC)
assert [(x["location"], x["name"], x["qty"]) for x in e2] == [
    ("Остров","Лама",3), ("Остров","Кот",2), ("Аэропорт","Лама",4), ("Аэропорт","Жираф",1)], e2
assert parse_shipment_text("Лама 2", LOC)[0]["location"] is None       # нет заголовка
print("multi-section OK")

names = ["Медведь милашка", "Лама", "Кликер", "Брелок", "Лола «Острые Козырьки»",
         "Кот", "Том в урбан стиле красный", "Стич скейтер", "Бэтмен"]
for q, want, conf in [("Медведь милашка", "Медведь милашка", "exact"), ("Кликеры", "Кликер", "near"), ("Брелоки", "Брелок", "near"),
                ("Лола «Острые Козырьки»", "Лола «Острые Козырьки»", "exact"), ("лама", "Лама", "exact"),
                ("Том в Урбан стиле красный", "Том в урбан стиле красный", "exact"), ("Стич Скейтер", "Стич скейтер", "exact"),
                ("Лола", "Лола «Острые Козырьки»", "partial"),
                ("Кот Сильвестр Красный", "Кот", "partial"),
                ("Джерри «Острые козырьки»", None, "none"),   # ошибка из e2e: не должен цепляться к Лоле
                ("Пеннивайз", None, "none"), ("Даффи Дак", None, "none")]:
    m, c, top = match_name(q, names)
    assert (m, c) == (want, conf), (q, m, c, top)
print("match OK")
assert name_key("  Ёжик «Тест»! ") == "ежик тест"

orders = [{"id":"7","row":9,"ordered":3,"printed":1,"deadline":"2026-11-10"},
          {"id":"5","row":6,"ordered":4,"printed":0,"deadline":"2026-11-02"},
          {"id":"8","row":10,"ordered":2,"printed":2,"deadline":"2026-11-01"}]   # уже полный
ch, left = distribute_printed(orders, 8)
assert [(c["id"], c["printed"], c["added"]) for c in ch] == [("5",4,4), ("7",3,2)] and left == 2, (ch, left)
assert distribute_printed(orders, 0) == ([], 0) and distribute_printed([], 5) == ([], 5)
print("distribute OK")
