"""Ручной e2e для /tracker (Playwright). Chart.js блокируем — проверяем вход, вкладки и отсутствие запросов к принтерам."""
import os, re, sys, time, threading
from harness import *   # noqa
import uvicorn
sys.path.append("/usr/local/lib/python3.13/site-packages")
from playwright.sync_api import sync_playwright

class Fake:
    def get_user_orders(s): return [["1","Дракон","3","1","2099-11-10","","Нет","A"],["2","Кот","2","2","2026-11-01","","Да","B"],["3","Лис","1","0","2099-11-10","","Нет","A"]]
    def get_active_tasks(s): return []
appmod.sheet_manager = Fake()
srv = uvicorn.Server(uvicorn.Config(appmod.app, host="127.0.0.1", port=8767, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start(); time.sleep(1.5)
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page()
    errs, reqs = [], []; p.on("pageerror", lambda e: errs.append(str(e))); p.on("request", lambda r: reqs.append(r.url))
    p.route(re.compile(r"cdn\.tailwindcss|cdn\.jsdelivr"), lambda r: r.abort())
    p.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='.hidden{display:none!important}';document.head.appendChild(s)})")
    p.goto("http://127.0.0.1:8767/tracker"); p.wait_for_selector("#login-overlay", state="visible")
    p.fill("#login-password", "secret") if p.locator("#login-password").count() else p.fill("input[type=password]", "secret")
    p.keyboard.press("Enter"); p.wait_for_selector("#tab-orders.active tbody tr", state="attached", timeout=5000)
    assert p.locator("[data-tab=printers]").count() == 0 and p.locator("#tab-printers").count() == 0
    # группировка
    def headers(): return [t.strip().split("\n")[0][:40] for t in p.locator("#orders-table-body tr.bg-blue-50, #orders-table-body tr.bg-gray-100").all_inner_texts()]
    h = headers(); assert len(h) == 2 and h[0].startswith("📦") and "№1, №3" in " ".join(h), h   # по умолчанию: заказ → позиции
    p.select_option("#group-by", "none"); assert not headers()
    p.select_option("#group-by", "customer"); h = headers(); assert len(h) == 2 and h[0].startswith("A") and h[1].startswith("B"), h
    p.select_option("#group-by", "deadline"); h = headers(); assert any(x.startswith("Выполнено") for x in h) and any(x.startswith("Просрочено") or x.startswith("Позже") or x.startswith("На этой") for x in h), h
    p.select_option("#group-by", "customer_deadline"); assert len(headers()) >= 3
    p.reload(); p.wait_for_selector("#tab-orders.active tbody tr", state="attached"); assert p.input_value("#group-by") == "customer_deadline" and headers()   # выбор запомнился
    p.select_option("#group-by", "none"); assert not headers() and p.locator("#orders-table-body tr").count() == 3
    p.click("[data-tab=tasks]"); p.click("[data-tab=infographics]"); time.sleep(1)
    assert not any("/api/printers" in u for u in reqs), "принтеры больше не запрашиваются"
    print("page errors:", [e for e in errs if "tailwind" not in e and "Chart" not in e] or "none")
    b.close()
print("tracker e2e OK")
