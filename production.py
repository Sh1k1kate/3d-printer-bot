"""Сводка для страницы /production: что надо допечатать и куда что отправлено.

Данные берутся из заказов (лист «Заказы»), прайса (картинки) и отправок (лист «Отправки»).
Модуль не ходит в Google Sheets сам — получает уже прочитанные данные, поэтому его легко тестировать.
"""

PRICE_PREFIX = "с прайса:"


def normalize_position(position):
    """'С прайса: Дракон' -> 'Дракон'. Остальные позиции (модели, 'Набор: ...') не трогаем."""
    p = (position or "").strip()
    if p.lower().startswith(PRICE_PREFIX):
        p = p[len(PRICE_PREFIX):].strip()
    return p


def _to_int(value):
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (ValueError, TypeError):
        return 0


def build_production_rows(orders, price_items, shipments, locations):
    """Склеивает активные заказы по позиции и считает остаток к печати.

    orders     — строки листа «Заказы» (как отдаёт SheetManager.get_active_orders)
    price_items — список из SheetManager.get_price_items (нужны name и photo)
    shipments  — {(позиция_lower, точка_lower): количество}
    locations  — список названий точек, например ['ВДНХ', 'Остров', 'Аэропорт']
    """
    price_by_name = {}
    for it in price_items:
        key = (it.get("name") or "").strip().lower()
        if key and key not in price_by_name:
            price_by_name[key] = it

    groups = {}
    for o in orders:
        if len(o) < 4:
            continue
        name = normalize_position(o[1])
        if not name:
            continue
        key = name.lower()
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"name": name, "ordered": 0, "printed": 0, "order_ids": [], "deadline": ""}
        g["ordered"] += _to_int(o[2])
        g["printed"] += _to_int(o[3])
        g["order_ids"].append(str(o[0]))
        deadline = (o[4] if len(o) > 4 else "").strip()
        if deadline and (not g["deadline"] or deadline < g["deadline"]):
            g["deadline"] = deadline

    rows = []
    for key, g in groups.items():
        item = price_by_name.get(key) or {}
        sent = {loc: _to_int(shipments.get((key, loc.lower()), 0)) for loc in locations}
        rows.append({
            "name": g["name"],
            "photo": item.get("photo", "") or "",
            "ordered": g["ordered"],
            "printed": g["printed"],
            "shipped": sent,
            "shipped_total": sum(sent.values()),
            "remaining": max(0, g["ordered"] - g["printed"]),
            "deadline": g["deadline"],
            "order_ids": g["order_ids"],
        })

    # сначала то, что надо допечатать, внутри — по ближайшему сроку
    rows.sort(key=lambda r: (r["remaining"] == 0, r["deadline"] or "9999-99-99", r["name"].lower()))
    return rows
