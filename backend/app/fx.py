# -*- coding: utf-8 -*-
"""Курсы НБП (таблица A, средний курс). Владелец думает в долларах —
цены показываются и в PLN, и в USD/EUR по курсу дня."""
import logging
from datetime import datetime
from typing import Dict, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from .models import FxRate

log = logging.getLogger("fx")
NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/?format=json"
CODES = ("USD", "EUR")


def refresh(db: Session) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for code in CODES:
        try:
            r = httpx.get(NBP_URL.format(code=code.lower()), timeout=20)
            r.raise_for_status()
            rate = r.json()["rates"][0]
            date, mid = rate["effectiveDate"], float(rate["mid"])
        except Exception as e:  # noqa: BLE001 — курс не критичен для прогона
            log.warning("НБП %s не ответил: %s", code, e)
            continue
        row = db.query(FxRate).filter_by(date=date, code=code).one_or_none()
        if row is None:
            db.add(FxRate(date=date, code=code, mid=mid, fetched_at=datetime.utcnow()))
        else:
            row.mid = mid
        out[code] = mid
    db.commit()
    return out


def latest(db: Session) -> Dict[str, Optional[float]]:
    res: Dict[str, Optional[float]] = {"USD": None, "EUR": None, "date": None}
    for code in CODES:
        row = (db.query(FxRate).filter_by(code=code)
               .order_by(FxRate.date.desc()).first())
        if row:
            res[code] = row.mid
            res["date"] = max(res["date"] or "", row.date)
    return res


def apply_to_listings(db: Session) -> int:
    """price_usd/price_eur у всех объявлений одним UPDATE — без перебора ORM."""
    fx = latest(db)
    n = 0
    for code, col in (("USD", "price_usd"), ("EUR", "price_eur")):
        mid = fx.get(code)
        if not mid:
            continue
        res = db.execute(text(
            "UPDATE listings SET %s = ROUND(price_pln / :mid, 0) "
            "WHERE price_pln IS NOT NULL" % col), {"mid": mid})
        n = max(n, res.rowcount or 0)
    db.commit()
    return n
