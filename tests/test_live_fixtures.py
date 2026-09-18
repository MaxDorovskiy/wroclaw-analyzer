# -*- coding: utf-8 -*-
"""Разбор на ЖИВЫХ ответах площадок (18.09.2026, обезличены scripts/make_fixtures.py).

Старые фикстуры (otodom_search.json и др.) писались по памяти и расходились с
площадками: этаж «FLOOR_2» вместо «SECOND», dateCreatedFirst вместо
createdAtFirst, без рекламных вставок OLX. Они остаются для сценариев (дубли,
история цен), а форму ответа проверяют эти.
"""
import copy
import json
import re
from datetime import datetime

import httpx

from app import fetcher as fetcher_mod
from app.fetcher import Fetcher, fingerprint_blocked, looks_blocked
from app.normalize import normalize, parse_floor
from app.sources.olx import Olx, next_offset
from app.sources.otodom import Otodom, find_search_block, parse_local_dt


def _json(fixtures, name):
    return json.loads((fixtures / name).read_text(encoding="utf-8"))


# ---------- Otodom ----------
def test_otodom_live_search(fixtures):
    items, pagination = find_search_block(_json(fixtures, "otodom_search_live.json"))
    assert len(items) == 3 and pagination["totalPages"] == 132
    raws = [Otodom().parse_item(it, "sale") for it in items]
    # инвестиция целиком (estate=INVESTMENT: ни цены, ни площади) — не квартира
    assert items[2]["estate"] == "INVESTMENT" and raws[2] is None
    a = normalize(raws[0])
    assert a["price_pln"] == 579000 and a["area"] == 57 and a["rooms"] == 3
    assert a["floor"] == 0                                   # "GROUND"
    assert a["district"] == "Fabryczna" and a["osiedle"] == u"Pilczyce-Kozanów-Popowice Płn."
    assert a["_unknown_places"] == []                        # «Popowice Północne» узнаётся по таблице частей
    assert a["seller_type"] == "agency" and a["seller_id"] == "agency:1001"
    assert a["condition"] == "to_renovate"                   # «Do remontu» в заголовке
    assert a["url"].endswith("-ID4test1") and a["image_count"] == 6
    # выдача пишет польское местное время (даже с «Z») — в базе должен быть UTC
    assert items[0]["createdAtFirst"] == "2026-09-18T10:34:53Z"
    assert a["posted_at"] == datetime(2026, 9, 18, 8, 34, 53)
    b = normalize(raws[1])
    assert b["floor"] == 6 and b["seller_type"] == "private" and b["seller_id"] is None   # "SIXTH", частник без agency
    assert b["osiedle"] == u"Gądów-Popowice Płd." and b["street"] == "bulw. Dedala"


def test_otodom_live_ad(fixtures):
    items, _ = find_search_block(_json(fixtures, "otodom_search_live.json"))
    raw = Otodom().parse_item(items[0], "sale")
    listed = raw.posted_at
    ad = _json(fixtures, "otodom_ad_sale_live.json")["props"]["pageProps"]["ad"]
    d = normalize(Otodom().apply_ad(raw, ad))
    # карточка (честный UTC) и выдача (местное) дают одно и то же время — значение не «прыгает»
    assert ad["createdAt"] == "2026-09-18T08:34:53Z" and d["posted_at"] == listed
    assert d["floor"] == 0 and d["floors_total"] == 4 and d["build_year"] == 1980
    assert d["market"] == "secondary" and d["building_type"] == "block"
    assert d["building_material"] == "concrete_plate" and d["windows"] == "wooden"
    assert d["ownership"] == "limited_ownership" and d["heating"] == "urban"
    assert d["construction_status"] == "to_renovation" and d["condition"] == "to_renovate"
    assert d["czynsz_pln"] == 450 and d["seller_phone"] == "+48600100200"
    assert d["lat"] == 51.128 and d["lon"] == 16.991
    assert {"balcony", "basement", "garage", "separate_kitchen"} <= set(json.loads(d["extras_json"]))
    assert json.loads(d["security_json"]) == ["entryphone"]
    assert "<" not in d["description_pl"] and d["description_pl"].startswith(u"Słoneczne 3 pokoje")


