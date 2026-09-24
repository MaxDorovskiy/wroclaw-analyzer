# -*- coding: utf-8 -*-
"""Осиедле по координатам для объявлений, где источник его не дал (в основном OLX).

    .venv/Scripts/python.exe scripts/fill_osiedle.py --check   # проверка точности, БЕЗ записи
    .venv/Scripts/python.exe scripts/fill_osiedle.py           # проставить

Проверка честная: размеченную точку убираем из карты и спрашиваем карту о ней же
(leave-one-out). Так видно и долю правильных ответов, и долю отказов «не уверен».
"""
import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app import geo_knn  # noqa: E402
from app.console import utf8_stdio  # noqa: E402
from app.db import SessionLocal, ensure_columns  # noqa: E402
from app.models import Listing  # noqa: E402


def check(db, n=1500):
    rows = db.execute(select(Listing.id, Listing.lat, Listing.lon, Listing.osiedle).where(
        Listing.lat.isnot(None), Listing.lon.isnot(None), Listing.osiedle.isnot(None),
        Listing.osiedle_src.is_(None))).all()
    print(u"размеченных точек (Otodom): %d" % len(rows))
    sample = random.Random(42).sample(rows, min(n, len(rows)))
    hold = {r[0] for r in sample}
    t = time.time()
    omap = geo_knn.build_map(db, exclude_ids=hold)
    print(u"карта без отложенных: %d точек, собрана за %.1f с" % (omap.size, time.time() - t))
    ok = wrong = unsure = 0
    misses = {}
    t = time.time()
    for _, lat, lon, real in sample:
        got = omap.guess(lat, lon)
        if got is None:
            unsure += 1
        elif got == real:
            ok += 1
        else:
            wrong += 1
            misses[(real, got)] = misses.get((real, got), 0) + 1
    answered = ok + wrong
    print(u"\nпроверено %d точек за %.1f с" % (len(sample), time.time() - t))
    print(u"  ответили:      %5d (%.1f%%)" % (answered, 100.0 * answered / len(sample)))
    print(u"  из них верно:  %5d (%.1f%% от ответов)" % (ok, 100.0 * ok / max(1, answered)))
    print(u"  ошиблись:      %5d (%.1f%% от ответов)" % (wrong, 100.0 * wrong / max(1, answered)))
    print(u"  «не уверен»:   %5d (%.1f%%)" % (unsure, 100.0 * unsure / len(sample)))
    if misses:
        print(u"\n  где путается (настоящее -> ответ):")
        for (a, b), c in sorted(misses.items(), key=lambda kv: -kv[1])[:8]:
            print(u"    %-38s -> %-30s %d" % (a, b, c))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help=u"только проверка точности")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    utf8_stdio()
    ensure_columns()
    db = SessionLocal()
    try:
        if args.check:
            check(db)
            return
        before = db.execute(select(Listing.id).where(
            Listing.is_active.is_(True), Listing.osiedle.is_(None))).all()
        print(u"активных без осиедле до: %d" % len(before))
        t = time.time()
        res = geo_knn.fill_missing(db, args.limit or None)
        after = db.execute(select(Listing.id).where(
            Listing.is_active.is_(True), Listing.osiedle.is_(None))).all()
        print(u"карта: %d точек; проставлено %d, «не уверены» %d; за %.0f с" % (
            res["map_points"], res["filled"], res["unsure"], time.time() - t))
        print(u"активных без осиедле стало: %d" % len(after))
    finally:
        db.close()


if __name__ == "__main__":
    main()
