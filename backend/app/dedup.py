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


class _UF:
    def __init__(self):
        self.p: Dict[int, int] = {}

    def find(self, x: int) -> int:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


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
            Listing.dedup_detached, Listing.market, Listing.seller_type)
    rows = db.execute(select(*cols)).all()
    uf = _UF()
    by_code: Dict[str, int] = {}
    mirrors: List[tuple] = []
    numeric: Dict[tuple, List[tuple]] = defaultdict(list)
    by_image: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        uf.find(r.id)
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

    linked_numeric = 0
    for key, lst in numeric.items():
        if len(lst) < 2:
            continue
        lst.sort()
        for (p1, id1), (p2, id2) in zip(lst, lst[1:]):
            if p1 and abs(p2 - p1) / p1 <= PRICE_TOL:
                uf.union(id1, id2)
                linked_numeric += 1

    linked_image = 0
    for key, ids in by_image.items():
        for a, b in zip(ids, ids[1:]):
            uf.union(a, b)
            linked_image += 1

    members: Dict[int, List[tuple]] = defaultdict(list)
    for r in rows:
        members[uf.find(r.id)].append(r)

    updates = []
    groups = 0
    investments = 0
    for root, lst in members.items():
        gid = "g%d" % min(x.id for x in lst)
        groups += 1
        active = [x for x in lst if x.is_active and x.price_pln]
        pool = active or [x for x in lst if x.price_pln] or lst
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
            "investments": investments}


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