def test_otodom_live_rent(fixtures):
    items, _ = find_search_block(_json(fixtures, "otodom_search_rent_live.json"))
    ds = [normalize(Otodom().parse_item(it, "rent")) for it in items]
    assert [d["floor"] for d in ds] == [3, 4, 0]             # THIRD, FOURTH, GROUND
    # czynsz: 850 / null / value=0 — ноль значит «не заполнено», а не «платежей нет»
    assert [d["czynsz_pln"] for d in ds] == [850, None, None]
    assert ds[1]["osiedle"] == "Nadodrze" and ds[2]["osiedle"] == u"Powstańców Śląskich"
    raw = Otodom().parse_item(items[0], "rent")
    ad = _json(fixtures, "otodom_ad_rent_live.json")["props"]["pageProps"]["ad"]
    d = normalize(Otodom().apply_ad(raw, ad))
    assert d["czynsz_pln"] == 850 and d["elevator"] is True and d["market"] is None
    assert d["condition"] == "renovated" and d["condition_src"] == "status"
    chars = json.loads(d["characteristics_json"])
    assert chars["deposit"]["value"] == "3250" and "free_from" in chars


def test_floor_words_and_local_time():
    assert [parse_floor(x) for x in ("GROUND", "FIRST", "EIGHTH", "TENTH", "ABOVE_TENTH", "CELLAR", "GARRET")] == \
        [0, 1, 8, 10, 11, -1, None]
    assert parse_floor("floor_3") == 3 and parse_floor("FLOOR_2") == 2 and parse_floor("parter") == 0
    # лето: Варшава = UTC+2, зима: UTC+1; явному смещению верим
    assert parse_local_dt("2026-09-18T10:21:14Z") == datetime(2026, 9, 18, 8, 21, 14)
    assert parse_local_dt("2026-09-18 10:22:05") == datetime(2026, 9, 18, 8, 22, 5)
    assert parse_local_dt("2026-01-15 10:00:00") == datetime(2026, 1, 15, 9, 0, 0)
    assert parse_local_dt("2026-09-17T22:15:14+02:00") == datetime(2026, 9, 17, 20, 15, 14)
    assert parse_local_dt(None) is None and parse_local_dt("") is None


# ---------- OLX ----------
def test_olx_live_sale(fixtures):
    data = _json(fixtures, "olx_offers_live.json")
    ds = [normalize(Olx().parse_item(it, "sale")) for it in data["data"]]
    a, b, c = ds
    assert a["price_pln"] == 257700 and a["area"] == 17.1 and a["rooms"] == 1 and a["floor"] == 0
    assert a["market"] == "secondary" and a["building_type"] == "block" and a["furnished"] is True
    assert a["district"] == "Krzyki" and a["osiedle"] is None and a["seller_type"] == "private"
    assert a["first_image"].endswith(";s=1000x700") and a["seller_phone"] is None   # телефон OLX в выдаче не отдаёт
    assert a["posted_at"] == datetime(2026, 4, 8, 19, 2, 30)                        # 21:02:30+02:00
    assert "<" not in a["description_pl"]
    assert b["seller_type"] == "agency" and "otodom.pl/pl/oferta/" in b["external_url"]
    assert c["district"] is None and c["_unknown_places"] == []                     # бывает и без дзельницы
    assert next_offset(data) is None


def test_olx_live_rent(fixtures):
    data = _json(fixtures, "olx_offers_rent_live.json")
    a, b = [normalize(Olx().parse_item(it, "rent")) for it in data["data"]]
    assert a["price_pln"] == 1600 and a["czynsz_pln"] == 300 and b["czynsz_pln"] is None
    assert a["elevator"] is False and a["building_type"] == "tenement" and a["market"] is None
    assert a["condition"] == "renovated"                                             # «po remoncie» в заголовке
    # сдвиг следующей страницы считает API: после offset=0 идёт 37, а не 40
    assert next_offset(data) == 37


