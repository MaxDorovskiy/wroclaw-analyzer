# -*- coding: utf-8 -*-
"""Выгодность, срезы рынка, индекс цен.

Принцип тот же, что в Киеве: цена за м² против МЕДИАНЫ ПУЛА ПОХОЖИХ, пулы
ищутся от узкого к широкому, пока не наберётся минимум. Поправка на площадь
измеряется на своих данных при каждом пересчёте (в Киеве метр дешевеет с
площадью на 3-6% за полосу; здесь цифра будет своя, и константу из Киева
копировать нельзя).
"""
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import MIN_AREA, SANE_SQM_RENT, SANE_SQM_SALE
from .models import Listing, PriceHistory, ScrapeRun
from .settings_store import set_setting

log = logging.getLogger("analytics")

# минимальный пул на уровне: узкие уровни допускают меньше, потому что там
# сравнение честнее (тот же осиедле и те же комнаты)
MIN_POOL = {"osiedle_rooms": 6, "osiedle": 8, "district_rooms": 10,
            "district": 12, "city_rooms": 15, "city": 20}
LEVELS = ("osiedle_rooms", "osiedle", "district_rooms", "district", "city_rooms", "city")
TRUST_MIN_POOL = 10          # меньше — «база тонкая»
# полосы площади: границы (м²); базовая полоса — 45-60 (самая массовая)
BAND_EDGES = (30, 45, 60, 80, 100)
BASE_BAND = 2
MIN_BAND_N = 30              # меньше — коэффициент полосы не меряем (1.0)


def band(area: Optional[float]) -> Optional[int]:
    if area is None:
        return None
    for i, edge in enumerate(BAND_EDGES):
        if area < edge:
            return i
    return len(BAND_EDGES)


