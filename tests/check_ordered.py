import os
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from production import plan_set_ordered as P
O = lambda i, row, o, p, d: {"id": i, "row": row, "ordered": o, "printed": p, "deadline": d}
one = [O("1", 2, 1, 0, "2026-11-01")]
assert P(one, 2) == [{"id": "1", "row": 2, "ordered": 2}]                      # 1 -> 2
assert P(one, 1) == []                                                          # без изменений
multi = [O("5", 6, 4, 1, "2026-11-10"), O("3", 4, 3, 3, "2026-11-02"), O("4", 5, 2, 0, "2026-11-05")]   # всего 9, напечатано 4
assert P(multi, 12) == [{"id": "5", "row": 6, "ordered": 7}]                    # рост — в заказ с самым поздним сроком
# уменьшение: с конца — №5 (4→1, не ниже напечатанного 1), потом №4 (2→1)
assert P(multi, 5) == [{"id": "5", "row": 6, "ordered": 1, "close": False}, {"id": "4", "row": 5, "ordered": 1, "close": False}], P(multi, 5)
# до напечатанного (4): №5 4→1, №4 2→0 — обнулившийся заказ закрывается
assert P(multi, 4) == [{"id": "5", "row": 6, "ordered": 1, "close": False}, {"id": "4", "row": 5, "ordered": 0, "close": True}], P(multi, 4)
for bad, msg in [(3, "напечатано"), (0, "не меньше 1"), (-2, "не меньше 1")]:
    try: P(multi, bad); assert False, bad
    except ValueError as e: assert msg in str(e), (bad, str(e))
try: P([], 3); assert False
except ValueError as e: assert "нет активных" in str(e)
# итог после применения совпадает с запрошенным
def apply(orders, ch):
    m = {c["id"]: c["ordered"] for c in ch}; return sum(m.get(o["id"], o["ordered"]) for o in orders)
for t in (4, 5, 6, 9, 10, 30): assert apply(multi, P(multi, t)) == t, t
print("plan_set_ordered OK")
