# -*- coding: utf-8 -*-
"""ПЕРВЫЙ запуск на новом месте: проверить, что адаптеры понимают площадки.

Делает по одному запросу выдачи к каждому источнику (и одну карточку Otodom),
печатает статус, число объявлений и три разобранные записи, сохраняет сырые
ответы в data/probe/. Если что-то разъехалось — по этим файлам чинятся имена
полей в backend/app/sources/*.py, а не гадается.

    .venv/bin/python scripts/probe_sources.py            # оба источника, продажа
    .venv/bin/python scripts/probe_sources.py --kind rent --source olx
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import PROBE_DIR  # noqa: E402
from app.console import utf8_stdio  # noqa: E402
from app.db import SessionLocal, ensure_columns  # noqa: E402
from app.fetcher import BlockedError, Fetcher  # noqa: E402
from app.normalize import normalize  # noqa: E402
from app.settings_store import get_settings  # noqa: E402
from app.sources import REGISTRY, get_source  # noqa: E402

KEYS = ("source_id", "url", "title_pl", "price_pln", "price_per_m2", "area", "rooms", "floor",
        "market", "building_type", "condition", "district", "osiedle", "seller_type", "seller_phone",
        "posted_at", "image_count")


def show(d):
    for k in KEYS:
        print("    %-14s %s" % (k, d.get(k)))
    if d.get("_unknown_places"):
        print(u"    ! незнакомые места: %s" % d["_unknown_places"])


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="sale", choices=["sale", "rent"])
    ap.add_argument("--source", default="all")
    ap.add_argument("--browser", action="store_true", help=u"сразу через Chromium (Playwright)")
    args = ap.parse_args()
    ensure_columns()
    db = SessionLocal()
    settings = get_settings(db)
    db.close()
    if args.browser:
        settings["fetch_mode"] = "browser"
    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    for name in REGISTRY:
        if args.source != "all" and name != args.source:
            continue
        print(u"\n=== %s / %s ===" % (name, args.kind))
        src = get_source(name)
        f = Fetcher(rpm=12, mode=settings.get("fetch_mode", "httpx"), dump_dir=PROBE_DIR)
        try:
            page, total, items = next(src.iter_pages(args.kind, f, 1, settings))
            print(u"страница %d из %s, объявлений на странице: %d" % (page, total, len(items)))
            if not items:
                ok = False
                print(u"! ноль объявлений: у OLX первым делом проверить id категории/города "
                      u"(настройки olx_category_*, olx_city_id), у Otodom — есть ли __NEXT_DATA__ в data/probe/")
            for raw in items[:3]:
                print(u"  --- %s" % raw.source_id)
                show(normalize(raw))
            if items and src.needs_details:
                print(u"  --- карточка %s" % items[0].url)
                raw = src.fetch_details(items[0], f)
                f.dump("%s_%s_ad.json" % (name, args.kind), json.dumps(raw.raw, ensure_ascii=False, indent=1))
                d = normalize(raw)
                show(d)
                print(u"    описание: %s..." % (d.get("description_pl") or u"")[:160].replace("\n", " "))
                print(u"    характеристик: %d, координаты: %s,%s" % (len(raw.characteristics), d.get("lat"), d.get("lon")))
            if name == "olx" and items:
                it = items[0].raw or {}
                print(u"    category.id=%s city=%s (ожидали %s / %s)" % (
                    (it.get("category") or {}).get("id"), (it.get("location") or {}).get("city", {}).get("name"),
                    settings.get("olx_category_%s" % args.kind), settings.get("olx_city_id")))
        except BlockedError as e:
            ok = False
            print(u"! БЛОК анти-бота: %s\n  попробуйте --browser, снизьте темп, подождите час; "
                  u"устойчиво — прокси (см. docs/RESEARCH.md §3)" % e)
        except Exception as e:  # noqa: BLE001
            ok = False
            print(u"! ошибка: %s" % e)
            traceback.print_exc()
        finally:
            print(u"запросов %s" % f.stats)
            f.close()
    print(u"\nсырые ответы: %s" % PROBE_DIR)
    print(u"ИТОГ: %s" % (u"источники отвечают, можно запускать прогон" if ok else u"есть проблемы, см. выше"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