def band_label(i: Optional[int]) -> Optional[str]:
    if i is None:
        return None
    lo = 0 if i == 0 else BAND_EDGES[i - 1]
    if i == len(BAND_EDGES):
        return u"%d+ м²" % lo
    return u"%d-%d м²" % (lo, BAND_EDGES[i])


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _quantile(vals: List[float], q: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def measure_area_coef(sqms_by_band: Dict[int, List[float]]) -> Dict[int, float]:
    """Медиана zł/м² полосы относительно базовой; без данных — 1.0.
    Коэффициент ограничен 0.7-1.3: дальше это уже не площадь, а мусор."""
    base = _median(sqms_by_band.get(BASE_BAND, []))
    coef = {}
    for b in range(len(BAND_EDGES) + 1):
        vals = sqms_by_band.get(b, [])
        m = _median(vals)
        if base and m and len(vals) >= MIN_BAND_N:
            coef[b] = max(0.7, min(1.3, m / base))
        else:
            coef[b] = 1.0
    return coef


def _rooms_key(rooms: Optional[int]) -> Optional[int]:
    if rooms is None:
        return None
    return min(rooms, 4)


def _bucket(row) -> str:
    c = row.condition_override or row.condition or "unknown"
    return c


def _sane(row, offer_type: str) -> bool:
    lo, hi = SANE_SQM_SALE if offer_type == "sale" else SANE_SQM_RENT
    return bool(row.price_pln and row.area and row.area >= MIN_AREA
                and lo <= row.price_pln / row.area <= hi)


def _pool_keys(row, rk, place_os, place_d, market, bucket) -> List[Tuple[str, tuple]]:
    keys = []
    if place_os and rk:
        keys.append(("osiedle_rooms", (place_os, rk, market, bucket)))
    if place_os:
        keys.append(("osiedle", (place_os, market, bucket)))
    if place_d and rk:
        keys.append(("district_rooms", (place_d, rk, market, bucket)))
    if place_d:
        keys.append(("district", (place_d, market, bucket)))
    if rk:
        keys.append(("city_rooms", (rk, market, bucket)))
    keys.append(("city", (market, bucket)))
    return keys


def recompute_deal_scores(db: Session, explain_id: Optional[int] = None):
    """Скидка к медиане пула у всех активных объявлений продажи."""
    cols = (Listing.id, Listing.price_pln, Listing.area, Listing.rooms, Listing.market,
            Listing.condition, Listing.condition_override, Listing.district,
            Listing.osiedle, Listing.osiedle_override, Listing.is_representative)
    rows = db.execute(select(*cols).where(Listing.offer_type == "sale",
                                          Listing.is_active.is_(True))).all()
    sane = [r for r in rows if _sane(r, "sale")]
    # 1) поправка на площадь — по представителям (зеркала не должны весить вдвое)
    by_band: Dict[int, List[float]] = defaultdict(list)
    for r in sane:
        if r.is_representative:
            by_band[band(r.area)].append(r.price_pln / r.area)
    coef = measure_area_coef(by_band)
    set_setting(db, "area_coef_sale", json.dumps({band_label(b): round(c, 3) for b, c in coef.items()}, ensure_ascii=False))

    # 2) пулы: (уровень, ключ) -> [(скорректированная цена м², id)]
    pools: Dict[Tuple[str, tuple], List[Tuple[float, int]]] = defaultdict(list)
    info = {}
    for r in sane:
        adj = r.price_pln / r.area / coef[band(r.area)]
        rk = _rooms_key(r.rooms)
        place_os = r.osiedle_override or r.osiedle
        market = r.market or "any"
        bucket = _bucket(r)
        info[r.id] = (adj, rk, place_os, r.district, market, bucket)
        if not r.is_representative:
            continue
        for mk in {market, "any"}:
            for bk in ({bucket, "mixed"} if bucket != "unknown" else {"mixed"}):
                for level, key in _pool_keys(r, rk, place_os, r.district, mk, bk):
                    pools[(level, key)].append((adj, r.id))

    # 3) каждому — первая база, где хватает соседей
    updates = []
    trace = None
    now = datetime.utcnow()
    scored = 0
    for r in rows:
        upd = {"id": r.id, "discount_pct": None, "baseline_sqm": None, "baseline_level": None,
               "baseline_key": None, "baseline_count": None, "deal_thin_base": None,
               "price_sqm_adj": None, "deal_updated_at": now}
        if r.id in info:
            adj, rk, place_os, place_d, market, bucket = info[r.id]
            upd["price_sqm_adj"] = round(adj, 2)
            steps = []
            found = None
            # сначала свой рынок и свой класс, потом свой рынок и все классы,
            # потом любой рынок — но уровень места держим узким, сколько можно
            variants = [(market, bucket), (market, "mixed"), ("any", bucket), ("any", "mixed")]
            if bucket == "unknown":
                variants = [(market, "mixed"), ("any", "mixed")]
            for level, key in _pool_keys(r, rk, place_os, place_d, market, bucket):
                for mk, bk in variants:
                    k = key[:-2] + (mk, bk)
                    vals = [(v, i) for v, i in pools.get((level, k), []) if i != r.id]
                    n = len(vals)
                    ok = n >= MIN_POOL[level]
                    steps.append({"level": level, "key": k, "n": n, "ok": ok})
                    if ok and found is None:
                        med = _median([v for v, _ in vals])
                        found = (level, k, n, med)
                        break
                if found:
                    break
            if found:
                level, k, n, med = found
                upd.update({"discount_pct": round((1 - adj / med) * 100, 1), "baseline_sqm": round(med, 0),
                            "baseline_level": level, "baseline_key": json.dumps(k, ensure_ascii=False),
                            "baseline_count": n, "deal_thin_base": n < TRUST_MIN_POOL})
                scored += 1
            if explain_id == r.id:
                trace = {"adj": adj, "band": band_label(band(r.area)), "coef": coef[band(r.area)],
                         "steps": steps, "found": found and {"level": found[0], "key": found[1],
                                                             "n": found[2], "median": found[3]}}
        updates.append(upd)
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    res = {"total": len(rows), "sane": len(sane), "scored": scored,
           "area_coef": {band_label(b): round(c, 3) for b, c in coef.items()}}
    if explain_id is not None:
        res["explain"] = trace
    return res


def deal_explain(db: Session, listing_id: int) -> Optional[dict]:
    """Объяснение для карточки тем же кодом, что и расчёт."""
    res = recompute_deal_scores(db, explain_id=listing_id)
    return res.get("explain")


# ---------- сводка ----------
def market_summary(db: Session) -> Dict:
    now = datetime.utcnow()
    out = {}
    for offer_type in ("sale", "rent"):
        rows = db.execute(select(Listing.price_pln, Listing.area, Listing.first_seen)
                          .where(Listing.offer_type == offer_type, Listing.is_active.is_(True),
                                 Listing.is_representative.is_(True))).all()
        sane = [r for r in rows if _sane(r, offer_type)]
        sqm = [r.price_pln / r.area for r in sane]
        block = {
            "active": len(rows),
            "new_24h": sum(1 for r in rows if r.first_seen and r.first_seen >= now - timedelta(hours=24)),
            "median_sqm": round(_median(sqm), 0) if sqm else None,
            "median_price": round(_median([r.price_pln for r in sane]), 0) if sane else None,
        }
        removed = db.execute(select(func.count()).select_from(Listing).where(
            Listing.offer_type == offer_type, Listing.is_active.is_(False),
            Listing.removed_at >= now - timedelta(days=7))).scalar() or 0
        block["removed_7d"] = removed
        if offer_type == "rent":
            block["median_rent"] = block.pop("median_price")
            block["median_rent_sqm"] = round(_median(sqm), 1) if sqm else None
            block.pop("median_sqm", None)
        out[offer_type] = block
    return out


# ---------- срезы ----------
def stats(db: Session, offer_type: str = "sale", level: str = "osiedle",
          rooms: Optional[List[int]] = None, market: Optional[str] = None,
          condition: Optional[List[str]] = None) -> Dict:
    from . import geo
    cols = (Listing.price_pln, Listing.area, Listing.rooms, Listing.market, Listing.condition,
            Listing.condition_override, Listing.district, Listing.osiedle, Listing.osiedle_override,
            Listing.first_seen, Listing.posted_at, Listing.is_active, Listing.removed_at)
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.execute(select(*cols).where(
        Listing.offer_type == offer_type, Listing.is_representative.is_(True),
        (Listing.is_active.is_(True)) | (Listing.removed_at >= since))).all()
    now = datetime.utcnow()
    groups: Dict[str, dict] = {}
    all_sqm: List[float] = []
    for r in rows:
        if rooms and (r.rooms is None or _rooms_key(r.rooms) not in rooms):
            continue
        if market and r.market != market:
            continue
        if condition and (r.condition_override or r.condition) not in condition:
            continue
        name = (r.osiedle_override or r.osiedle) if level == "osiedle" else r.district
        if not name:
            name = u"— невідомо"
        g = groups.setdefault(name, {"name": name, "sqm": [], "price": [], "area": [], "days": [],
                                     "count": 0, "new_30d": 0, "removed_30d": 0,
                                     "district": geo.district_of(name) if level == "osiedle" else name})
        if r.is_active:
            g["count"] += 1
            if _sane(r, offer_type):
                s = r.price_pln / r.area
                g["sqm"].append(s)
                g["price"].append(r.price_pln)
                g["area"].append(r.area)
                all_sqm.append(s)
            start = r.posted_at or r.first_seen
            if start:
                g["days"].append((now - start).days)
            if r.first_seen and r.first_seen >= since:
                g["new_30d"] += 1
        elif r.removed_at and r.removed_at >= since:
            g["removed_30d"] += 1
    out = []
    for g in groups.values():
        out.append({
            "name": g["name"],
            "name_uk": (geo.osiedle_uk(g["name"]) if level == "osiedle" else geo.district_uk(g["name"])),
            "district": g["district"],
            "count": g["count"],
            "median_sqm": round(_median(g["sqm"]), 0) if g["sqm"] else None,
            "p25_sqm": round(_quantile(g["sqm"], 0.25), 0) if g["sqm"] else None,
            "p75_sqm": round(_quantile(g["sqm"], 0.75), 0) if g["sqm"] else None,
            "median_price": round(_median(g["price"]), 0) if g["price"] else None,
            "median_area": round(_median(g["area"]), 1) if g["area"] else None,
            "median_days": int(_median(g["days"])) if g["days"] else None,
            "new_30d": g["new_30d"], "removed_30d": g["removed_30d"],
        })
    out.sort(key=lambda x: -(x["count"] or 0))
    return {"rows": out, "total": sum(g["count"] for g in groups.values()),
            "median_sqm": round(_median(all_sqm), 0) if all_sqm else None}


# ---------- индекс по одним и тем же объявлениям ----------
def _period_key(dt: datetime, period: str) -> str:
    if period == "quarter":
        return "%d-Q%d" % (dt.year, (dt.month - 1) // 3 + 1)
    return dt.strftime("%Y-%m")


def _period_start(key: str) -> datetime:
    if "-Q" in key:
        y, q = key.split("-Q")
        return datetime(int(y), (int(q) - 1) * 3 + 1, 1)
    y, m = key.split("-")
    return datetime(int(y), int(m), 1)


def price_index(db: Session, period: str = "month", offer_type: str = "sale") -> Dict:
    """Медиана изменения цены у объявлений, живших на ОБЕИХ границах периода.
    Медиана по дате подачи движением рынка не является (дешёвое уходит
    быстрее); price_history пишется только при смене цены — цена на дату
    берётся переносом последней известной."""
    ls = db.execute(select(Listing.id, Listing.first_seen, Listing.removed_at, Listing.is_active)
                    .where(Listing.offer_type == offer_type, Listing.is_representative.is_(True))).all()
    if not ls:
        return {"points": []}
    ids = {r.id: r for r in ls}
    hist: Dict[int, List[Tuple[datetime, float]]] = defaultdict(list)
    for lid, price, at in db.execute(select(PriceHistory.listing_id, PriceHistory.price_pln,
                                            PriceHistory.seen_at).order_by(PriceHistory.seen_at)).all():
        if lid in ids and price:
            hist[lid].append((at, price))
    first = min(r.first_seen for r in ls if r.first_seen)
    now = datetime.utcnow()
    keys = []
    cur = _period_start(_period_key(first, period))
    while cur <= now:
        keys.append(_period_key(cur, period))
        nxt = cur + timedelta(days=32 if period == "month" else 95)
        cur = _period_start(_period_key(nxt, period))

    def price_at(lid: int, t: datetime) -> Optional[float]:
        last = None
        for at, p in hist.get(lid, []):
            if at <= t:
                last = p
            else:
                break
        return last

    points = []
    index = 100.0
    for i, k in enumerate(keys):
        start = _period_start(k)
        end = _period_start(keys[i + 1]) if i + 1 < len(keys) else now
        changes = []
        for lid, r in ids.items():
            if not r.first_seen or r.first_seen > start:
                continue
            alive_end = r.is_active or (r.removed_at and r.removed_at >= end)
            if not alive_end:
                continue
            p0, p1 = price_at(lid, start), price_at(lid, end)
            if p0 and p1:
                changes.append((p1 - p0) / p0 * 100)
        med = _median(changes) if len(changes) >= 20 else None
        if i > 0 and med is not None:
            index = index * (1 + med / 100)
        points.append({"period": k, "index": round(index, 1), "change_pct": round(med, 2) if med is not None else None,
                       "n": len(changes)})
    return {"points": points}


def trends(db: Session, weeks: int = 26, offer_type: str = "sale") -> Dict:
    now = datetime.utcnow()
    since = now - timedelta(weeks=weeks)
    rows = db.execute(select(Listing.price_pln, Listing.area, Listing.first_seen, Listing.removed_at,
                             Listing.is_active)
                      .where(Listing.offer_type == offer_type, Listing.is_representative.is_(True))).all()
    weeks_out = []
    for w in range(weeks):
        start = since + timedelta(weeks=w)
        end = start + timedelta(weeks=1)
        new = [r for r in rows if r.first_seen and start <= r.first_seen < end]
        removed = sum(1 for r in rows if r.removed_at and start <= r.removed_at < end)
        active = sum(1 for r in rows if r.first_seen and r.first_seen < end
                     and (r.is_active or (r.removed_at and r.removed_at >= end)))
        sqm = [r.price_pln / r.area for r in new if _sane(r, offer_type)]
        weeks_out.append({"week": start.strftime("%Y-%m-%d"), "new": len(new), "removed": removed,
                          "active": active, "median_sqm": round(_median(sqm), 0) if sqm else None})
    return {"points": weeks_out}
