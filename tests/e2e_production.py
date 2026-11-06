"""Ручной e2e (нужен Playwright + chromium): вход на /production, таблица, выход, протухший токен.
Запуск: python tests/e2e_production.py"""
import os, re, sys, time, threading
from harness import *   # noqa
import uvicorn
sys.path.append("/usr/local/lib/python3.13/site-packages")
from playwright.sync_api import sync_playwright

class Fake:
    def __init__(s): s.ship = {}
    def get_active_orders(s): return [["1", "Дракон", "3", "1", "2026-11-10", "", "Нет", "A"]]
    def get_price_items(s): return []
    def get_shipments(s): return s.ship
    def replace_active_orders(s, items, dl, cust, clr): s.replaced = (items, dl, cust, clr); return {'archived': 1, 'created': [2], 'shipments_cleared': 0}
    def set_shipment(s, p, l, q): s.ship[(p.lower(), l.lower())] = q; return True
appmod.sheet_manager = Fake()
srv = uvicorn.Server(uvicorn.Config(appmod.app, host="127.0.0.1", port=8766, log_level="error"))
threading.Thread(target=srv.run, daemon=True).start(); time.sleep(1.5)

with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page()
    errs = []; p.on("pageerror", lambda e: errs.append(str(e)))
    p.route(re.compile(r"cdn\.tailwindcss|cdn\.jsdelivr"), lambda r: r.abort())
    p.add_init_script("document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');s.textContent='.hidden{display:none!important}';document.head.appendChild(s)})")
    p.goto("http://127.0.0.1:8766/production")
    p.wait_for_selector("#login-overlay", state="visible")
    assert p.locator("tbody tr").count() == 0
    p.fill("#login-pwd", "nope"); p.click("#login-btn"); p.wait_for_function("document.getElementById('login-msg').textContent.includes('Неверный')")
    p.fill("#login-pwd", "secret"); p.click("#login-btn"); p.wait_for_selector("tbody tr"); assert p.locator("#login-overlay").is_hidden()
    tok = p.evaluate("localStorage.getItem('adminToken')"); assert tok and tok != "secret" and p.evaluate("localStorage.getItem('priceAdminToken')") is None
    p.fill("input.ship-input >> nth=0", "2"); p.keyboard.press("Tab"); time.sleep(0.5)
    assert appmod.sheet_manager.ship, "отправка не записалась"
    p.reload(); p.wait_for_selector("tbody tr"); assert p.locator("#login-overlay").is_hidden()   # токен пережил перезагрузку
    p.evaluate("localStorage.setItem('adminToken','1.bad')"); p.reload(); p.wait_for_selector("#login-overlay", state="visible")   # битый токен -> снова вход
    p.fill("#login-pwd", "secret"); p.click("#login-btn"); p.wait_for_selector("tbody tr")
    p.click("#auth-btn"); p.wait_for_selector("#login-overlay", state="visible"); assert p.locator("tbody tr").count() == 0   # выход
    print("page errors:", [e for e in errs if "tailwind" not in e] or "none")
    b.close()
print("e2e OK")
