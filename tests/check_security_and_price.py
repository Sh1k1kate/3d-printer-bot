import os
from harness import *   # noqa: заглушка Sheets, appmod, WS, Real
import time, json
from fastapi.testclient import TestClient

c = TestClient(appmod.app, raise_server_exceptions=False)

# ---- вход и токены ----
assert c.post("/api/admin/login", json={"password": "wrong"}).status_code == 401
r = c.post("/api/admin/login", json={"password": "secret"})
assert r.status_code == 200 and r.json()["token"] and r.json()["expires_in"] > 0
tok = r.json()["token"]
H = {"X-Admin-Token": tok}
assert not appmod.check_admin_token("secret")                       # сырой пароль больше не принимается
assert not appmod.check_admin_token(tok[:-1] + ("0" if tok[-1] != "0" else "1"))
assert not appmod.check_admin_token(f"{int(time.time()) - 5}." + tok.split(".")[1])   # подпись от другого exp
assert not appmod.check_admin_token(appmod.make_admin_token(ttl=-10))                 # истёк
for url in ["/api/orders", "/api/tasks", "/api/printers", "/api/production", "/api/price/admin"]:
    assert c.get(url).status_code == 401, url
    assert c.get(url, headers={"X-Admin-Token": "secret"}).status_code == 401, url
assert c.get("/api/orders", headers=H).status_code == 200

# ---- перебор пароля блокируется ----
appmod._login_fails.clear()
codes = [c.post("/api/admin/login", json={"password": f"x{i}"}).status_code for i in range(7)]
assert codes[:5] == [401] * 5 and codes[5:] == [429, 429], codes
assert c.post("/api/admin/login", json={"password": "secret"}).status_code == 429   # и верный пока нельзя
appmod._login_fails.clear()

