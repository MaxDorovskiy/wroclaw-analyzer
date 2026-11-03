# -*- coding: utf-8 -*-
"""Дубли: одна квартира стоит на Otodom и OLX (зеркало), у двух агентств, у
агентства и собственника. В каталоге показывается представитель группы —
самое дешёвое активное размещение, остальные видны в карточке.

Ключи склейки по убыванию силы:
1. OLX `external_url` -> код Otodom в URL (точное зеркало);
2. те же числа: (тип, комнаты, площадь ±0 м² после округления, этаж, осиедле
   или дзельница) и цена в пределах 3%;
3. одна и та же первая картинка на CDN — И те же комнаты, площадь, этаж. Одной
   картинки мало: у квартир застройщика первая картинка — общий рендер дома.
   На первом прогоне 18.09.2026 (9411 объявлений Otodom) ключ «только картинка»
   сливал 3374 объявления в 395 групп и прятал за представителем 31.7%
   каталога; в 347 группах площади расходились больше чем на 2 м², крупнейшая —
   44 квартиры одного застройщика от 35 до 68 м², от 424 тыс. до 1.05 млн zł,
   этажи 1-11. С числами — 270 объявлений (2.9%), группы не больше 4: повторные
   подачи одного лота.

Барьера, который не ошибается, нет (в Киеве проверено), поэтому есть ручное
«інша квартира» (dedup_detached) — такие строки в склейку не идут.
"""
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Listing

PRICE_TOL = 0.03
_ID_RX = re.compile(r"ID([A-Za-z0-9]+)/?(?:[?#].*)?$")


def otodom_code(url: Optional[str]) -> Optional[str]:
    if not url or "otodom" not in url:
        return None
    m = _ID_RX.search(url)
    return m.group(1) if m else None


#: Одна квартира не может стоять в домах разных лет и в разных местах. Ключ «по
#: числам» этого не видел: Codex 28.10.2026 нашёл g49 — вторичка 2001 г. на
#: ul. Tolkmicka и первичка 2028 г. на Alei Śliwowej, 55,50 и 56,11 м², 639 000 и
#: 639 900 zł; вторая была скрыта как «дубль».
#: Пороги подобраны на ночной копии 02.11.2026 по выборке разведённых групп:
#: * год у разных агентств расходится и в одном доме (каменица 1900 / 1910,
#:   Vivaldiego 2003 / 2006 / 2011 в одной точке) — разница лет мешает склейке,
#:   только если и точки не рядом (дальше SAME_PLACE_M);
#: * у квартир застройщика бывают «улетевшие» метки (Architektów: 2 км между
#:   юнитами одной цены) — по месту разводим, только если ВСЕ пары точек дальше
#:   MAX_POINT_GAP_M;
#: * цена до злотого (EXACT_PRICE) — это тот же юнит: расстояние ей прощаем
#:   (934/8468: 1 522 457 zł, 84,23 м², метка застройщика в 1,5 км), а разницу лет
#:   — нет (F-001 Codex 03.11.2026: 650 123 / 650 124, 2001 / 2028 г. склеивались);
#: * «до злотого» — только если обе цены некруглые: 1 099 999 и 1 100 000 у квартир
#:   на разных улицах, 2012 и 2018 г., 737 м (3898/36794) склеивались. «…999» само
#:   по себе не круглая: у застройщика 868 999 и 868 999,9 — один юнит 64,55 м² в 1,7 км.
#: Ближайшая пара точек, а не все пары — сознательно: проверка «все точки рядом»
#: на копии 03.11.2026 вскрыла 14 скрытых продаж, и половина — та же квартира
#: (pl. Legionów 389 999 / 390 000 в одной точке, 880 000 в 7 м). Цепочка через
#: объявление без года (2172/33601/35469: 1970 и 1986 г., 600 м) остаётся — см. DEFERRED.
MAX_YEAR_GAP = 3
SAME_PLACE_M = 300.0
MAX_POINT_GAP_M = 1000.0
EXACT_PRICE = 5.0


def _round_price(p: float) -> bool:
    # без округления до злотого: 908 999,8 (прайс застройщика) — не 909 000
    return p % 1000 == 0


