# -*- coding: utf-8 -*-
"""OLX: публичный JSON API выдачи (/api/v1/offers/).

Описание и параметры приходят сразу — карточки не нужны. Ловушки, известные
из чужого опыта: id категорий/городов меняются (при нуле объявлений
проверять их первыми — probe_sources.py печатает category.id и city первых
записей), потолок offset около 1000 — выдача дробится по цене на полосы,
где объявлений меньше 1000.
"""
import math
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..config import OLX_API, OLX_FRIENDLY, OLX_MAX_OFFSET, OLX_PAGE_SIZE, OLX_PATHS
from .base import Page, RawListing, Source, parse_dt

# первичные полосы цены; если в полосе > 1000 объявлений — делится пополам
PRICE_EDGES = {
    "sale": [0, 300000, 400000, 450000, 500000, 550000, 600000, 650000, 700000,
             800000, 900000, 1000000, 1300000, 2000000, None],
    "rent": [0, 2000, 2400, 2800, 3200, 3600, 4000, 4500, 5500, 8000, None],
}
MIN_WIDTH = {"sale": 5000, "rent": 50}


def _pv(params: Dict[str, dict], key: str) -> Any:
    """Значение параметра: для select — ключ, для числа — число, иначе label."""
    p = params.get(key)
    if not p:
        return None
    v = p.get("value")
    if isinstance(v, dict):
        if v.get("key") not in (None, ""):
            return v.get("key")
        if v.get("value") is not None:
            return v.get("value")
        return v.get("label")
    return v


