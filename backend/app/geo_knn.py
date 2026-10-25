# -*- coding: utf-8 -*-
"""Осиедле по координатам — для объявлений, где источник его не дал.

Otodom называет осиедле у 100% своих объявлений и даёт координаты; OLX даёт
координаты у 100%, а осиедле — почти никогда (у него в адресе только дзельница).
Осиедле — единица аналитики: медианы, пулы выгодности и доходности считаются
сначала по нему (analytics._pool_keys). Объявление без осиедле сравнивается с
дзельницей или городом, то есть с чужими квартирами, — а таких в аренде больше
половины, потому что там OLX основной источник.

Решение без новых зависимостей и без внешних файлов: размеченные точки Otodom
сами задают карту. Для точки без осиедле берём k ближайших размеченных и, если
они согласны между собой, ставим их осиедле. Границы осиедле проходят по улицам,
и у границы соседи расходятся — там мы отказываемся отвечать, а не угадываем.

Проверено на 3000 отложенных точках Otodom (leave-one-out): см. scripts/fill_osiedle.py.
"""
import json
import logging
import math
from typing import Dict, List, Optional, Tuple

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import geo
from .models import Listing

log = logging.getLogger("geo_knn")

K = 9                  # сколько соседей смотрим
MIN_AGREE = 6          # столько из них должны назвать одно осиедле
MAX_DIST_M = 900.0     # дальше — это уже не «соседний дом», отвечать нечестно
CELL = 0.004           # шаг сетки, ~400 м: ячейка+кольцо покрывают радиус поиска
MIN_MAP_POINTS = 500   # на редкой карте соседи случайны — лучше не отвечать вовсе

# Вроцлав на 51° с.ш.: 1° широты ≈ 111.2 км, 1° долготы ≈ 69.9 км
M_PER_DEG_LAT = 111_200.0
M_PER_DEG_LON = 69_900.0


def _cell(lat: float, lon: float) -> Tuple[int, int]:
    return int(math.floor(lat / CELL)), int(math.floor(lon / CELL))


class OsiedleMap(object):
    """Сетка размеченных точек: поиск соседей без перебора всей базы."""

    def __init__(self, points: List[Tuple[float, float, str]]):
        self.grid: Dict[Tuple[int, int], List[Tuple[float, float, str]]] = {}
        for lat, lon, name in points:
            self.grid.setdefault(_cell(lat, lon), []).append((lat, lon, name))
        self.size = len(points)

    def _around(self, lat: float, lon: float, rings: int) -> List[Tuple[float, float, str]]:
        cy, cx = _cell(lat, lon)
        out = []
        for dy in range(-rings, rings + 1):
            for dx in range(-rings, rings + 1):
                out.extend(self.grid.get((cy + dy, cx + dx), ()))
        return out

    def guess(self, lat: float, lon: float) -> Optional[str]:
        """Осиедле или None, если соседи не согласны либо их слишком мало."""
        if lat is None or lon is None:
            return None
        near: List[Tuple[float, str]] = []
        for rings in (1, 2, 3):
            cand = self._around(lat, lon, rings)
            if len(cand) >= K or rings == 3:
                for plat, plon, name in cand:
                    dy = (plat - lat) * M_PER_DEG_LAT
                    dx = (plon - lon) * M_PER_DEG_LON
                    d = math.hypot(dy, dx)
                    if d <= MAX_DIST_M:
                        near.append((d, name))
                if len(near) >= K:
                    break
        if len(near) < K:
            return None
        near.sort()
        votes: Dict[str, int] = {}
        for _, name in near[:K]:
            votes[name] = votes.get(name, 0) + 1
        best, n = max(votes.items(), key=lambda kv: kv[1])
        return best if n >= MIN_AGREE else None


def build_map(db: Session, exclude_ids: Optional[set] = None) -> OsiedleMap:
    """Карта из объявлений, где источник САМ назвал осиедле (это Otodom).
    Свои же догадки в карту не попадают — иначе ошибка расползлась бы."""
    rows = db.execute(select(Listing.id, Listing.lat, Listing.lon, Listing.osiedle).where(
        Listing.lat.isnot(None), Listing.lon.isnot(None), _precise(),
        Listing.osiedle.isnot(None), Listing.osiedle_src.is_(None))).all()
    pts = [(r[1], r[2], r[3]) for r in rows if not exclude_ids or r[0] not in exclude_ids]
    return OsiedleMap(pts)


