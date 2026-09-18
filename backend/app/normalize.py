# -*- coding: utf-8 -*-
"""Из RawListing (как отдал источник) — в поля Listing (как храним).

Здесь живут ВСЕ правила приведения, общие для источников: комнаты из
«two»/«2 pokoje»/«THREE», этаж из «floor_3»/«parter»/«GROUND», тип дома из
«blok»/«block»/«kamienica», класс состояния по словам. Правило в одном
месте — значит, чинится один раз для всех.
"""
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

from . import geo
from .config import MAX_AREA, MIN_AREA
from .sources.base import RawListing


def _norm_key(v: Any) -> str:
    if v is None:
        return ""
    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace(u"ł", "l").replace(u"Ł", "L").lower().strip()
    return re.sub(r"[\s\-]+", "_", s)


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(u"\xa0", " ").replace(" ", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _int(v: Any) -> Optional[int]:
    f = _num(v)
    return int(round(f)) if f is not None else None


# ---------- комнаты ----------
_ROOM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "more": 11,
    "jeden": 1, "dwa": 2, "trzy": 3, "cztery": 4, "piec": 5, "szesc": 6,
    "kawalerka": 1,
}


def parse_rooms(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v) if 0 < v < 30 else None
    k = _norm_key(v)
    if k in _ROOM_WORDS:
        return _ROOM_WORDS[k]
    m = re.match(r"(\d+)", k)
    if m:
        n = int(m.group(1))
        return n if 0 < n < 30 else None
    for w, n in _ROOM_WORDS.items():
        if k.startswith(w):
            return n
    return None