def _pnum(params: Dict[str, dict], key: str) -> Optional[float]:
    p = params.get(key)
    if not p:
        return None
    v = p.get("value")
    if isinstance(v, dict):
        for k in ("value", "key", "label"):
            x = v.get(k)
            if x is None:
                continue
            try:
                return float(str(x).replace(u"\xa0", "").replace(" ", "").replace(",", ".").split("z")[0])
            except ValueError:
                continue
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Olx(Source):
    name = "olx"
    needs_details = False

    # ---------- id категории и города ----------
    def resolve_ids(self, offer_type: str, fetcher, settings: Dict[str, str]) -> Tuple[int, int]:
        cat_key = "olx_category_sale" if offer_type == "sale" else "olx_category_rent"
        fallback = (int(settings.get(cat_key) or 0), int(settings.get("olx_city_id") or 0))
        try:
            data = fetcher.get_json(OLX_FRIENDLY + OLX_PATHS[offer_type])
            d = data.get("data") or data
            cat = int(d.get("category_id") or 0)
            city = int(d.get("city_id") or 0)
            if cat and city:
                return cat, city
        except Exception as e:  # noqa: BLE001 — любой сбой = берём настройку
            fetcher_log(e)
        return fallback

    def _total(self, fetcher, base: dict, lo: Optional[int], hi: Optional[int]) -> int:
        params = dict(base, offset=0, limit=1)
        if lo is not None:
            params["filter_float_price:from"] = lo
        if hi is not None:
            params["filter_float_price:to"] = hi
        data = fetcher.get_json(OLX_API, params)
        meta = data.get("metadata") or {}
        for k in ("total_elements", "total", "count"):
            if isinstance(meta.get(k), int):
                return meta[k]
        return len(data.get("data") or [])

    def _bands(self, fetcher, base: dict, offer_type: str) -> List[Tuple[Optional[int], Optional[int], int]]:
        """Полосы цены с числом объявлений ≤ потолка offset. Дробит пополам,
        пока полоса шире MIN_WIDTH; узкую оставляет — что сверх потолка,
        всё равно не достать (такие цены — редкость)."""
        total = self._total(fetcher, base, None, None)
        if total <= OLX_MAX_OFFSET:
            return [(None, None, total)]
        edges = PRICE_EDGES[offer_type]
        stack = []
        for i in range(len(edges) - 1):
            lo = edges[i]
            hi = (edges[i + 1] - 1) if edges[i + 1] is not None else None
            stack.append((lo, hi))
        out = []
        while stack:
            lo, hi = stack.pop(0)
            n = self._total(fetcher, base, lo, hi)
            if n == 0:
                continue
            width = (hi - lo) if (hi is not None and lo is not None) else None
            if n > OLX_MAX_OFFSET and width and width > MIN_WIDTH[offer_type]:
                mid = lo + width // 2
                stack.insert(0, (mid + 1, hi))
                stack.insert(0, (lo, mid))
                continue
            out.append((lo, hi, n))
        return out

    def iter_pages(self, offer_type: str, fetcher, start_page: int = 1,
                   settings: Optional[Dict[str, str]] = None) -> Iterator[Page]:
        settings = settings or {}
        cat, city = self.resolve_ids(offer_type, fetcher, settings)
        base = {"category_id": cat, "city_id": city, "sort_by": "created_at:desc",
                "limit": OLX_PAGE_SIZE}
        bands = self._bands(fetcher, base, offer_type)
        total_pages = sum(int(math.ceil(min(n, OLX_MAX_OFFSET) / float(OLX_PAGE_SIZE))) for _, _, n in bands)
        page = 0
        for lo, hi, n in bands:
            offset = 0
            while offset < min(n, OLX_MAX_OFFSET):
                page += 1
                if page < start_page:
                    offset += OLX_PAGE_SIZE
                    continue
                params = dict(base, offset=offset)
                if lo is not None:
                    params["filter_float_price:from"] = lo
                if hi is not None:
                    params["filter_float_price:to"] = hi
                data = fetcher.get_json(OLX_API, params)
                if page == start_page:
                    import json as _json
                    fetcher.dump("olx_%s_page%d.json" % (offer_type, page),
                                 _json.dumps(data, ensure_ascii=False, indent=1))
                items = data.get("data") or []
                parsed = [x for x in (self.parse_item(it, offer_type) for it in items) if x]
                yield page, total_pages, parsed
                if len(items) < OLX_PAGE_SIZE:
                    break
                offset += OLX_PAGE_SIZE

    def parse_item(self, it: dict, offer_type: str) -> Optional[RawListing]:
        sid = it.get("id")
        if sid is None:
            return None
        params: Dict[str, dict] = {}
        for p in it.get("params") or []:
            if isinstance(p, dict) and p.get("key"):
                params[p["key"]] = p
        price_p = (params.get("price") or {}).get("value") or {}
        currency = price_p.get("currency") if isinstance(price_p, dict) else None
        loc = it.get("location") or {}
        names = []
        for key in ("region", "city", "district"):
            v = loc.get(key)
            if isinstance(v, dict) and v.get("name"):
                names.append(v["name"])
        mp = it.get("map") or {}
        user = it.get("user") or {}
        contact = it.get("contact") or {}
        photos = []
        for ph in it.get("photos") or []:
            link = ph.get("link") if isinstance(ph, dict) else None
            if link:
                photos.append(link.replace("{width}", "1000").replace("{height}", "700"))
        chars = {}
        for k, p in params.items():
            v = p.get("value")
            chars[k] = {"label": p.get("name"),
                        "value": (v.get("key") if isinstance(v, dict) and v.get("key") is not None
                                  else (v.get("value") if isinstance(v, dict) else v)),
                        "localized": v.get("label") if isinstance(v, dict) else None}
        business = it.get("business")
        seller_raw = "business:%s" % ("true" if business else "false") if business is not None else None
        return RawListing(
            source=self.name, source_id=str(sid), url=it.get("url") or "",
            offer_type=offer_type,
            title=it.get("title") or u"",
            description=it.get("description") or u"",
            price=_pnum(params, "price"), currency=currency or "PLN",
            price_per_m2=_pnum(params, "price_per_m"),
            czynsz=_pnum(params, "rent"),
            area=_pnum(params, "m"),
            rooms_raw=_pv(params, "rooms"),
            floor_raw=_pv(params, "floor_select"),
            building_type_raw=_pv(params, "builttype"),
            market_raw=_pv(params, "market"),
            furnished_raw=_pv(params, "furniture"),
            location_names=names,
            lat=mp.get("lat"), lon=mp.get("lon"),
            seller_type_raw=seller_raw,
            seller_name=user.get("name") or contact.get("name"),
            seller_id=("user:%s" % user.get("id")) if user.get("id") else None,
            images=photos, image_count=len(photos),
            posted_at=parse_dt(it.get("created_time")),
            refreshed_at=parse_dt(it.get("last_refresh_time")),
            external_url=it.get("external_url") or None,
            characteristics=chars, raw=it, needs_details=False,
        )


def fetcher_log(e: Exception):
    import logging
    logging.getLogger("olx").warning(u"friendly-links не ответил (%s) — беру id из настроек", e)