class _FakeFetcher:
    """Отвечает как API OLX: friendly-links, счётчик (limit=1) и страницы по offset."""

    def __init__(self, pages, total):
        self.pages, self.total, self.calls = pages, total, []

    def get_json(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if "friendly-links" in url:
            assert url.endswith("/nieruchomosci,mieszkania,sprzedaz,wroclaw/")   # через запятую, иначе 404
            return {"data": {"category_id": 14, "region_id": 3, "city_id": 19701}}
        if params.get("limit") == 1:
            return {"data": [], "metadata": self.total}
        return self.pages[params["offset"]]

    def dump(self, name, text):
        pass


def test_olx_pages_follow_next_and_skip_promoted_repeats(fixtures):
    items = _json(fixtures, "olx_offers_live.json")["data"]
    promo = copy.deepcopy(items[0])
    promo["id"], promo["promotion"] = 910000099, {"top_ad": True}
    href = "https://www.olx.pl/api/v1/offers?category_id=14&city_id=19701&limit=40&offset=%d"
    pages = {
        0: {"data": [promo, items[0], items[1]], "links": {"next": {"href": href % 39}}},
        39: {"data": [promo, items[2]], "links": {}},
    }
    f = _FakeFetcher(pages, {"total_elements": 45, "visible_total_count": 45})
    got = list(Olx().iter_pages("sale", f, 1, {"olx_category_sale": "1", "olx_city_id": "1"}))
    assert [[r.source_id for r in parsed] for _, _, parsed in got] == \
        [["910000099", "910000001", "910000002"], ["910000003"]]        # рекламный повтор отсечён
    offsets = [p["offset"] for _, p in f.calls if p.get("limit") == 40]
    assert offsets == [0, 39]                                           # шаг — из links.next, не +40
    assert all(p["category_id"] == 14 and p["city_id"] == 19701 for _, p in f.calls if "offset" in p)


def test_olx_total_ignores_capped_counter():
    # живой ответ: total_elements=1000 (потолок), visible_total_count=1865 (правда)
    f = _FakeFetcher({}, {"total_elements": 1000, "visible_total_count": 1865})
    assert Olx()._total(f, {"category_id": 14, "city_id": 19701}, None, None) == 1865
    bands = Olx()._bands(f, {"category_id": 14, "city_id": 19701}, "sale")
    assert len(bands) > 1                                               # выдача дробится по цене


# ---------- fetcher: блок по отпечатку клиента ----------
_CF_BODY = u"<HTML><H1>403 ERROR</H1>Request blocked. We can't connect to the server for this app</HTML>"


def _cf_403(request):
    return httpx.Response(403, text=_CF_BODY, request=request,
                          headers={"server": "CloudFront", "x-cache": "Error from cloudfront",
                                   "content-type": "text/html"})


def test_fingerprint_block_switches_host_to_browser(monkeypatch):
    req = httpx.Request("GET", "https://www.olx.pl/api/v1/offers/")
    assert fingerprint_blocked(_cf_403(req)) and looks_blocked(_cf_403(req))
    assert not fingerprint_blocked(httpx.Response(403, text="datadome", request=req, headers={"x-datadome": "1"}))
    f = Fetcher(rpm=600)
    monkeypatch.setattr(f, "_throttle", lambda: None)
    monkeypatch.setattr(fetcher_mod.time, "sleep", lambda s: None)
    httpx_calls, browser_calls = [], []

    def fake_httpx_get(url, params=None, headers=None):
        httpx_calls.append(url)
        return _cf_403(httpx.Request("GET", url))

    def fake_browser_get(url, params=None, json_api=False):
        browser_calls.append((url, json_api))
        return httpx.Response(200, text='{"data": [1]}', request=httpx.Request("GET", url))

    monkeypatch.setattr(f.client, "get", fake_httpx_get)
    monkeypatch.setattr(f, "browser_get", fake_browser_get)
    url = "https://www.olx.pl/api/v1/offers/"
    assert f.get_json(url, {"offset": 0}) == {"data": [1]}
    assert f.get_json(url, {"offset": 40}) == {"data": [1]}
    # первый запрос: httpx -> 403 -> сразу браузер, без минутной паузы; второй — уже только браузер
    assert len(httpx_calls) == 1 and len(browser_calls) == 2 and all(j for _, j in browser_calls)
    assert f.stats["blocked"] == 1 and f.stats["requests"] == 2
    f.close()


# ---------- скрипты деплоя ----------
def test_windows_scripts_are_readable_by_powershell51(fixtures):
    """Без BOM Windows PowerShell 5.1 читает .ps1 в ANSI: байты 0x93/0x94 из UTF-8
    («ф», «Д», «—») становятся «умными кавычками», а они для парсера — кавычки.
    18.09.2026 так не разбирались install/safe_restart/scrape_trigger."""
    scripts = sorted((fixtures.parent.parent / "deploy" / "windows").glob("*.ps1"))
    assert len(scripts) >= 5
    for p in scripts:
        raw = p.read_bytes()
        if any(b > 127 for b in raw):
            assert raw.startswith(b"\xef\xbb\xbf"), u"%s: не-ASCII без BOM" % p.name
        # $args — автоматическая переменная: параметр с таким именем приходит пустым
        assert not re.search(r"function\s+\S+\s*\([^)]*\$args\b", raw.decode("utf-8-sig"), re.I), p.name