# ---- вебхук: секрет ----
appmod.WEBHOOK_SECRET = "whs"
assert c.post("/webhook", json={}).status_code == 403
assert c.post("/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "bad"}).status_code == 403
assert c.post("/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "whs"}).status_code == 200
appmod.WEBHOOK_SECRET = ""

# ---- заявка с прайса: цены считает сервер ----
class FakeSM:
    def __init__(s): s.orders = []; s.promo_used = []
    def get_price_items(s):
        return [{"row_index": 3, "name": "Дракон", "retail": "500", "wholesale": "400", "wholesale_from": "5"},
                {"row_index": 4, "name": "Кот <b>", "retail": "100 ₽", "wholesale": "", "wholesale_from": ""}]
    def add_order(s, pos, qty, dl, cust): s.orders.append((pos, qty, cust)); return len(s.orders)
    def validate_promo(s, code): return {"valid": code == "OK", "code": code, "discount_percent": 10}
    def increment_promo_usage(s, code): s.promo_used.append(code)
fake = FakeSM(); appmod.sheet_manager = fake
sent = []
class FakeBot:
    async def send_message(self, rid, text, **kw): sent.append((rid, text))
appmod.bot = FakeBot(); appmod.PRICE_ORDER_CHAT_ID = "42"

def order(items, **kw):
    appmod._rl_hits.clear()
    return c.post("/api/price/order_request", json={"items": items, "contact": "@me <i>", "name": "Ян", **kw})

r = order([{"name": "дракон", "qty": 5, "unit_price": 1, "line_total": 1}], promo_code="OK")
j = r.json(); assert r.status_code == 200, r.text
assert j["grand_total"] == 2000 and j["discount"] == 200 and j["final_total"] == 1800, j     # опт 400×5, не 1 ₽ от клиента
assert fake.orders[0][:2] == ("С прайса: Дракон", 5) and fake.promo_used == ["OK"]
txt = sent[-1][1]; assert "&lt;i&gt;" in txt and "<i>" not in txt.replace("<i>(опт)</i>", "")
r = order([{"name": "Кот <b>", "qty": 1}]); assert "&lt;b&gt;" in sent[-1][1] and r.json()["grand_total"] == 100
n = len(fake.orders)
assert order([{"name": "Нет такого", "qty": 1}]).status_code == 400
assert order([{"name": "Дракон", "qty": 0}]).status_code == 400
assert order([{"name": "Дракон", "qty": 10**6}]).status_code == 400
assert order([{"name": "Дракон", "qty": 1}] * 51).status_code == 400
assert len(fake.orders) == n, "заказы не должны создаваться при отказе"
# нет получателя -> отказ ДО создания заказов
appmod.PRICE_ORDER_CHAT_ID = ""; saved = list(appmod.ALLOWED_USERS); appmod.ALLOWED_USERS[:] = []
assert order([{"name": "Дракон", "qty": 1}]).status_code == 500 and len(fake.orders) == n
appmod.ALLOWED_USERS[:] = saved
# rate limit
appmod._rl_hits.clear()
codes = [c.post("/api/price/order_request", json={"items": [{"name": "Дракон", "qty": 1}], "contact": "a"}).status_code for _ in range(7)]
assert codes[-1] == 429, codes

# ---- share: JSON-LD не закрывает <script> ----
class FakeSM2(FakeSM):
    def get_price_item_by_row(s, r): return {"row_index": r, "name": "A</script><script>alert(1)", "description": "d", "photo": "", "retail": "300", "wholesale": "", "wholesale_from": "", "category": "x"}
appmod.sheet_manager = FakeSM2()
page = c.get("/share/3").text
block = page.split('application/ld+json">')[1].split("</script>")[0]
assert block.strip().endswith("}") and json.loads(block)["name"].startswith("A"), block   # данные не закрыли <script>
assert "<script>alert" not in page

# ---- прайс: постоянные ID ----
H8 = ["Название", "Описание", "Фото (URL)", "Розница", "Опт", "Опт от (шт)", "Категория"]
class PriceWS(WS):
    id = 99
    def col_values(s, c): return [(r[c - 1] if len(r) >= c else "") for r in s.rows]
    def row_values(s, r): return list(s.rows[r - 1])
    def update(s, rng, vals, **kw):
        r0 = col(rng.split(":")[0])[0]
        for i, v in enumerate(vals):
            while len(s.rows) < r0 + i: s.rows.append([])
            row = s.rows[r0 + i - 1]
            row[:len(v)] = [str(x) for x in v]   # как в Sheets: затрагиваем только указанные столбцы
    def update_cell(s, r, c, v):
        while len(s.rows[r - 1]) < c: s.rows[r - 1].append("")
        s.rows[r - 1][c - 1] = str(v)
pw = PriceWS([H8, ["A", "", "", "1", "", "", "К"], ["B", "", "", "2", "", "", "К"], ["", "", "", "", "", "", ""], ["C", "", "", "3", "", "", "К"]])
class Sheet:  # spreadsheet с batch_update(deleteDimension)
    def batch_update(s, body):
        for rq in sorted(body["requests"], key=lambda q: -q["deleteDimension"]["range"]["startIndex"]):
            del pw.rows[rq["deleteDimension"]["range"]["startIndex"]]
sm = object.__new__(Real); sm._initialized = True; sm._cache = {}
sm.sheet_price, sm.sheet, sm.sheet_log = pw, Sheet(), WS([])
settings = {}
sm.get_setting = lambda k, d="": settings.get(k, d)
sm.set_setting = lambda k, v: settings.__setitem__(k, str(v)) or True
sm._migrate_price_ids()
assert pw.rows[0][7] == "ID" and [r[7] if len(r) > 7 else "" for r in pw.rows[1:]] == ["2", "3", "", "5"]   # ID = номер строки: старые ссылки живы
items = {i["name"]: i["row_index"] for i in sm.get_price_items()}
assert items == {"A": 2, "B": 3, "C": 5}
sm._migrate_price_ids(); assert [r[7] if len(r) > 7 else "" for r in pw.rows[1:]] == ["2", "3", "", "5"]   # идемпотентно
assert sm.add_price_item("D", retail="4") and sm.get_price_item_by_row(6)["name"] == "D"
assert sm.delete_price_item(2)                                     # удалили A — строки сдвинулись
assert sm.get_price_item_by_row(3)["name"] == "B" and sm.get_price_item_by_row(5)["name"] == "C"   # ID прежние
assert sm.get_price_item_by_row(2) is None
assert sm.update_price_item_fields(5, {"retail": "30", "name": "C2"})
assert sm.get_price_item_by_row(5)["name"] == "C2" and sm.get_price_item_by_row(5)["retail"] == "30"
assert sm.set_category_for_rows([3, 5, 999], "Новая") == 2 and sm.get_price_item_by_row(3)["category"] == "Новая"
assert sm.delete_price_items([3, 5, 999]) == 2 and [i["name"] for i in sm.get_price_items()] == ["D"]
assert sm.add_price_item("E") and sm.get_price_item_by_row(7)["name"] == "E"     # ID 6 (D), 7 — не переиспользуются
print("security & price OK")
