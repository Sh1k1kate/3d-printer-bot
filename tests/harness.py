"""Общая заглушка Google Sheets для проверочных скриптов."""
import os, sys, re, threading, time, types, datetime as _dt
os.environ.update(BOT_TOKEN="123456:TEST-token", ADMIN_PASSWORD="secret")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)

# --- заглушка только для хендлеров бота (создают SheetManager при импорте) ---
import google_sheets as real
Real = real.SheetManager
stub = types.ModuleType("google_sheets"); 
class _SM:
    def __init__(self,*a,**k): pass
    def __getattr__(self,n): return lambda *a,**k: None
stub.SheetManager = _SM; stub.moscow_now = real.moscow_now
sys.modules["google_sheets"] = stub
import app as appmod

def col(a1):
    m = re.match(r"([A-Z])(\d+)", a1); return int(m.group(2)), ord(m.group(1)) - 64
class WS:
    def __init__(s, rows): s.rows=[list(r) for r in rows]; s.calls=[]
    def get_all_values(s): return [list(r) for r in s.rows]
    def batch_update(s, data, **kw):
        s.calls.append(("batch_update", len(data)))
        for d in data:
            r,c = col(d["range"])
            while len(s.rows)<r: s.rows.append([])
            while len(s.rows[r-1])<c: s.rows[r-1].append("")
            s.rows[r-1][c-1]=str(d["values"][0][0])
    def append_rows(s, rows, **kw): s.calls.append(("append_rows", len(rows))); s.rows += [[str(x) for x in r] for r in rows]
    def append_row(s,row,**kw): s.rows.append(row)

H=["№","Позиция","Заказано","Напечатано","Срок","Изм","Выполнен","Заказчик"]
orders = WS([H,
 ["1","Медведь милашка","3","0","2026-11-10","","Нет","A"],
 ["2","С прайса: Лама","1","0","2026-11-03","","Нет","B"],
 ["3","Кликер","12","0","2026-11-05","","Нет","C"],
 ["4","Брелок","10","2","2026-11-06","","Нет","D"],
 ["5","Лола «Острые Козырьки»","2","0","2026-11-04","","Нет","E"],
 ["6","Бэтмен","1","0","2026-11-02","","Нет","F"],
 ["7","Бэтмен","1","0","2026-11-09","","Нет","G"],
 ["8","Росомаха","4","0","2026-11-12","","Нет","H"],
])
ship = WS([["Позиция","Точка","Отправлено"], ["Бэтмен","Остров","1"]])
price = WS([["Название","Описание","Фото","Розница","Опт","Опт от","Категория","ID"]])
sm = object.__new__(Real); sm._initialized=True
sm.sheet_orders, sm.sheet_shipments, sm.sheet_price, sm.sheet_log = orders, ship, price, WS([]); sm._cache={}
appmod.sheet_manager = sm


def appmod_H():
    return {"X-Admin-Token": appmod.make_admin_token()}
