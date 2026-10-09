# -*- coding: utf-8 -*-
"""Проверка БОЕВОГО сайта браузером: каждый раздел открывается, в консоли пусто.

`ui_check.py` гоняет фронтенд на фикстурах — он ловит поломки вёрстки, но не
видит того, что приходит из настоящей базы: пустые поля, длинные тексты,
неожиданные значения. Этот скрипт открывает работающий сервер и смотрит
каждый раздел живьём.

Пароль берётся из окружения (`WRO_WEB_USER`/`WRO_WEB_PASS`, как их задаёт
`deploy/windows/env.ps1`) и нигде не печатается.

    python scripts/live_check.py [адрес] [папка-для-снимков]
    код возврата: 0 — всё открылось без ошибок, 1 — есть проблемы
"""
from __future__ import print_function

import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRO_BASE") or "http://127.0.0.1:8020"
OUT = Path(tempfile.gettempdir()) / "wro-live"

# (раздел, что должно появиться на экране)
PAGES = [
    # ждём именно строку списка, а не карточку: карточки рисуются сразу,
    # а списки приходят тремя отдельными запросами — именно их и проверяем
    ("home", ".dash-list li"),
    ("catalog", "table.grid tbody tr.clickable"),
    ("deals", "table.grid tbody tr"),
    ("rent", "table.grid tbody tr.clickable"),
    ("favorites", ".panel"),
    ("contacts", "table.grid tbody tr"),
    ("stats", "table.grid tbody tr"),
    ("runs", "table.grid tbody tr"),
    ("journal", "table.grid tbody tr"),
    ("settings", ".form-grid input"),
]
# Шум, который к нам не относится: расширения браузера, картинки площадок
# (CDN режет горячие ссылки), favicon при открытии по file://
SKIP = ("favicon", "apollo.olxcdn", "otodom", "olxcdn", "ERR_BLOCKED_BY_ORB",
        "net::ERR_NAME_NOT_RESOLVED")


def main(base=BASE, out_dir=OUT):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    user = os.environ.get("WRO_WEB_USER") or "admin"
    pwd = os.environ.get("WRO_WEB_PASS") or ""
    problems = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  http_credentials={"username": user, "password": pwd})
        page = ctx.new_page()
        seen = []
        page.on("console", lambda m: seen.append((m.type, m.text)) if m.type == "error" else None)
        page.on("pageerror", lambda e: seen.append(("pageerror", str(e))))
        page.goto(base + "/", wait_until="load", timeout=60000)
        for name, selector in PAGES:
            before = len(seen)
            page.evaluate("location.hash = '#/%s'" % name)
            try:
                page.wait_for_selector(selector, timeout=30000)
            except Exception as e:  # noqa: BLE001
                problems.append(u"%s: не дождались «%s» (%s)" % (name, selector, str(e)[:60]))
            page.wait_for_timeout(900)
            shot = out / (name + ".png")
            page.screenshot(path=str(shot), full_page=False)
            fresh = [t for t in seen[before:] if not any(s in t[1] for s in SKIP)]
            for kind, text in fresh:
                problems.append(u"%s: %s %s" % (name, kind, text[:140]))
            print(u"  %-10s %s" % (name, shot))
        # карточка: самое дорогое объявление — там больше всего полей
        page.evaluate("location.hash = '#/catalog?sort=price&order=desc'")
        page.wait_for_selector("table.grid tbody tr.clickable", timeout=30000)
        page.click("table.grid tbody tr.clickable")
        try:
            page.wait_for_selector(".modal table.chars", timeout=30000)
            page.screenshot(path=str(out / "card.png"), full_page=False)
            print(u"  %-10s %s" % ("card", out / "card.png"))
        except Exception as e:  # noqa: BLE001
            problems.append(u"карточка не открылась: %s" % str(e)[:80])
        browser.close()
    if problems:
        print(u"\nПРОБЛЕМЫ:")
        for x in problems:
            print(u"  " + x)
        return 1
    print(u"\nOK: все разделы открылись, ошибок в консоли нет")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    sys.exit(main(args[0] if args else BASE, args[1] if len(args) > 1 else OUT))