def _dist(a, b) -> float:
    return ((a[0] - b[0]) * 111200.0) ** 2 + ((a[1] - b[1]) * 69900.0) ** 2


class _UF:
    """Объединение групп. У каждой группы — годы постройки и точные точки её
    членов, и слабые ключи (числа, картинка) объединяют группы ТОЛЬКО если они
    совместимы целиком: иначе цепочка A~B~C через посредника склеивает A и C,
    которые между собой несовместимы."""

    def __init__(self):
        self.p: Dict[int, int] = {}
        self.years: Dict[int, tuple] = {}
        self.points: Dict[int, list] = {}

    def add(self, x: int, year=None, point=None):
        self.p.setdefault(x, x)
        if year:
            self.years[x] = (year, year)
        if point:
            self.points[x] = [point]

    def find(self, x: int) -> int:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def compatible(self, a: int, b: int, exact: bool = False) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        pa, pb = self.points.get(ra) or [], self.points.get(rb) or []
        d2 = [_dist(x, y) for x in pa for y in pb]                         # квадраты метров
        if not exact and d2 and min(d2) > MAX_POINT_GAP_M ** 2:
            return False
        ya, yb = self.years.get(ra), self.years.get(rb)
        if ya and yb and max(ya[1], yb[1]) - min(ya[0], yb[0]) > MAX_YEAR_GAP:
            return bool(d2) and min(d2) <= SAME_PLACE_M ** 2
        return True

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        keep, gone = min(ra, rb), max(ra, rb)
        self.p[gone] = keep
        ya, yb = self.years.pop(gone, None), self.years.get(keep)
        if ya:
            self.years[keep] = (min(ya[0], yb[0]), max(ya[1], yb[1])) if yb else ya
        pts = self.points.pop(gone, None)
        if pts:
            self.points.setdefault(keep, []).extend(pts[:20])   # хватит для проверки, группы до ~30


MIN_INVEST_AREAS = 4


def is_investment(members: List) -> bool:
    """Группа — не дубли, а ценник застройщика?

    Квартиры одной инвестиции по числам неразличимы: те же комнаты,
    тот же этаж, площадь и цена в пределах погрешности ключа — и склейка
    собирает их в одну карточку. Разобрать их обратно — засорить каталог
    тридцатью почти одинаковыми строками; оставить как есть — соврать
    подписью «ещё 31 размещение». Поэтому группу помечаем, а подпись
    меняется на «N квартир в этом доме».

    Признак — ЧИСЛО РАЗНЫХ ТОЧНЫХ ПЛОЩАДЕЙ, а не «один продавец»:
    самая большая группа на боевой базе 24.09.2026 (30 квартир, 20 площадей)
    стояла у ДВУХ агентств сразу. Четыре разные площади (40,52 / 40,60 /
    40,68 / 40,76) не объяснить опиской в одном объявлении; три — ещё можно
    (34,56 / 34,57 / 35,0 при одной цене — это одна квартира, поданная трижды).
    Второе условие — первичка или застройщик в группе: на вторичке столько
    одинаковых квартир в одном доме разом не продают.

    На 24.09.2026: 100 групп, 817 объявлений.
    """
    if len(members) < MIN_INVEST_AREAS:
        return False
    if not any((x.market == "primary" or x.seller_type == "developer") for x in members):
        return False
    areas = {round(x.area, 2) for x in members if x.area}
    return len(areas) >= MIN_INVEST_AREAS


