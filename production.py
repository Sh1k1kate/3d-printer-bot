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


# ---------------------------------------------------------------------------
# Вставка текста: «ВДНХ / 1. Медведь 2 шт / ...» -> отправки (+ напечатанное)
# ---------------------------------------------------------------------------
import re
from difflib import SequenceMatcher

_QUOTES = str.maketrans({c: " " for c in "«»\"'“”„‟`’‘()[]{}.,;:!?—–-_/\\"})
_QTY_RE = re.compile(
    r"^(?P<name>.*?)[\s\-–—:]*(?:(?:[x×х]\s*)?(?P<qty>\d+)\s*(?:шт\.?|штук[аи]?)?)?\s*$",
    re.IGNORECASE,
)
_NUM_PREFIX_RE = re.compile(r"^\s*\d+\s*[.)]\s+")


def name_key(s):
    """Для сравнения названий: без регистра, ё=е, без кавычек и знаков, одинарные пробелы."""
    s = (s or "").lower().replace("ё", "е").translate(_QUOTES)
    return " ".join(s.split())


def parse_shipment_text(text, locations):
    """Разбирает вставленный текст на строки вида (точка, название, количество).

    Заголовок секции — строка, совпадающая с названием точки («ВДНХ», «остров:»).
    Строка позиции: необязательный номер «12.», название, необязательное количество
    («2 шт», «x2», просто «2»). Без количества считаем 1 шт.
    Если заголовка ещё не было, location = None (страница подставит точку по умолчанию).
    """
    loc_by_key = {name_key(l): l for l in locations}
    entries, location = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        key = name_key(line)
        if key in loc_by_key:
            location = loc_by_key[key]
            continue
        body = _NUM_PREFIX_RE.sub("", line)
        m = _QTY_RE.match(body)
        name = (m.group("name") if m else body).strip(" \t-–—:")
        qty = int(m.group("qty")) if m and m.group("qty") else 1
        if not name:                       # строка была просто числом/мусором
            name, qty = body.strip(), 1
        if not name_key(name):
            continue
        entries.append({"line": line, "location": location, "name": name, "qty": qty})
    return entries


def _tok_sim(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _all_tokens_match(src, dst, thr=0.8):
    """Каждое слово из src находит похожее слово в dst («кликеры» ~ «кликер»)."""
    return bool(src) and all(max((_tok_sim(t, u) for u in dst), default=0) >= thr for t in src)


def match_name(query, candidates):
    """Ищет в candidates (названия позиций) то, что соответствует названию из текста.

    Возвращает (название | None, уверенность, топ-3 кандидата по сходству), где уверенность:
      "exact"   — совпало после нормализации (регистр, кавычки, ё);
      "near"    — те же слова с поправкой на окончания («Кликеры» ~ «Кликер»);
      "partial" — одно название входит в другое по словам («Лола» ~ «Лола «Острые козырьки»»);
      "none"    — похожего нет (одинаковые «хвосты» вроде «Острые козырьки» не считаются).
    """
    q = name_key(query)
    qt = q.split()
    ranked = []
    for c in candidates:
        k = name_key(c)
        if not k or not q:
            continue
        kt = k.split()
        ratio = _tok_sim(q, k)
        if k == q:
            rank = 3
        elif len(qt) == len(kt) and _all_tokens_match(qt, kt) and _all_tokens_match(kt, qt):
            rank = 2
        elif len(qt) != len(kt) and (_all_tokens_match(qt, kt) or _all_tokens_match(kt, qt)):
            rank = 1
        else:
            rank = 0
        ranked.append((rank, ratio, c))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2].lower()))
    top = [c for _, _, c in sorted(ranked, key=lambda x: (-x[1], x[2].lower()))[:3]]
    if ranked and ranked[0][0] > 0:
        return ranked[0][2], {3: "exact", 2: "near", 1: "partial"}[ranked[0][0]], top
    return None, "none", top


def distribute_printed(orders, qty):
    """Раскладывает qty напечатанных штук по заказам одной позиции.

    orders — [{id, row, ordered, printed, deadline}]. Сначала закрываем заказы с ближайшим
    сроком; в один заказ не кладём больше, чем в нём заказано (как и в боте).
    Возвращает (изменения [{id,row,printed(новое),added}], остаток, не поместившийся в заказы).
    """
    left = max(0, int(qty))
    changes = []
    for o in sorted(orders, key=lambda o: (o.get("deadline") or "9999-99-99", _to_int(o["id"]))):
        if left <= 0:
            break
        room = max(0, o["ordered"] - o["printed"])
        add = min(room, left)
        if add:
            changes.append({"id": o["id"], "row": o["row"], "printed": o["printed"] + add, "added": add})
            left -= add
    return changes, left


def plan_set_ordered(orders, new_total):
    """Меняет суммарное «заказано» по позиции, раскладывая разницу по её заказам.

    orders — [{id, row, ordered, printed, deadline}] активные заказы позиции.
    Увеличение целиком уходит в заказ с самым поздним сроком. Уменьшение снимается с заказов
    с конца (самый поздний срок первым), но в заказе не опускается ниже уже напечатанного —
    как и в боте, где напечатанное не может быть больше заказанного.
    Возвращает список изменений [{id, row, ordered(новое)[, close]}]; close=True — заказ обнулился и
    его нужно пометить выполненным. ValueError — если так сделать нельзя.
    """
    new_total = int(new_total)
    if not orders:
        raise ValueError("У позиции нет активных заказов")
    if new_total < 1:
        raise ValueError("Заказано должно быть не меньше 1 (чтобы убрать позицию, закройте её)")
    printed_sum = sum(max(0, o["printed"]) for o in orders)
    if new_total < printed_sum:
        raise ValueError(f"Нельзя поставить меньше, чем уже напечатано ({printed_sum})")
    ordered = sorted(orders, key=lambda o: (o.get("deadline") or "9999-99-99", _to_int(o["id"])))
    delta = new_total - sum(o["ordered"] for o in ordered)
    if delta == 0:
        return []
    if delta > 0:
        last = ordered[-1]
        return [{"id": last["id"], "row": last["row"], "ordered": last["ordered"] + delta}]
    left, changes = -delta, []
    for o in reversed(ordered):
        if left <= 0:
            break
        take = min(left, max(0, o["ordered"] - max(0, o["printed"])))
        if take:
            new = o["ordered"] - take
            # заказ, обнулившийся при уменьшении, закрываем — нулевых активных заказов не оставляем
            changes.append({"id": o["id"], "row": o["row"], "ordered": new, "close": new == 0})
            left -= take
    return changes
