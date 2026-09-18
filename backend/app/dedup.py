# -*- coding: utf-8 -*-
"""Дубли: одна квартира стоит на Otodom и OLX (зеркало), у двух агентств, у
агентства и собственника. В каталоге показывается представитель группы —
самое дешёвое активное размещение, остальные видны в карточке.

Ключи склейки по убыванию силы:
1. OLX `external_url` -> код Otodom в URL (точное зеркало);
2. те же числа: (тип, комнаты, площадь ±0 м² после округления, этаж, осиедле
   или дзельница) и цена в пределах 3%;
3. одна и та же первая картинка на CDN (у зеркал URL совпадает буква в букву).

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


def rebuild_groups(db: Session) -> Dict[str, int]:
    cols = (Listing.id, Listing.source, Listing.offer_type, Listing.url,
            Listing.external_url, Listing.rooms, Listing.area, Listing.floor,
            Listing.osiedle, Listing.osiedle_override, Listing.district,
            Listing.price_pln, Listing.is_active, Listing.first_image,
            Listing.dedup_detached)
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
        if r.first_image and len(r.first_image) > 30:
            by_image[(r.offer_type, r.first_image)].append(r.id)

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
    for root, lst in members.items():
        gid = "g%d" % min(x.id for x in lst)
        groups += 1
        active = [x for x in lst if x.is_active and x.price_pln]
        pool = active or [x for x in lst if x.price_pln] or lst
        rep = min(pool, key=lambda x: (x.price_pln or 1e18, x.id)).id
        for x in lst:
            updates.append({"id": x.id, "dedup_group": gid, "group_size": len(lst),
                            "is_representative": x.id == rep})
    for i in range(0, len(updates), 2000):
        db.bulk_update_mappings(Listing, updates[i:i + 2000])
    db.commit()
    return {"listings": len(rows), "groups": groups, "mirror": linked_mirror,
            "numeric": linked_numeric, "image": linked_image}


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
