# -*- coding: utf-8 -*-
"""Доходность от сдачи: медиана ставки аренды по уровням -> % годовых.

Формула валовая: ставка × 12 / вложения. У голых («stan deweloperski») и
убитых квартир в знаменателе цена ПЛЮС отделка (`renovation_cost_sqm_pln`).
Czynsz administracyjny не вычитаем — на аренде его обычно платит арендатор
сверх ставки. Поправка на площадь у аренды своя (измеряется на аренде), у
продажи — своя; копировать одну в другую нельзя.
"""
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import geo
from .analytics import _median, _rooms_key, _sane, band, band_label, era, era_ratios, measure_area_coef
from .models import Listing
from .settings_store import get_float, set_setting

log = logging.getLogger("rent")

MIN_POOL = {"osiedle_rooms": 5, "osiedle": 8, "district_rooms": 8, "district": 12,
            "city_rooms": 15, "city": 20}
RENO_CONDITIONS = ("developer_bare", "to_renovate")


# Сдаётся КОМНАТА, а не квартира. Такие объявления попадают в категорию
# «мешкания — аренда» по ошибке продавца, и ставка в них — за одну комнату при
# площади всей квартиры (1000 zł за 62 м²) или за комнату в 12 м² (1200 zł). На
# узком уровне (осиедле × комнаты, 5-8 объявлений) одна такая строка сдвигает
# медиану. На 15.10.2026 их 30 из 4124 активных.
# Признак — ТОЛЬКО единственное число «pokój»: по-польски «2 pokoje do
# wynajęcia» обычно значит «двушка в аренду», и фильтр по множественному числу
# выкинул бы целые квартиры. Проверено глазами по всем совпадениям.
_ROOM_RX = re.compile(r"(?<![\d\-])(?<!\d\s)\bpok[oó]j\b|\bmiejsce\s+w\s+pokoju\b", re.I)
_WHOLE_FLAT_RX = re.compile(
    r"kawalerk"                                  # студия — квартира из одной комнаты
    r"|pok[oó]j\w*\s+k[aą]piel"                  # «pokój kąpielowy» — ванная
    r"|\d\s*-?\s*pokoje\b|\d\s*pok\."            # «2 Pokoje», «3pok.» — описание целой квартиры
    r"|mieszkanie\s+(lub\s+)?pok[oó]j"           # «mieszkanie pokój z kuchnią»
    r"|z[lł]\s*/\s*pok", re.I)                   # «1400 zł/pokój» — цена в объявлении за всю


def is_room_rental(title: Optional[str]) -> bool:
    """Сдаётся комната, а не квартира целиком — в медиану аренды такое не берём."""
    t = title or ""
    return bool(_ROOM_RX.search(t)) and not _WHOLE_FLAT_RX.search(t)


def _rent_rows(db: Session):
    """Объявления аренды, из которых считается медиана ставки.

    Только активные представители групп (одна квартира на Otodom и OLX считается
    один раз), с правдоподобной ставкой за м² и без комнат на съём."""
    cols = (Listing.id, Listing.price_pln, Listing.area, Listing.rooms, Listing.district,
            Listing.osiedle, Listing.osiedle_override, Listing.is_representative, Listing.title_pl,
            Listing.build_year, Listing.building_type, Listing.market)
    rows = db.execute(select(*cols).where(Listing.offer_type == "rent", Listing.is_active.is_(True),
                                          Listing.is_representative.is_(True))).all()
    return [r for r in rows if _sane(r, "rent") and not is_room_rental(r.title_pl)]


def _rent_pools(rows, by_era: bool = True):
    """Пулы ставок за м², приведённых к средней полосе площади и — если by_era —
    к типичному для осиедле возрасту дома.

    Поправка на возраст — та же, что у продажи (analytics.measure_era_coef), но
    своя: в новостройке того же осиедле м² сдаётся на ~20% дороже, чем в старом
    доме (копия 15.10.2026: 2015+ — 1,093 от медианы осиедле, 1945-2014 — 0,90).
    Без неё старой дешёвой квартире ставили медианную ставку осиедле, и её
    доходность выходила завышенной на ~10%."""
    by_band: Dict[int, List[float]] = defaultdict(list)
    for r in rows:
        by_band[band(r.area)].append(r.price_pln / r.area)
    coef = measure_area_coef(by_band)
    era_coef = era_ratios((r.osiedle_override or r.osiedle, era(r), r.price_pln / r.area / coef[band(r.area)])
                          for r in rows) if by_era else {}
    pools: Dict[Tuple[str, tuple], List[float]] = defaultdict(list)
    for r in rows:
        adj = r.price_pln / r.area / coef[band(r.area)] / era_coef.get(era(r), 1.0)
        rk = _rooms_key(r.rooms)
        os_ = r.osiedle_override or r.osiedle
        if os_ and rk:
            pools[("osiedle_rooms", (os_, rk))].append(adj)
        if os_:
            pools[("osiedle", (os_,))].append(adj)
        if r.district and rk:
            pools[("district_rooms", (r.district, rk))].append(adj)
        if r.district:
            pools[("district", (r.district,))].append(adj)
        if rk:
            pools[("city_rooms", (rk,))].append(adj)
        pools[("city", ())].append(adj)
    return pools, coef, era_coef


def _find(pools, rk, os_, district):
    for level, key in (("osiedle_rooms", (os_, rk)), ("osiedle", (os_,)),
                       ("district_rooms", (district, rk)), ("district", (district,)),
                       ("city_rooms", (rk,)), ("city", ())):
        if any(k is None for k in key):
            continue
        vals = pools.get((level, key), [])
        if len(vals) >= MIN_POOL[level]:
            return level, len(vals), _median(vals)
    return None


