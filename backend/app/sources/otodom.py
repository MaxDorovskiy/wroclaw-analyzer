# -*- coding: utf-8 -*-
"""Otodom: выдача и карточка через JSON в <script id="__NEXT_DATA__">.

Имена полей — по описаниям парсеров 2024-2025 и памяти (живой доступ к
площадке из среды разработки был закрыт). Поэтому:
- путь к объявлениям ищется сначала точно (props.pageProps.data.searchAds),
  а при промахе — обходом всего JSON по признаку «список словарей с id и
  площадью/ценой»;
- на карточке читаются и `characteristics` (список key/value/localizedValue),
  и `target` (то же плоско) — что найдётся;
- сырой JSON сохраняется в raw_json, разбор можно повторить без скрапа.
"""
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import geo
from ..config import OTODOM_AD_URL, OTODOM_CITY_ID, OTODOM_PAGE_SIZE, OTODOM_SEARCH
from ..tz import WARSAW
from .base import Page, RawListing, Source, parse_dt

NEXT_RX = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse_local_dt(v: Any) -> Optional[datetime]:
    """Время из ВЫДАЧИ Otodom -> наивный UTC. Выдача пишет польское местное
    время, даже когда ставит «Z»: у одного объявления 18.09.2026 в выдаче
    createdAtFirst="2026-09-18T10:21:14Z" и dateCreated="2026-09-18 10:22:05",
    а в карточке createdAt="2026-09-18T08:21:14Z" и modifiedAt="...T08:22:05Z"
    (карточка — честный UTC, объявлению в тот момент было 2 минуты). Читая
    выдачу как UTC, получали подачу «из будущего» на 1-2 часа, и значение
    прыгало между выдачей и карточкой на каждом прогоне.
    Явное смещение («+02:00») — верим ему."""
    if not v:
        return None
    s = str(v).strip()
    if re.search(r"[+-]\d{2}:?\d{2}$", s):
        return parse_dt(s)
    try:
        wall = datetime.strptime(s[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return parse_dt(s)
    return wall.replace(tzinfo=WARSAW).astimezone(timezone.utc).replace(tzinfo=None)


def extract_next_data(html: str) -> dict:
    m = NEXT_RX.search(html)
    if not m:
        raise ValueError(u"__NEXT_DATA__ не найден — страница не Next.js или блок/капча")
    return json.loads(m.group(1))


def _walk(obj: Any, depth: int = 0):
    """Все словари внутри JSON (в глубину до 14 уровней)."""
    if depth > 14:
        return
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            for d in _walk(v, depth + 1):
                yield d
    elif isinstance(obj, list):
        for v in obj:
            for d in _walk(v, depth + 1):
                yield d


def _is_ad_item(x: Any) -> bool:
    return (isinstance(x, dict) and "id" in x
            and any(k in x for k in ("areaInSquareMeters", "totalPrice", "pricePerSquareMeter", "roomsNumber")))


def find_search_block(data: dict) -> Tuple[List[dict], dict]:
    try:
        block = data["props"]["pageProps"]["data"]["searchAds"]
        return list(block.get("items") or []), dict(block.get("pagination") or {})
    except (KeyError, TypeError):
        pass
    for d in _walk(data):
        items = d.get("items")
        if isinstance(items, list) and items and _is_ad_item(items[0]):
            return items, dict(d.get("pagination") or {})
    return [], {}


def find_ad(data: dict) -> dict:
    try:
        ad = data["props"]["pageProps"]["ad"]
        if isinstance(ad, dict) and ad:
            return ad
    except (KeyError, TypeError):
        pass
    for d in _walk(data):
        if "characteristics" in d and ("description" in d or "target" in d):
            return d
    raise ValueError(u"объявление (pageProps.ad) не найдено")


def flatten_items(items: List[dict]) -> Iterator[dict]:
    """Записи выдачи вместе со свёрнутыми в них квартирами. Otodom прячет квартиры
    застройщика внутрь записи-инвестиции (relatedAds, форма та же — AdvertListItem):
    на стр. 100 продажи 18.09.2026 было 13 записей вместо 72, а остальные 62 квартиры
    лежали в relatedAds двух инвестиций. Без разворота первый прогон собрал 5.4 тыс.
    объявлений из 9.5 тыс.: первые 46 страниц по 73, дальше — по 2-40."""
    for it in items:
        if not isinstance(it, dict):
            continue
        yield it
        for rel in it.get("relatedAds") or []:
            if isinstance(rel, dict):
                yield rel


def _name(v: Any) -> Optional[str]:
    if isinstance(v, dict):
        return v.get("name") or v.get("fullName") or v.get("label")
    return v if isinstance(v, str) else None


def _rg_locations(loc: Optional[dict]) -> List[dict]:
    rg = (loc or {}).get("reverseGeocoding") or {}
    return [l for l in rg.get("locations") or [] if isinstance(l, dict)]


def _loc_names(loc: dict) -> List[str]:
    """Цепочка мест: reverseGeocoding — то, что площадка определила по точке на
    карте (воеводство -> город -> дзельница -> под-район). Адрес — то, что вписал
    продавец (в живой выдаче там только город и воеводство); он идёт запасным
    путём, иначе имя дзельницы из адреса задваивалось бы и читалось как
    одноимённый под-район (см. geo.SAME_NAME_PART)."""
    names = [n for n in (_name(l) for l in _rg_locations(loc)) if n]
    if names:
        return names
    addr = (loc or {}).get("address") or {}
    for key in ("province", "city", "district", "subdistrict", "quarter"):
        n = _name(addr.get(key))
        if n:
            names.append(n)
    return names


def outside_city(loc: Optional[dict]) -> bool:
    """Точка объявления — не во Вроцлаве. Продавцы пригородов вписывают город
    «Wrocław», чтобы попасть в городскую выдачу, но reverseGeocoding честен:
    county «wrocławski» -> commune «Siechnice» -> «Iwiny» вместо
    dolnoslaskie/wroclaw/wroclaw/wroclaw. В первом прогоне таких 0.6%, медиана
    11.7 тыс. zł/м² против 13.6 тыс. в городе: без дзельницы они сравнивались с
    общегородским пулом и получали ложную «скидку» ~14% — прямо в топ выгодных.
    Судим только по ПОЛОЖИТЕЛЬНОМУ признаку — записи уровня city_or_village: нет
    её (нет reverseGeocoding, площадка переименовала уровни) — объявление
    остаётся. Обратное правило («нет id города — значит, не город») при смене
    формата молча обнулило бы весь источник, а через 3 дня — и каталог."""
    for l in _rg_locations(loc):
        if (l.get("locationLevel") or "").lower() == "city_or_village":
            return l.get("id") != OTODOM_CITY_ID and geo.norm(_name(l)) != "wroclaw"
    return False


def _street(loc: dict) -> Optional[str]:
    addr = (loc or {}).get("address") or {}
    st = addr.get("street")
    if isinstance(st, dict):
        name = st.get("name")
        num = st.get("number")
        if name:
            return (u"%s %s" % (name, num)).strip() if num else name
        return None
    return st if isinstance(st, str) else None


def _val(x: Any) -> Optional[float]:
    if isinstance(x, dict):
        x = x.get("value")
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _seller(is_private: Any, agency: Optional[dict], owner: Optional[dict] = None) -> str:
    t = ((owner or {}).get("type") or (agency or {}).get("type") or "").upper()
    if is_private or t == "PRIVATE":
        return "private"
    if t == "DEVELOPER":
        return "developer"
    return "agency"


def _listify(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None]
    if isinstance(v, str):
        return [p for p in re.split(r"[;|,]|::", v) if p.strip()]
    return [str(v)]


class Otodom(Source):
    name = "otodom"
    needs_details = True

    def iter_pages(self, offer_type: str, fetcher, start_page: int = 1,
                   settings: Optional[Dict[str, str]] = None) -> Iterator[Page]:
        base = OTODOM_SEARCH[offer_type]
        page = start_page
        while True:
            html = fetcher.get_html(base, params={
                "limit": OTODOM_PAGE_SIZE, "page": page, "by": "LATEST",
                "direction": "DESC", "viewType": "listing"})
            if page == start_page:
                fetcher.dump("otodom_%s_page%d.html" % (offer_type, page), html)
            data = extract_next_data(html)
            items, pagination = find_search_block(data)
            total_pages = 0
            try:
                total_pages = int(pagination.get("totalPages") or 0)
            except (TypeError, ValueError):
                total_pages = 0
            parsed = [x for x in (self.parse_item(it, offer_type) for it in flatten_items(items)) if x]
            yield page, (total_pages or page), parsed
            if not items or (total_pages and page >= total_pages):
                break
            page += 1

    def parse_item(self, it: dict, offer_type: str) -> Optional[RawListing]:
        sid = it.get("id")
        if sid is None:
            return None
        # estate="INVESTMENT" — инвестиция целиком (живой ответ 18.09.2026: цена, площадь,
        # комнаты и этаж = null, есть только priceFromPerSquareMeter и диапазоны). Её
        # квартиры идут в той же выдаче отдельными FLAT с developmentId; сама инвестиция —
        # отдельная сущность (DEFERRED §5), в каталоге квартир она была бы пустой строкой
        # и зря тратила бы карточку в хвосте.
        if (it.get("estate") or "FLAT") != "FLAT":
            self.skipped["investment"] = self.skipped.get("investment", 0) + 1
            return None
        if outside_city(it.get("location")):
            self.skipped["outside"] = self.skipped.get("outside", 0) + 1
            return None
        slug = it.get("slug") or ""
        # без slug адрес не построить: код в URL не выводится из числового id
        url = OTODOM_AD_URL.format(slug=slug) if slug else (it.get("url") or u"")
        loc = it.get("location") or {}
        agency = it.get("agency") or {}
        total = it.get("totalPrice") or {}
        images = []
        for im in it.get("images") or []:
            if isinstance(im, dict):
                u = im.get("large") or im.get("medium") or im.get("small")
                if u:
                    images.append(u)
            elif isinstance(im, str):
                images.append(im)
        r = RawListing(
            source=self.name, source_id=str(sid), url=url, offer_type=offer_type,
            title=it.get("title") or u"",
            price=_val(total),
            currency=(total.get("currency") if isinstance(total, dict) else None) or "PLN",
            price_per_m2=_val(it.get("pricePerSquareMeter")),
            # у аренды rentPrice — это czynsz «dodatkowo», у продажи его нет. 0 = поле не
            # заполнено (в живой выдаче аренды: null — 16 из 73, value=0 — 4): «0 zł» в
            # карточке читалось бы как «платежей нет», а это неизвестно
            czynsz=(_val(it.get("rentPrice")) or None) if offer_type == "rent" else None,
            hide_price=bool(it.get("hidePrice")),
            area=_val(it.get("areaInSquareMeters")),
            rooms_raw=it.get("roomsNumber"),
            floor_raw=it.get("floorNumber"),
            location_names=_loc_names(loc),
            street=_street(loc),
            seller_type_raw=_seller(it.get("isPrivateOwner"), agency),
            seller_name=agency.get("name") if isinstance(agency, dict) else None,
            seller_id=("agency:%s" % agency.get("id")) if isinstance(agency, dict) and agency.get("id") else None,
            images=images,
            image_count=it.get("totalPossibleImages"),
            # живой ключ — createdAtFirst; dateCreatedFirst оставлен на случай отката имени
            posted_at=parse_local_dt(it.get("createdAtFirst") or it.get("dateCreatedFirst")
                                     or it.get("dateCreated")),
            refreshed_at=parse_local_dt(it.get("pushedUpAt") or it.get("dateCreated")),
            # вложенные объявления идут своими строками — в raw_json родителя они балласт
            raw={k: v for k, v in it.items() if k != "relatedAds"}, needs_details=True,
        )
        if it.get("shortDescription") and not r.description:
            pass  # короткий текст выдачи не заменяет описание — ждём карточку
        return r

    def fetch_details(self, raw: RawListing, fetcher) -> RawListing:
        html = fetcher.get_html(raw.url)
        data = extract_next_data(html)
        ad = find_ad(data)
        return self.apply_ad(raw, ad)

    def apply_ad(self, raw: RawListing, ad: dict) -> RawListing:
        """Переложить карточку в RawListing. Отдельно от fetch_details, чтобы
        тесты и повторный разбор (reparse) шли тем же кодом без сети."""
        chars: Dict[str, Dict[str, Any]] = {}
        for c in ad.get("characteristics") or []:
            if not isinstance(c, dict) or not c.get("key"):
                continue
            chars[c["key"]] = {"label": c.get("label"), "value": c.get("value"),
                               "localized": c.get("localizedValue")}
        target = ad.get("target") or {}

        def cv(key: str, tkey: Optional[str] = None):
            if key in chars and chars[key].get("value") not in (None, ""):
                return chars[key]["value"]
            if tkey and target.get(tkey) not in (None, "", []):
                v = target.get(tkey)
                return v[0] if isinstance(v, list) and len(v) == 1 else v
            return None

        raw.description = ad.get("description") or raw.description or u""
        raw.title = ad.get("title") or raw.title
        raw.characteristics = chars
        raw.area = _val(cv("m", "Area")) or raw.area
        raw.price = _val(cv("price", "Price")) or raw.price
        raw.price_per_m2 = _val(cv("price_per_m", "Price_per_m")) or raw.price_per_m2
        raw.rooms_raw = cv("rooms_num", "Rooms_num") or raw.rooms_raw
        raw.floor_raw = cv("floor_no", "Floor_no") or raw.floor_raw
        raw.floors_total_raw = cv("building_floors_num", "Building_floors_num")
        raw.build_year_raw = cv("build_year", "Build_year")
        raw.market_raw = cv("market", "Market") or ad.get("market")
        raw.building_type_raw = cv("building_type", "Building_type")
        raw.building_material_raw = cv("building_material", "Building_material")
        raw.construction_status_raw = cv("construction_status", "Construction_status")
        raw.ownership_raw = cv("building_ownership", "Building_ownership")
        raw.heating_raw = cv("heating", "Heating")
        raw.windows_raw = cv("windows_type", "Windows_type")
        raw.elevator_raw = cv("lift", "Lift")
        raw.furnished_raw = cv("furniture", "Furniture")
        rent = _val(cv("rent", "Rent"))
        if rent:                       # 0 — «не заполнено», см. parse_item
            raw.czynsz = rent
        raw.extras = _listify(cv("extras_types", "Extras_types")) + _listify(cv("equipment_types", "Equipment_types"))
        raw.media = _listify(cv("media_types", "Media_types"))
        raw.security = _listify(cv("security_types", "Security_types"))
        # текстовые подписи дополнений (balkon, winda, ...) — на случай, если ключей нет
        for f in ad.get("features") or []:
            if isinstance(f, str):
                raw.extras.append(f)
        for cat in ad.get("featuresByCategory") or []:
            for f in (cat or {}).get("values") or []:
                if isinstance(f, str):
                    raw.extras.append(f)

        loc = ad.get("location") or {}
        coords = loc.get("coordinates") or {}
        raw.lat = _val(coords.get("latitude")) or raw.lat
        raw.lon = _val(coords.get("longitude")) or raw.lon
        names = _loc_names(loc)
        if names:
            raw.location_names = names
        raw.street = _street(loc) or raw.street
        addr = loc.get("address") or {}
        if isinstance(addr, dict):
            parts = [_name(addr.get(k)) for k in ("street", "subdistrict", "district", "city")]
            if isinstance(addr.get("street"), dict):
                parts[0] = _street(loc)
            raw.address_raw = u", ".join(p for p in parts if p) or raw.address_raw

        owner = ad.get("owner") or {}
        agency = ad.get("agency") or {}
        raw.seller_type_raw = _seller(False, agency if agency else None, owner)
        if owner.get("type", "").upper() == "PRIVATE":
            raw.seller_type_raw = "private"
        raw.seller_name = (agency.get("name") if agency else None) or owner.get("name") or raw.seller_name
        if agency and agency.get("id"):
            raw.seller_id = "agency:%s" % agency["id"]
        elif owner.get("id"):
            raw.seller_id = "user:%s" % owner["id"]
        phones = owner.get("phones") or agency.get("phones") or []
        if isinstance(phones, list) and phones:
            raw.seller_phone = phones[0] if isinstance(phones[0], str) else str(phones[0])

        imgs = []
        for im in ad.get("images") or []:
            if isinstance(im, dict):
                u = im.get("large") or im.get("medium") or im.get("thumbnail")
                if u:
                    imgs.append(u)
        if imgs:
            raw.images = imgs
            raw.image_count = len(imgs)
        raw.posted_at = parse_dt(ad.get("createdAt")) or raw.posted_at
        raw.refreshed_at = parse_dt(ad.get("pushedUpAt") or ad.get("modifiedAt")) or raw.refreshed_at
        raw.raw = ad
        raw.needs_details = False
        return raw
