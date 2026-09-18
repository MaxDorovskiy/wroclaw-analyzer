# -*- coding: utf-8 -*-
"""Повторный разбор сохранённого raw_json без нового скрапа — после правки
парсера или словаря (условие, осиедле, дополнения).

    .venv/bin/python scripts/reparse.py [--source otodom|olx] [--limit N]
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.console import utf8_stdio  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Listing, ScrapeRun  # noqa: E402
from app.scraper import PROTECTED, flush_unknown  # noqa: E402
from app.normalize import normalize  # noqa: E402
from app.sources import RawListing, get_source  # noqa: E402
from app.sources.otodom import outside_city  # noqa: E402


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=None)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    db = SessionLocal()
    q = db.query(Listing).filter(Listing.raw_json.isnot(None))
    if args.source:
        q = q.filter(Listing.source == args.source)
    if args.limit:
        q = q.limit(args.limit)
    n = changed = dropped = 0
    unknown = {}
    for row in q.yield_per(200):
        try:
            raw_obj = json.loads(row.raw_json)
        except ValueError:
            continue
        src = get_source(row.source)
        if row.source == "otodom" and "characteristics" in raw_obj:
            if outside_city(raw_obj.get("location")):
                raw = None
            else:
                raw = RawListing(source=row.source, source_id=row.source_id, url=row.url, offer_type=row.offer_type)
                raw = src.apply_ad(raw, raw_obj)
        else:
            raw = src.parse_item(raw_obj, row.offer_type)
        if raw is None:
            # адаптер такое больше не берёт (пригород, инвестиция целиком): прогоны эту
            # строку уже не увидят, а до снятия «не видели 3 дня» она портила бы пулы
            if row.is_active:
                row.is_active = False
                row.removed_at = datetime.utcnow()
                dropped += 1
            continue
        d = normalize(raw)
        unknown_places = d.pop("_unknown_places", [])
        for p in unknown_places:
            unknown[("place", p)] = unknown.get(("place", p), 0) + 1
        for k, v in d.items():
            if k in PROTECTED or k in ("raw_json", "first_seen", "last_seen"):
                continue
            if v is not None and getattr(row, k) != v:
                setattr(row, k, v)
                changed += 1
        n += 1
        if n % 500 == 0:
            db.commit()
            print(u"%d разобрано, %d полей изменено" % (n, changed))
    db.commit()
    flush_unknown(db, unknown)
    print(u"готово: %d разобрано, %d полей изменено, %d снято (адаптер их больше не берёт); "
          u"пересчитать: POST /api/recompute" % (n, changed, dropped))


if __name__ == "__main__":
    main()
