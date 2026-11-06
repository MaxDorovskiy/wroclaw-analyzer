#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Убрать из аналитики строки-фантомы Otodom, собранные до правки адаптера.

Последний элемент каждой страницы выдачи — служебная копия первого объявления
(дата «1999-02-29», см. otodom.Otodom._without_copies). Адаптер брал её как
объявление. С 18.09 по 12.10.2026 id был 9+настоящий id+00067 — 3 860 строк, по одной
на страницу; с 12.10.2026 — один id на сутки (90000622NN), и в одну строку за прогон
писалось до 121 разного объявления: 17% всей истории цен, дом в продаже со скидкой
квартиры (F-013 Codex 06.11.2026).

Строки не удаляются (политика владельца), а получают тип TECHNICAL_COPY: их не видит
ничего, что считает по типу сделки. По настоящим объявлениям ничего не теряется: у всех
3 860 строк старого формата настоящий id есть в базе, у всех строк нового — есть
объявление с тем же кодом в ссылке (проверено на боевой 06.11.2026).

Только после выкатки адаптера: иначе следующий прогон заведёт новую строку.

    set WRO_DB=<база>
    python scripts/mark_technical_copies.py [--dry]
"""
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from sqlalchemy import select, text, update  # noqa: E402

from app import analytics, dedup, rent_analytics  # noqa: E402
from app.config import TECHNICAL_COPY  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Listing  # noqa: E402
from app.scraper import SCORE_FIELDS  # noqa: E402

_RX = re.compile(r"9\d{8}00067|90000\d{5}")


def metrics(db):
    q = lambda s: db.execute(text(s)).scalar()  # noqa: E731
    out = {}
    for kind in ("sale", "rent", "house_sale", "house_rent"):
        out["видно " + kind] = q("select count(*) from listings where offer_type='%s' and is_active=1 "
                                 "and is_representative=1" % kind)
    out["выгодных ≥15% (без тонкой базы)"] = q(
        "select count(*) from listings where offer_type='sale' and is_active=1 and is_representative=1 "
        "and discount_pct>=15 and coalesce(deal_thin_base,0)=0")
    out["дома с оценками"] = q("select count(*) from listings where offer_type like 'house%' "
                               "and (discount_pct is not null or yield_pct is not null)")
    out["фантомов активных"] = q("select count(*) from listings where source='otodom' and length(source_id)>8 "
                                 "and is_active=1")
    return out


def main():
    dry = "--dry" in sys.argv
    db = SessionLocal()
    ids = [r[0] for r in db.execute(select(Listing.id, Listing.source_id).where(
        Listing.source == "otodom", Listing.offer_type != TECHNICAL_COPY)).all() if _RX.fullmatch(r[1] or "")]
    print("строк-фантомов:", len(ids))
    before = metrics(db)
    if dry:
        print(before)
        return
    now = datetime.utcnow()
    values = dict({f: None for f in SCORE_FIELDS}, offer_type=TECHNICAL_COPY, is_representative=False,
                  dedup_group=None, group_size=1)
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        db.execute(update(Listing).where(Listing.id.in_(part)).values(**values))
        db.execute(update(Listing).where(Listing.id.in_(part), Listing.is_active.is_(True)).values(
            is_active=False, removed_at=now))
    db.commit()
    print("склейка:", dedup.rebuild_groups(db))
    print("выгодность:", analytics.recompute_deal_scores(db))
    print("доходность:", rent_analytics.recompute_yields(db))
    after = metrics(db)
    for k in before:
        print("%-34s %6s → %s" % (k, before[k], after[k]))


if __name__ == "__main__":
    main()
