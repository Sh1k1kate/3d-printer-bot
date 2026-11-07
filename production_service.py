"""Общая логика допечатки/отправок для сайта (app.py) и Telegram-бота (handlers/production.py).

Функции синхронные и работают с SheetManager, поэтому в async-коде вызываются через run_in_threadpool.
"""
import os

from google_sheets import moscow_now
from production import build_production_rows, normalize_position

NO_ORDER_CUSTOMER = "Без заказа"   # заказчик у заказов, созданных автоматически для отправленного без заказа
MAX_POSITION_NAME = 100

# Можно поменять без правки кода: SHIPMENT_LOCATIONS="ВДНХ,Остров,Аэропорт,Новая точка"
SHIPMENT_LOCATIONS = [
    s.strip() for s in os.getenv("SHIPMENT_LOCATIONS", "ВДНХ,Остров,Аэропорт").split(",") if s.strip()
]


class ShipmentError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or []


def production_rows(sm, locations=None):
    return build_production_rows(sm.get_active_orders(), sm.get_price_items(), sm.get_shipments(),
                                 locations or SHIPMENT_LOCATIONS)


def canonical_location(value, locations=None):
    v = (value or "").strip().lower()
    return next((loc for loc in (locations or SHIPMENT_LOCATIONS) if loc.lower() == v), None)


def ensure_printed(sm, only=None, locations=None):
    """Отправленное = напечатанное: подтягивает «напечатано» до «отправлено», если оно меньше.

    Считаем по позиции в целом (сумма по активным заказам), поэтому уже учтённое напечатанное
    повторно не прибавляется. only — множество названий в нижнем регистре; None — все позиции.
    Возвращает {"added": {...}, "leftover": {...}} как add_printed_batch; leftover — отправлено больше заказанного.
    """
    need = {}
    for r in production_rows(sm, locations):
        key = r["name"].lower()
        if (only is None or key in only) and r["shipped_total"] > r["printed"]:
            need[key] = r["shipped_total"] - r["printed"]
    if not need:
        return {"added": {}, "leftover": {}}
    return sm.add_printed_batch(need)


def apply_shipments(sm, items, add_printed=True, locations=None):
    """Прибавляет количества к «отправлено» точки; отправленное считается напечатанным (ensure_printed).
    add_printed оставлен для совместимости со старыми клиентами и игнорируется.

    items — [{"position", "location", "qty", "create"}]; create=True создаёт заказ «Без заказа» для
    позиции, которой нет среди активных. При ошибках в данных ничего не пишет и бросает ShipmentError.
    """
    locations = locations or SHIPMENT_LOCATIONS
    rows = production_rows(sm, locations)
    known = {r["name"].lower(): r["name"] for r in rows}

    out, errors, to_create = [], [], {}
    for it in items:
        loc = canonical_location(it["location"], locations)
        name = normalize_position(it["position"])
        pos = known.get(name.lower())
        if not loc:
            errors.append(f"«{it['position']}»: неизвестная точка «{it['location']}»")
        elif it["qty"] <= 0:
            errors.append(f"«{it['position']}»: количество должно быть больше 0")
        elif pos:
            out.append((pos, loc, it["qty"]))
        elif it.get("create") and name and len(name) <= MAX_POSITION_NAME:
            c = to_create.setdefault(name.lower(), {"name": name, "qty": 0})
            c["qty"] += it["qty"]
            out.append((c["name"], loc, it["qty"]))
        else:
            errors.append(f"«{it['position']}»: нет среди активных заказов")
    if errors:
        raise ShipmentError("Есть ошибки, ничего не записано", errors)
    if not out:
        raise ShipmentError("Нечего записывать")

    result = {"status": "ok", "shipped": sum(q for _, _, q in out), "printed_added": 0, "leftover": {}, "created": []}
    if to_create:
        today = moscow_now().strftime("%Y-%m-%d")
        sm.add_orders_batch([
            (c["name"], c["qty"], c["qty"], today, NO_ORDER_CUSTOMER)
            for c in to_create.values()
        ])
        result["created"] = [c["name"] for c in to_create.values()]
    sm.add_shipments_batch(out)
    # позиции из созданных заказов уже напечатаны целиком; остальным «напечатано» подтягиваем до «отправлено»
    names = dict(known, **{k: c["name"] for k, c in to_create.items()})
    printed = ensure_printed(sm, only={pos.lower() for pos, _l, _q in out}, locations=locations)
    result["printed_added"] = sum(printed["added"].values()) + sum(c["qty"] for c in to_create.values())
    result["leftover"] = {names.get(k, k): v for k, v in printed["leftover"].items()}
    return result
