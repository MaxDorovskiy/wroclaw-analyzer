# -*- coding: utf-8 -*-
"""Почему у объявления такая скидка — по шагам, тем же кодом, что и расчёт.

    .venv/bin/python scripts/explain_deal.py <listing_id>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import analytics  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Listing  # noqa: E402


def main():
    lid = int(sys.argv[1])
    db = SessionLocal()
    l = db.get(Listing, lid)
    if l is None:
        print(u"нет такого объявления")
        return
    print(u"%s | %s | %s zł, %s м², %s к., %s/%s, %s, %s" % (
        l.source, l.title_pl, l.price_pln, l.area, l.rooms, l.osiedle_override or l.osiedle, l.district,
        l.market, l.condition_override or l.condition))
    res = analytics.recompute_deal_scores(db, explain_id=lid)
    ex = res.get("explain")
    if not ex:
        print(u"объявление не прошло санитарные пороги (цена/площадь) — без оценки")
        return
    print(u"цена м² с поправкой на площадь: %.0f (полоса %s, коэф. %.3f)" % (ex["adj"], ex["band"], ex["coef"]))
    for s in ex["steps"]:
        print(u"  %-15s n=%-4d %s  %s" % (s["level"], s["n"], u"OK" if s["ok"] else u"мало",
                                          json.dumps(s["key"], ensure_ascii=False)))
    if ex["found"]:
        f = ex["found"]
        print(u"база: %s, медиана %.0f zł/м² по %d объявлениям -> скидка %.1f%%" % (
            f["level"], f["median"], f["n"], (1 - ex["adj"] / f["median"]) * 100))
    else:
        print(u"пула не набралось ни на одном уровне")


if __name__ == "__main__":
    main()