def _precise():
    """Точка — дом, а не «где-то в дзельнице» (см. models.Listing.geo_radius_km)."""
    return or_(Listing.geo_radius_km.is_(None), Listing.geo_radius_km == 0)


def backfill_radius(db: Session) -> int:
    """geo_radius_km для объявлений OLX, записанных до 25.10.2026, — из сырого
    ответа (поле map). Новые получают его при разборе; после первого прохода
    здесь пусто, и сырые ответы больше не читаются."""
    from .sources.olx import olx_geo_radius
    rows = db.execute(select(Listing.id, Listing.raw_json).where(
        Listing.source == "olx", Listing.geo_radius_km.is_(None), Listing.raw_json.isnot(None))).all()
    updates = []
    for lid, raw in rows:
        try:
            mp = (json.loads(raw or "{}") or {}).get("map") or {}
        except ValueError:
            mp = {}
        updates.append({"id": lid, "geo_radius_km": olx_geo_radius(mp)})
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    return len(updates)


def drop_unreliable(db: Session) -> Dict[str, int]:
    """Снять догадки, которым нельзя верить, и дописать дзельницу верным.

    * точка неточная (радиус > 0) — догадка по центру дзельницы, снимаем;
    * продавец назвал дзельницу, а угаданное осиедле — из другой: у границы
      соседи ошиблись, снимаем (дзельница продавца остаётся);
    * дзельницы нет вовсе — берём её из осиедле: без неё объявление не видно в
      фильтре по дзельнице, а выгодность перескакивает с осиедле сразу на город
      (25.10.2026 таких активных было 324)."""
    rows = db.execute(select(Listing.id, Listing.osiedle, Listing.district, Listing.geo_radius_km).where(
        Listing.osiedle_src == "geo", Listing.osiedle.isnot(None))).all()
    updates = []
    cnt = {"approx": 0, "other_district": 0, "district_set": 0}
    for lid, osiedle, district, radius in rows:
        own = geo.district_of(osiedle)
        if radius:
            cnt["approx"] += 1
            updates.append({"id": lid, "osiedle": None, "osiedle_src": None})
        elif district and own and district != own:
            cnt["other_district"] += 1
            updates.append({"id": lid, "osiedle": None, "osiedle_src": None})
        elif not district and own:
            cnt["district_set"] += 1
            updates.append({"id": lid, "district": own})
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    return cnt


def fill_missing(db: Session, limit: Optional[int] = None) -> Dict[str, int]:
    """Проставить осиедле там, где его нет, а координаты есть и точные.

    Пишем в тот же столбец `osiedle` (аналитика и фильтры читают его и ничего
    не знают про источник), а происхождение — в `osiedle_src='geo'`. Если
    площадка позже назовёт осиедле сама, upsert перезапишет: источник главнее.
    Сначала чистим старые догадки (drop_unreliable): правила стали строже
    25.10.2026, и записанное до этого должно им подчиниться.
    """
    radius = backfill_radius(db)
    dropped = drop_unreliable(db)
    omap = build_map(db)
    if omap.size < MIN_MAP_POINTS:
        log.warning("карта осиедле слишком редкая (%d точек) — пропускаю", omap.size)
        return {"map_points": omap.size, "filled": 0, "unsure": 0, "dropped": dropped}
    q = select(Listing.id, Listing.lat, Listing.lon, Listing.district).where(
        Listing.osiedle.is_(None), Listing.lat.isnot(None), Listing.lon.isnot(None), _precise())
    if limit:
        q = q.limit(limit)
    rows = db.execute(q).all()
    filled = unsure = conflict = 0
    updates = []
    for lid, lat, lon, district in rows:
        name = omap.guess(lat, lon)
        own = geo.district_of(name) if name else None
        if name and district and own and own != district:
            conflict += 1                 # соседи говорят одно, продавец — другое
        elif name:
            upd = {"id": lid, "osiedle": name, "osiedle_src": "geo"}
            if not district and own:
                upd["district"] = own
            updates.append(upd)
            filled += 1
        else:
            unsure += 1
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    log.info("осиедле по координатам: карта %d точек, проставлено %d, не уверены %d, против дзельницы %d",
             omap.size, filled, unsure, conflict)
    out = {"map_points": omap.size, "filled": filled, "unsure": unsure, "conflict": conflict}
    if radius:
        out["radius_backfilled"] = radius
    if any(dropped.values()):
        out["dropped"] = dropped
    return out