def rebuild_groups(db: Session) -> Dict[str, int]:
    cols = (Listing.id, Listing.source, Listing.offer_type, Listing.url,
            Listing.external_url, Listing.rooms, Listing.area, Listing.floor,
            Listing.osiedle, Listing.osiedle_override, Listing.district,
            Listing.price_pln, Listing.is_active, Listing.first_image,
            Listing.dedup_detached, Listing.market, Listing.seller_type,
            Listing.build_year, Listing.lat, Listing.lon, Listing.geo_radius_km)
    rows = db.execute(select(*cols)).all()
    uf = _UF()
    by_code: Dict[str, int] = {}
    mirrors: List[tuple] = []
    numeric: Dict[tuple, List[tuple]] = defaultdict(list)
    by_image: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        # точка — только точная (у OLX без адреса это центр дзельницы, см. geo_knn)
        point = (r.lat, r.lon) if r.lat is not None and r.lon is not None and not r.geo_radius_km else None
        uf.add(r.id, r.build_year, point)
        if r.dedup_detached:
            continue
        if r.source == "otodom":
            code = otodom_code(r.url)
            if code:
                by_code[(r.offer_type, code)] = r.id
        if r.external_url:
            code = otodom_code(r.external_url)
            if code:
                mirrors.append((r.offer_type, code, r.id))
        place = r.osiedle_override or r.osiedle or r.district
        if r.rooms and r.area and place and r.price_pln:
            key = (r.offer_type, r.rooms, int(round(r.area)), r.floor, place)
            numeric[key].append((r.price_pln, r.id))
        if r.first_image and len(r.first_image) > 30 and r.rooms and r.area:
            by_image[(r.offer_type, r.first_image, r.rooms, int(round(r.area)), r.floor)].append(r.id)

    linked_mirror = 0
    for offer_type, code, lid in mirrors:
        other = by_code.get((offer_type, code))
        if other and other != lid:
            uf.union(lid, other)
            linked_mirror += 1

    # Зеркало (код Otodom в ссылке OLX) — точный признак, его не проверяем;
    # числа и картинка — слабые, им нужна совместимость групп.
    linked_numeric = refused = 0
    for key, lst in numeric.items():
        if len(lst) < 2:
            continue
        lst.sort()
        for (p1, id1), (p2, id2) in zip(lst, lst[1:]):
            if p1 and abs(p2 - p1) / p1 <= PRICE_TOL:
                # «до злотого» — только некруглая цена (прайс застройщика 385 303);
                # 650 000 у двух разных квартир вторички совпадает сплошь и рядом
                exact = abs(p2 - p1) <= EXACT_PRICE and not _round_price(p1) and not _round_price(p2)
                if uf.compatible(id1, id2, exact):
                    uf.union(id1, id2)
                    linked_numeric += 1
                else:
                    refused += 1

    linked_image = 0
    for key, ids in by_image.items():
        for a, b in zip(ids, ids[1:]):
            if uf.compatible(a, b):
                uf.union(a, b)
                linked_image += 1
            else:
                refused += 1

    members: Dict[int, List[tuple]] = defaultdict(list)
    for r in rows:
        members[uf.find(r.id)].append(r)

    updates = []
    groups = 0
    investments = 0
    for root, lst in members.items():
        gid = "g%d" % min(x.id for x in lst)
        groups += 1
        # Активное сильнее цены: у объявлений «запытайте о цене» цены нет вовсе,
        # и представителем группы становилось СНЯТОЕ размещение — а живое исчезало
        # из каталога (он показывает is_active И is_representative). На боевой базе
        # 09.10.2026 так пряталась одна квартира (группа g7327).
        active_priced = [x for x in lst if x.is_active and x.price_pln]
        active = [x for x in lst if x.is_active]
        pool = active_priced or active or [x for x in lst if x.price_pln] or lst
        rep = min(pool, key=lambda x: (x.price_pln or 1e18, x.id)).id
        kind = "investment" if is_investment(active or lst) else None
        if kind:
            investments += 1
        for x in lst:
            updates.append({"id": x.id, "dedup_group": gid, "group_size": len(lst),
                            "is_representative": x.id == rep, "group_kind": kind})
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    return {"listings": len(rows), "groups": groups, "mirror": linked_mirror,
            "numeric": linked_numeric, "image": linked_image,
            "refused": refused, "investments": investments}


def detach(db: Session, listing_id: int) -> Optional[str]:
    """«Інша квартира»: вынести размещение из группы навсегда."""
    row = db.get(Listing, listing_id)
    if row is None:
        return None
    row.dedup_detached = True
    row.dedup_group = "g%d" % row.id
    row.group_size = 1
    row.is_representative = True
    db.commit()
    rebuild_groups(db)
    db.refresh(row)
    return row.dedup_group
