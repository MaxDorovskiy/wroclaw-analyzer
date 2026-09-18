#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка «фронтенд против НАСТОЯЩЕГО бэкенда» без запуска сервера.

ui_check.py кормит интерфейс фикстурами по контракту; но фронтенд и бэкенд
писались параллельно по одному документу, и разъехаться они могли в именах
полей. Здесь запросы страницы (file://frontend/dist) перехватываются
Playwright и отдаются FastAPI TestClient на синтетической базе
(scripts/demo_seed.py) — сервер как процесс не нужен, а ответы настоящие.

    .venv/bin/python scripts/ui_check_live.py [каталог_для_скриншотов]
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="wro-live-"))
os.environ["WRO_DB"] = str(TMP / "demo.db")
os.environ["WRO_DATA"] = str(TMP)
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ.pop("WRO_WEB_PASS", None)
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from app.db import SessionLocal, ensure_columns  # noqa: E402
from app.main import app  # noqa: E402
from demo_seed import seed  # noqa: E402
from ui_check import API_BASE, CORS, DIST, PLACEHOLDER_SVG, VIEWPORT, launch_chromium  # noqa: E402

DEFAULT_OUT = Path(os.environ.get("UI_OUT") or (TMP / "shots"))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    out.mkdir(parents=True, exist_ok=True)
    ensure_columns()
    db = SessionLocal()
    print(u"демо-данные:", seed(db, n_sale=500, n_rent=200, rnd=5))
    db.close()
    errors, calls = [], []
    with TestClient(app) as client:
        first_id = client.get("/api/listings?per_page=1&sort=discount").json()["items"][0]["id"]

        def handle(route, request):
            url = urlparse(request.url)
            if not url.path.startswith("/api/"):
                route.fulfill(status=200, content_type="image/svg+xml", body=PLACEHOLDER_SVG, headers=CORS)
                return
            target = url.path + ("?" + url.query if url.query else "")
            if request.method == "POST":
                body = request.post_data
                r = client.post(target, content=body or None,
                                headers={"content-type": "application/json"} if body else None)
            else:
                r = client.get(target)
            calls.append((request.method, target, r.status_code))
            if r.status_code >= 400:
                errors.append(u"%s %s -> %d %s" % (request.method, target, r.status_code, r.text[:200]))
            route.fulfill(status=r.status_code, content_type=r.headers.get("content-type", "application/json"),
                          body=r.content, headers=CORS)

        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport=VIEWPORT)
            page.add_init_script("window.__API_BASE__ = %s" % json.dumps(API_BASE))
            page.route(re.compile(r"^https?://"), handle)
            page.on("pageerror", lambda e: errors.append(u"pageerror: %s" % e))
            page.on("console", lambda m: errors.append(u"console.error: %s" % m.text) if m.type == "error" else None)

            def go(hash_, wait_text, name):
                page.evaluate("location.hash = %s" % json.dumps(hash_))
                page.wait_for_selector("text=%s" % wait_text, timeout=20000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(400)
                page.screenshot(path=str(out / (name + ".png")), full_page=True)
                print(u"  скриншот %s" % (out / (name + ".png")))

            page.goto(DIST.as_uri() + "#/catalog", wait_until="load")
            page.wait_for_selector("text=Знайдено", timeout=20000)
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(out / "live_catalog.png"), full_page=True)
            print(u"  скриншот %s" % (out / "live_catalog.png"))
            go("#/catalog?id=%d" % first_id, u"Характеристики", "live_card")
            go("#/deals", u"Знайдено", "live_deals")
            go("#/rent", u"Знайдено", "live_rent")
            go("#/contacts", u"Контакти", "live_contacts")
            go("#/stats", u"Статистика", "live_stats")
            go("#/runs", u"Прогони", "live_runs")
            go("#/settings", u"Налаштування", "live_settings")
            browser.close()
    print(u"запросов к API: %d, разных ручек: %d" % (len(calls), len(set(c[1].split('?')[0] for c in calls))))
    if errors:
        print(u"ОШИБКИ:")
        for e in errors:
            print(u"  " + e)
        return 1
    print(u"OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