# ---------- этаж ----------
# Выдача Otodom отдаёт этаж порядковым словом: в первом прогоне 18.09.2026
# встретились GROUND, FIRST ... TENTH, ABOVE_TENTH, CELLAR (и null);
# карточка и OLX пишут «floor_3».
# Без этой таблицы этаж был пуст у всех объявлений, пока не скачана карточка
# (а хвост — 600 карточек за прогон при ~9.5 тыс. объявлений).
_FLOOR_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def parse_floor(v: Any) -> Optional[int]:
    """0 = parter (польская нумерация), -1 = suterena, 11 = «выше 10».
    «poddasze» (чердачный) — None: этажа как числа у него нет."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    k = _norm_key(v)
    if k in _FLOOR_WORDS:
        return _FLOOR_WORDS[k]
    if k in ("ground", "parter", "floor_0", "0", "ground_floor"):
        return 0
    if k in ("cellar", "suterena", "floor_-1", "-1", "floor__1", "basement"):
        return -1
    if k in ("garret", "poddasze", "floor_poddasze", "attic"):
        return None
    if k in ("floor_higher_10", "floor_11", "higher_10", "powyzej_10", "11+", ">10",
             "above_tenth", "above_10"):
        return 11
    m = re.search(r"(-?\d+)", k)
    return int(m.group(1)) if m else None


# ---------- рынок ----------
def parse_market(v: Any) -> Optional[str]:
    k = _norm_key(v)
    if not k:
        return None
    if "pierwotn" in k or k.startswith("primary"):
        return "primary"
    if "wtorn" in k or k.startswith("secondary"):
        return "secondary"
    return None


# ---------- тип дома, материал, статус, собственность, отопление, окна ----------
_BUILDING = {
    "block": "block", "blok": "block", "blok_mieszkalny": "block",
    "tenement": "tenement", "kamienica": "tenement",
    "apartment": "apartment", "apartamentowiec": "apartment", "apartment_building": "apartment",
    "house": "house", "dom": "house", "dom_wolnostojacy": "house", "dom_wolnostojacy_": "house",
    "wolnostojacy": "house",          # так пишет OLX (builttype), без «dom_»
    "infill": "infill", "plomba": "infill",
    "ribbon": "ribbon", "szeregowiec": "ribbon", "dom_szeregowy": "ribbon",
    "loft": "loft",
    "other": "other", "pozostale": "other", "inne": "other",
}
_MATERIAL = {
    "brick": "brick", "cegla": "brick",
    "concrete_plate": "concrete_plate", "wielka_plyta": "concrete_plate", "plyta": "concrete_plate",
    "silikat": "silikat",
    "breezeblock": "breezeblock", "pustak": "breezeblock",
    "cellular_concrete": "cellular_concrete", "beton_komorkowy": "cellular_concrete",
    "reinforced_concrete": "reinforced_concrete", "zelbet": "reinforced_concrete",
    "concrete": "concrete", "beton": "concrete",
    "wood": "wood", "drewno": "wood",
    "hydroton": "hydroton", "keramzyt": "hydroton",
    "other": "other", "inne": "other",
}
_STATUS = {
    "ready_to_use": "ready_to_use", "do_zamieszkania": "ready_to_use",
    "to_completion": "to_completion", "do_wykonczenia": "to_completion",
    "to_renovation": "to_renovation", "do_remontu": "to_renovation",
}
_OWNERSHIP = {
    "full_ownership": "full_ownership", "pelna_wlasnosc": "full_ownership", "wlasnosc": "full_ownership",
    "limited_ownership": "limited_ownership", "spoldzielcze_wlasnosciowe": "limited_ownership",
    "spoldzielcze_wl_prawo_do_lokalu": "limited_ownership",
    "co_operative": "co_operative", "spoldzielcze_lokatorskie": "co_operative",
    "share": "share", "udzial": "share",
    "usufruct": "usufruct", "uzytkowanie_wieczyste": "usufruct",
}
_HEATING = {
    "urban": "urban", "miejskie": "urban",
    "gas": "gas", "gazowe": "gas",
    "electric": "electric", "elektryczne": "electric",
    "boiler_room": "boiler_room", "kotlownia": "boiler_room",
    "tiled_stove": "tiled_stove", "piece_kaflowe": "tiled_stove",
    "heat_pump": "heat_pump", "pompa_ciepla": "heat_pump",
    "coal": "coal", "weglowe": "coal",
    "other": "other", "inne": "other",
}
_WINDOWS = {
    "plastic": "plastic", "plastikowe": "plastic", "pcv": "plastic",
    "wooden": "wooden", "drewniane": "wooden",
    "aluminium": "aluminium", "aluminiowe": "aluminium",
}
_SELLER = {
    "private": "private", "osoba_prywatna": "private", "prywatny": "private",
    "agency": "agency", "biuro_nieruchomosci": "agency", "agencja": "agency",
    "developer": "developer", "deweloper": "developer",
}


def _map(table: Dict[str, str], v: Any) -> Optional[str]:
    k = _norm_key(v)
    if not k:
        return None
    if k in table:
        return table[k]
    for key, val in table.items():
        if k.startswith(key) or key in k:
            return val
    return None


def parse_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    k = _norm_key(v)
    if k in ("yes", "tak", "true", "1", "y"):
        return True
    if k in ("no", "nie", "false", "0", "n"):
        return False
    return None


# ---------- класс состояния по словам ----------
# Порядок важен: сначала СИЛЬНЫЕ негативные признаки, потом позитивные — иначе
# «po remoncie kuchni, reszta do remontu» уйдёт в «renovated».
_RX_TO_RENOVATE = re.compile(
    u"do (generalnego |kapitalnego |gruntownego |całkowitego |pełnego )?remontu|"
    u"wymaga (generalnego |kapitalnego )?remontu|stan do remontu|do kompletnego remontu",
    re.I)
_RX_TO_REFRESH = re.compile(
    u"do od[sś]wie[żz]enia|do odnowienia|wymaga od[sś]wie[żz]enia|do lekkiego remontu|"
    u"do drobnego remontu|do drobnych poprawek|wymaga drobnego remontu", re.I)
_RX_DEVELOPER = re.compile(
    u"stan(ie)? deweloperski|standard deweloperski|do wyko[ńn]czenia|"
    u"do samodzielnego wyko[ńn]czenia|deweloperskim", re.I)
_RX_RENOVATED = re.compile(
    u"po (generalnym |kapitalnym |gruntownym |całkowitym |pełnym |świeżym |niedawnym )?remoncie|"
    u"wyko[ńn]czone|w pełni wyko[ńn]czone|gotowe do zamieszkania|gotowe do wprowadzenia|"
    u"wysoki standard|wysokim standardzie|pod klucz|świeżo wyremontowane|wyremontowane|"
    u"po kapitalnym|kompletnie urządzone|w pełni umeblowane|nowe wyko[ńn]czenie|"
    u"odnowione|odświeżone|po odświeżeniu", re.I)


def classify_condition(construction_status: Optional[str], market: Optional[str],
                       title: str, description: Optional[str]):
    """-> (class, src). Структурная метка сильнее слов, но слова уточняют её."""
    text = u" ".join(x for x in (title or u"", description or u"") if x)
    if _RX_TO_RENOVATE.search(text):
        return "to_renovate", "text"
    if construction_status == "to_renovation":
        return "to_renovate", "status"
    if _RX_DEVELOPER.search(text):
        return "developer_bare", "text"
    if construction_status == "to_completion":
        return "developer_bare", "status"
    if _RX_TO_REFRESH.search(text):
        return "to_refresh", "text"
    if _RX_RENOVATED.search(text):
        return "renovated", "text"
    if construction_status == "ready_to_use":
        # у первички «do zamieszkania» обычно значит «с отделкой от застройщика»
        return "renovated", "status"
    return "unknown", "auto"


def clean_phone(v: Any) -> Optional[str]:
    """«+48 600 100 200», «600-100-200», «48600100200» -> «+48600100200»."""
    if not v:
        return None
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
        if not v:
            return None
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 9:
        digits = "48" + digits
    if len(digits) < 9 or len(digits) > 15:
        return None
    return "+" + digits


# Польские подписи дополнений (Otodom features / OLX) -> канонические ключи EXTRAS
_EXTRAS_PL = {
    "balkon": "balcony", "taras": "terrace", "ogrodek": "garden", "ogrod": "garden",
    "garaz": "garage", "garaz_miejsce_parkingowe": "garage", "miejsce_parkingowe": "garage",
    "winda": "lift", "piwnica": "basement", "pom_uzytkowe": "usable_room",
    "oddzielna_kuchnia": "separate_kitchen", "dwupoziomowe": "two_storey",
    "klimatyzacja": "air_conditioning", "strych": "attic", "meble": "furniture",
    "zmywarka": "dishwasher", "lodowka": "fridge", "piekarnik": "oven", "kuchenka": "stove",
    "pralka": "washing_machine", "telewizor": "tv", "internet": "internet",
    "telewizja_kablowa": "cable_television", "telefon": "phone", "prad": "electricity",
    "woda": "water", "kanalizacja": "sewage", "gaz": "gas",
    "drzwi_antywlamaniowe": "anti_burglary_door", "drzwi_okna_antywlamaniowe": "anti_burglary_door",
    "domofon_wideofon": "entryphone", "domofon": "entryphone",
    "monitoring_ochrona": "monitoring", "monitoring": "monitoring",
    "teren_zamkniety": "closed_area", "system_alarmowy": "alarm",
    "rolety_antywlamaniowe": "roller_shutters",
}


def canon_extra(x: Any) -> str:
    k = re.sub(r"_+", "_", _norm_key(x).replace("/", "_").replace(".", ""))
    return _EXTRAS_PL.get(k, k)


def parse_seller(raw: RawListing) -> Optional[str]:
    # OLX даёт только флаг business; «business:false» = частник, и разбирать его
    # надо ДО таблицы синонимов, иначе подстрока «business» уводит в агентство
    if raw.seller_type_raw in ("business:true", "business:false"):
        return "agency" if raw.seller_type_raw.endswith("true") else "private"
    return _map(_SELLER, raw.seller_type_raw)


def _clean_text(s: Optional[str]) -> Optional[str]:
    """HTML описания Otodom -> текст с переносами строк."""
    if not s:
        return s
    if "<" in s and ">" in s:
        s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.I)
        s = re.sub(r"</\s*(p|div|li|h\d)\s*>", "\n", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s)
        s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
              .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def normalize(raw: RawListing) -> Dict[str, Any]:
    """Поля Listing из сырого объявления. Не трогает то, что источник не дал
    (None), — чтобы хвост с карточкой не затирал уже известное."""
    d: Dict[str, Any] = {
        "source": raw.source, "source_id": str(raw.source_id), "url": raw.url,
        "offer_type": raw.offer_type, "external_url": raw.external_url,
    }
    d["title_pl"] = (raw.title or u"").strip() or None
    if raw.description is not None:
        d["description_pl"] = _clean_text(raw.description)

    area = _num(raw.area)
    if area is not None and not (MIN_AREA <= area <= MAX_AREA):
        area = None          # «повierzchnia 1 m²» и участки — не квартиры
    d["area"] = area
    price = _num(raw.price)
    if raw.currency and raw.currency.upper() != "PLN":
        price = None         # редкие EUR-объявления: без курса не сравнить, пропускаем цену
    d["price_pln"] = price
    d["hide_price"] = bool(raw.hide_price)
    ppm = _num(raw.price_per_m2)
    if ppm is None and price and area:
        ppm = price / area
    d["price_per_m2"] = round(ppm, 2) if ppm else None
    d["czynsz_pln"] = _num(raw.czynsz)

    d["rooms"] = parse_rooms(raw.rooms_raw)
    d["floor"] = parse_floor(raw.floor_raw)
    d["floors_total"] = _int(raw.floors_total_raw)
    by = _int(raw.build_year_raw)
    d["build_year"] = by if by and 1800 <= by <= 2035 else None
    d["market"] = parse_market(raw.market_raw)
    d["building_type"] = _map(_BUILDING, raw.building_type_raw)
    d["building_material"] = _map(_MATERIAL, raw.building_material_raw)
    d["construction_status"] = _map(_STATUS, raw.construction_status_raw)
    d["ownership"] = _map(_OWNERSHIP, raw.ownership_raw)
    d["heating"] = _map(_HEATING, raw.heating_raw)
    d["windows"] = _map(_WINDOWS, raw.windows_raw)
    d["elevator"] = parse_bool(raw.elevator_raw)
    if d["elevator"] is None and any(canon_extra(x) == "lift" for x in raw.extras):
        d["elevator"] = True
    d["furnished"] = parse_bool(raw.furnished_raw)
    if d["furnished"] is None and any(canon_extra(x) in ("furniture", "umeblowane") for x in raw.extras):
        d["furnished"] = True
    d["extras_json"] = json.dumps(sorted(set(canon_extra(x) for x in raw.extras if x)), ensure_ascii=False)
    d["media_json"] = json.dumps(sorted(set(canon_extra(x) for x in raw.media if x)), ensure_ascii=False)
    d["security_json"] = json.dumps(sorted(set(canon_extra(x) for x in raw.security if x)), ensure_ascii=False)
    if raw.characteristics:
        d["characteristics_json"] = json.dumps(raw.characteristics, ensure_ascii=False)

    cond, src = classify_condition(d["construction_status"], d["market"],
                                   d["title_pl"] or u"", d.get("description_pl"))
    d["condition"], d["condition_src"] = cond, src

    district, osiedle, unknown = geo.resolve(raw.location_names)
    d["district"], d["osiedle"] = district, osiedle
    d["_unknown_places"] = unknown
    d["street"] = (raw.street or None)
    d["lat"], d["lon"] = raw.lat, raw.lon
    d["address_raw"] = raw.address_raw
    d["location_raw"] = u" | ".join(x for x in raw.location_names if x) or None

    d["seller_type"] = parse_seller(raw)
    d["seller_name"] = raw.seller_name
    d["seller_id"] = raw.seller_id
    d["seller_phone"] = clean_phone(raw.seller_phone)
    d["no_commission"] = raw.no_commission
    d["images_json"] = json.dumps(raw.images[:40], ensure_ascii=False)
    d["first_image"] = raw.images[0] if raw.images else None
    d["image_count"] = raw.image_count if raw.image_count is not None else len(raw.images)
    d["posted_at"] = raw.posted_at
    d["refreshed_at"] = raw.refreshed_at
    if raw.raw is not None:
        d["raw_json"] = json.dumps(raw.raw, ensure_ascii=False)
    return d