def recompute_yields(db: Session) -> Dict:
    rent = _rent_rows(db)
    if not rent:
        return {"rent": 0, "scored": 0}
    pools, coef, era_coef = _rent_pools(rent)
    set_setting(db, "area_coef_rent", json.dumps({band_label(b): round(c, 3) for b, c in coef.items()}, ensure_ascii=False))
    set_setting(db, "era_coef_rent", json.dumps({e: round(c, 3) for e, c in sorted(era_coef.items())},
                                                ensure_ascii=False))
    reno_sqm = get_float(db, "renovation_cost_sqm_pln", 2000.0)
    cols = (Listing.id, Listing.price_pln, Listing.area, Listing.rooms, Listing.district,
            Listing.osiedle, Listing.osiedle_override, Listing.condition, Listing.condition_override,
            Listing.build_year, Listing.building_type, Listing.market)
    sale = db.execute(select(*cols).where(Listing.offer_type == "sale", Listing.is_active.is_(True))).all()
    updates = []
    scored = 0
    for r in sale:
        upd = {"id": r.id, "rent_median_pln": None, "rent_baseline_level": None,
               "rent_baseline_count": None, "yield_pct": None, "yield_investment_pln": None,
               "yield_reno_cost_pln": None}
        # Тот же фильтр здравого смысла, что и у выгодности (4–40 тыс. zł/м²).
        # Без него доля в квартире, торговое место или арендное объявление, попавшее
        # в категорию продажи, получали доходность в десятки и сотни процентов и
        # вставали первыми в «Найкраща дохідність» на главном экране.
        # На боевой базе 09.10.2026: 149 000 zł за 118 м² — 48,8% годовых.
        if _sane(r, "sale"):
            found = _find(pools, _rooms_key(r.rooms), r.osiedle_override or r.osiedle, r.district)
            if found:
                level, n, med_sqm = found
                expected = med_sqm * coef[band(r.area)] * era_coef.get(era(r), 1.0) * r.area
                cond = r.condition_override or r.condition
                reno = reno_sqm * r.area if cond in RENO_CONDITIONS else 0.0
                invest = r.price_pln + reno
                upd.update({"rent_median_pln": round(expected, 0), "rent_baseline_level": level,
                            "rent_baseline_count": n, "yield_pct": round(expected * 12 / invest * 100, 2),
                            "yield_investment_pln": round(invest, 0), "yield_reno_cost_pln": round(reno, 0)})
                scored += 1
        updates.append(upd)
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    return {"rent": len(rent), "sale": len(sale), "scored": scored}


def rent_explain(db: Session, row: Listing) -> Optional[dict]:
    if row.yield_pct is None:
        return None
    return {"level": row.rent_baseline_level, "count": row.rent_baseline_count,
            "expected_rent": row.rent_median_pln, "investment_pln": row.yield_investment_pln,
            "renovation_cost_pln": row.yield_reno_cost_pln,
            "median_sqm": round(row.rent_median_pln / row.area, 1) if row.area else None}


def yield_top(db: Session, level: str = "osiedle", rooms: Optional[int] = None,
              min_rent: int = 8, min_sale: int = 8) -> Dict:
    """Топ мест для покупки под сдачу: ставка zł/м² в месте против цены м² там же.
    Ставка приводится к площади пула продажи через коэффициент полосы."""
    rent = _rent_rows(db)
    # без поправки на возраст: здесь ставка места против цены места, обе — как есть
    pools, coef_r, _ = _rent_pools(rent, by_era=False)
    cols = (Listing.price_pln, Listing.area, Listing.rooms, Listing.district, Listing.osiedle,
            Listing.osiedle_override)
    sale = [r for r in db.execute(select(*cols).where(
        Listing.offer_type == "sale", Listing.is_active.is_(True),
        Listing.is_representative.is_(True))).all() if _sane(r, "sale")]
    groups: Dict[tuple, dict] = {}
    for r in sale:
        place = (r.osiedle_override or r.osiedle) if level == "osiedle" else r.district
        rk = _rooms_key(r.rooms)
        if not place or not rk or (rooms and rk != rooms):
            continue
        g = groups.setdefault((place, rk), {"sqm": [], "area": []})
        g["sqm"].append(r.price_pln / r.area)
        g["area"].append(r.area)
    out = []
    for (place, rk), g in groups.items():
        if len(g["sqm"]) < min_sale:
            continue
        key = ("osiedle_rooms", (place, rk)) if level == "osiedle" else ("district_rooms", (place, rk))
        vals = pools.get(key, [])
        # И не пустой: при min_rent <= 0 проверка длины ничего не отсекала,
        # и _median([]) возвращал None — ручка падала в 500 (проверка 10.10.2026)
        if not vals or len(vals) < min_rent:
            continue
        med_area = _median(g["area"])
        rent_sqm = _median(vals) * coef_r[band(med_area)]
        sale_sqm = _median(g["sqm"])
        out.append({"name": place, "name_uk": geo.osiedle_uk(place) if level == "osiedle" else geo.district_uk(place),
                    "rooms": rk, "rent_sqm": round(rent_sqm, 1),
                    "rent_median_pln": round(rent_sqm * med_area, 0),
                    "sale_median_sqm": round(sale_sqm, 0),
                    "yield_pct": round(rent_sqm * 12 / sale_sqm * 100, 2),
                    "n_rent": len(vals), "n_sale": len(g["sqm"])})
    out.sort(key=lambda x: -x["yield_pct"])
    return {"rows": out}
