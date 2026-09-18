# -*- coding: utf-8 -*-
"""Фикстуры для тестов из ЖИВЫХ ответов площадок, обезличенные.

Когда площадка переименует поля, порядок такой: probe_sources.py кладёт сырые
ответы в %WRO_DATA%/probe, по ним чинится адаптер, а этот скрипт превращает те
же ответы в tests/fixtures/*_live.json — чтобы тесты проверяли разбор на том,
что площадка отдаёт на самом деле, а не на том, что помнит автор.

    .venv/bin/python scripts/make_fixtures.py          # все шесть файлов пробы
    .venv/bin/python scripts/make_fixtures.py --probe D:/other/probe

Что заменяется: id объявлений, продавцов и агентств, имена, телефоны, e-mail,
ссылки, фото, номера домов, точные координаты (до 3 знаков ≈ 100 м). Что
выбрасывается: реклама, трекинг, SEO и прочие блоки, которые адаптер не читает.
ИМЕНА В ТЕКСТЕ ОПИСАНИЙ скрипт не узнаёт («Opiekun oferty Jan Kowalski») —
описания обрезаются до 400 знаков, и результат надо просмотреть глазами
перед коммитом.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import PROBE_DIR  # noqa: E402
from app.console import utf8_stdio  # noqa: E402
from app.sources.otodom import extract_next_data  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
DESC_LIMIT = 400

# телефон: три тройки цифр с любыми разделителями — «602 101 602», «537**178**702»
# (так прячут номер от парсеров); цена «1 250 000» не совпадает — там не три тройки
_PHONE = re.compile(r"(?<!\d)(?:\+?48\W{0,3})?\d{3}\W{0,3}\d{3}\W{0,3}\d{3}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://[^\s\"'<>]+")
# подписи агентов: «Opiekun oferty: Jan Kowalski», «<strong>Opiekun Oferty</strong><br/>Jan Kowalski»
_SIGN = re.compile(u"((?:Opiekun|Agent|Doradca|Pośrednik|Kontakt)[^\\n<:–-]{0,30}(?:<[^>]+>|[\\s:–-])*)"
                   u"([A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż]+\\s+[A-ZŁŚŻŹĆŃÓ][a-ząćęłńóśźż-]+)")
SHORT_STUB = u"(skrócony opis z wyników — adapter go nie czyta, w fiksturze pominięty)"


def scrub(text, limit=None):
    if not text:
        return text
    text = _URL.sub("https://example.invalid", text)
    text = _EMAIL.sub("kontakt@example.invalid", text)
    text = _PHONE.sub("600 100 200", text)
    text = _SIGN.sub(lambda m: m.group(1) + u"Jan Kowalski", text)
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + u" …"
    return text


def _coord(v):
    return round(float(v), 3) if isinstance(v, (int, float)) else v


def _code(n):
    return "ID4test%d" % n


# ---------- Otodom: выдача ----------
def otodom_item(it, n):
    it = json.loads(json.dumps(it))
    new_id = 70000000 + n
    it["id"] = new_id
    it["slug"] = re.sub(r"-ID\w+$", "-" + _code(n), it.get("slug") or "oferta-" + _code(n))
    it["href"] = "[lang]/ad/" + it["slug"]
    it["title"] = scrub(it.get("title"))
    # склейка тегов в shortDescription ломает шаблоны очистки («OfertyJan»), а адаптер поле не читает
    it["shortDescription"] = SHORT_STUB if it.get("shortDescription") else None
    if it.get("agency"):
        a = it["agency"]
        it["agency"] = {"id": 1000 + n, "name": u"Biuro Nieruchomości %d" % n, "type": a.get("type"),
                        "slug": "biuro-%d-ID%d" % (n, 1000 + n), "imageUrl": None,
                        "brandingVisible": a.get("brandingVisible"), "highlightedAds": a.get("highlightedAds"),
                        "__typename": a.get("__typename")}
    if it.get("advertOwner"):
        it["advertOwner"] = {"name": u"Doradca", "imageUrl": None, "__typename": it["advertOwner"].get("__typename")}
    if it.get("organisationAssignedMember"):
        it["organisationAssignedMember"] = {"profileID": str(n), "userID": str(2000 + n), "firstName": "Jan",
                                            "lastName": "Kowalski", "photoURL": None, "mobile": "+48600100200",
                                            "__typename": "OrganisationAssignedMember"}
    it["images"] = [{"medium": "https://example.invalid/otodom/%d-%d-medium.jpg" % (n, i),
                     "large": "https://example.invalid/otodom/%d-%d-large.jpg" % (n, i),
                     "__typename": "AdvertListItemImage"} for i in range(min(2, len(it.get("images") or [])))]
    for k in ("development", "developmentTitle", "developmentUrl", "specialOffer", "relatedAds", "openDays"):
        if k in it:
            it[k] = None
    if it.get("developmentId"):
        it["developmentId"] = 70009000
    street = ((it.get("location") or {}).get("address") or {}).get("street")
    if isinstance(street, dict):
        street["number"] = ""
    return it


def otodom_search(html, picks):
    data = extract_next_data(html)
    sa = data["props"]["pageProps"]["data"]["searchAds"]
    items = sa["items"]
    chosen = []
    for want in picks:
        for it in items:
            if it in chosen:
                continue
            if want(it):
                chosen.append(it)
                break
    out = {"props": {"pageProps": {"data": {"searchAds": {
        "__typename": sa.get("__typename"),
        "items": [otodom_item(it, i + 1) for i, it in enumerate(chosen)],
        "pagination": sa.get("pagination"),
    }}}}}
    return out


# ---------- Otodom: карточка ----------
AD_KEEP = ("id", "publicId", "advertType", "advertiserType", "status", "market", "source", "title", "slug", "url",
           "description", "createdAt", "modifiedAt", "pushedUpAt", "characteristics", "target", "features",
           "featuresByCategory", "featuresWithoutCategory", "additionalInformation", "topInformation",
           "location", "owner", "agency", "contactDetails", "images", "property", "price")


def otodom_ad(ad, n):
    ad = {k: json.loads(json.dumps(ad[k])) for k in AD_KEEP if k in ad}
    ad["id"] = 70000000 + n
    ad["publicId"] = "test%d" % n
    ad["slug"] = re.sub(r"-ID\w+$", "-" + _code(n), ad.get("slug") or "oferta-" + _code(n))
    ad["url"] = "https://www.otodom.pl/pl/oferta/" + ad["slug"]
    ad["title"] = scrub(ad.get("title"))
    ad["description"] = scrub(ad.get("description"), DESC_LIMIT)
    t = ad.get("target") or {}
    for k in ("Photo", "Title"):
        if k in t:
            t[k] = ""
    if "Id" in t:
        t["Id"] = str(ad["id"])
    if "seller_id" in t:
        t["seller_id"] = str(1000 + n)
    owner = ad.get("owner") or {}
    if owner:
        ad["owner"] = {"id": 1000 + n, "type": owner.get("type"), "name": u"Biuro Nieruchomości %d" % n,
                       "phones": ["+48600100200"] if owner.get("phones") else [], "imageUrl": None,
                       "contacts": [{"name": "Jan Kowalski", "phone": "+48600100200", "imageURLSmall": None,
                                     "hasPhoneNumber": True}] if owner.get("contacts") else []}
    agency = ad.get("agency") or {}
    if agency:
        ad["agency"] = {"id": 1000 + n, "name": u"Biuro Nieruchomości %d" % n, "type": agency.get("type"),
                        "slug": "biuro-%d-ID%d" % (n, 1000 + n), "imageUrl": None,
                        "phones": ["+48600100200"] if agency.get("phones") else [],
                        "hasPhoneNumber": agency.get("hasPhoneNumber"), "url": "/pl/firmy/biura-nieruchomosci/biuro-%d" % n}
    cd = ad.get("contactDetails") or {}
    if cd:
        ad["contactDetails"] = {"name": "Jan Kowalski", "type": cd.get("type"),
                                "phones": ["+48600100200"] if cd.get("phones") else [], "imageUrl": None,
                                "hasPhoneNumber": cd.get("hasPhoneNumber")}
    ad["images"] = [{"thumbnail": "https://example.invalid/otodom/ad%d-%d-thumb.jpg" % (n, i),
                     "small": "https://example.invalid/otodom/ad%d-%d-small.jpg" % (n, i),
                     "medium": "https://example.invalid/otodom/ad%d-%d-medium.jpg" % (n, i),
                     "large": "https://example.invalid/otodom/ad%d-%d-large.jpg" % (n, i)}
                    for i in range(min(3, len(ad.get("images") or [])))]
    loc = ad.get("location") or {}
    co = loc.get("coordinates") or {}
    if co:
        co["latitude"], co["longitude"] = _coord(co.get("latitude")), _coord(co.get("longitude"))
    street = (loc.get("address") or {}).get("street")
    if isinstance(street, dict):
        street["number"] = ""
    return {"props": {"pageProps": {"ad": ad}}}


# ---------- OLX ----------
OLX_KEEP = ("id", "url", "title", "last_refresh_time", "created_time", "valid_to_time", "pushup_time", "description",
            "promotion", "params", "key_params", "business", "user", "status", "contact", "map", "location",
            "photos", "partner", "category", "offer_type", "external_url", "protect_phone")


def olx_item(it, n):
    it = {k: json.loads(json.dumps(it[k])) for k in OLX_KEEP if k in it}
    it["id"] = 910000000 + n
    it["url"] = re.sub(r"-ID\w+\.html$", "-IDtest%d.html" % n, it.get("url") or "")
    it["title"] = scrub(it.get("title"))
    it["description"] = scrub(it.get("description"), DESC_LIMIT)
    u = it.get("user") or {}
    it["user"] = {"id": 5000 + n, "name": u"Użytkownik %d" % n, "created": u.get("created"),
                  "other_ads_enabled": u.get("other_ads_enabled"), "logo": None, "photo": None,
                  "company_name": (u"Biuro Nieruchomości %d" % n) if u.get("company_name") else "",
                  "seller_type": u.get("seller_type")}
    c = it.get("contact") or {}
    it["contact"] = {"name": u"Użytkownik %d" % n, "phone": c.get("phone"), "chat": c.get("chat"),
                     "negotiation": c.get("negotiation"), "courier": c.get("courier")}
    it["photos"] = [{"id": 8000 + n * 10 + i, "filename": "test%d-%d" % (n, i), "rotation": 0,
                     "width": p.get("width"), "height": p.get("height"),
                     "link": "https://example.invalid/olx/test%d-%d/image;s={width}x{height}" % (n, i)}
                    for i, p in enumerate((it.get("photos") or [])[:2])]
    if it.get("external_url"):
        it["external_url"] = re.sub(r"-ID\w+", "-" + _code(900 + n), _URL.sub(
            lambda m: m.group(0) if "otodom.pl" in m.group(0) else "https://example.invalid", it["external_url"]))
    for p in it.get("params") or []:
        if p.get("key") == "developer_url":
            p["value"] = {"key": "https://example.invalid", "label": "https://example.invalid"}
    mp = it.get("map") or {}
    if mp:
        mp["lat"], mp["lon"] = _coord(mp.get("lat")), _coord(mp.get("lon"))
    return it


def olx_page(data, picks, next_offset=None):
    items = data.get("data") or []
    chosen = []
    for want in picks:
        for it in items:
            if it in chosen:
                continue
            if want(it):
                chosen.append(it)
                break
    meta = data.get("metadata") or {}
    out = {"data": [olx_item(it, i + 1) for i, it in enumerate(chosen)],
           "metadata": {k: meta.get(k) for k in ("total_elements", "visible_total_count", "promoted") if k in meta},
           "links": {}}
    links = data.get("links") or {}
    for k in ("self", "next", "first", "previous"):
        if k in links:
            out["links"][k] = links[k]
    return out


def _has_param(it, key):
    return any(p.get("key") == key for p in it.get("params") or [])


def main():
    utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default=str(PROBE_DIR))
    args = ap.parse_args()
    probe = Path(args.probe)
    made = []

    def write(name, obj):
        (FIX / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        made.append(name)

    f = probe / "otodom_sale_page1.html"
    if f.exists():
        write("otodom_search_live.json", otodom_search(f.read_text(encoding="utf-8"), [
            lambda it: it.get("estate") == "FLAT" and (it.get("agency") or {}).get("type") == "AGENCY",
            lambda it: it.get("estate") == "FLAT" and it.get("isPrivateOwner"),
            lambda it: it.get("estate") == "FLAT" and (it.get("agency") or {}).get("type") == "DEVELOPER",
            lambda it: it.get("estate") == "INVESTMENT",
        ]))
    f = probe / "otodom_rent_page1.html"
    if f.exists():
        write("otodom_search_rent_live.json", otodom_search(f.read_text(encoding="utf-8"), [
            lambda it: (it.get("rentPrice") or {}).get("value"),
            lambda it: it.get("rentPrice") is None,
            lambda it: it.get("rentPrice") is not None and not it["rentPrice"].get("value"),
        ]))
    for kind in ("sale", "rent"):
        f = probe / ("otodom_%s_ad.json" % kind)
        if f.exists():
            write("otodom_ad_%s_live.json" % kind, otodom_ad(json.loads(f.read_text(encoding="utf-8")),
                                                            1 if kind == "sale" else 2))
    f = probe / "olx_sale_page1.json"
    if f.exists():
        write("olx_offers_live.json", olx_page(json.loads(f.read_text(encoding="utf-8")), [
            lambda it: not it.get("business") and (it.get("location") or {}).get("district"),
            lambda it: it.get("business") and it.get("external_url"),
            lambda it: not (it.get("location") or {}).get("district"),
            lambda it: (it.get("promotion") or {}).get("top_ad"),
        ]))
    f = probe / "olx_rent_page1.json"
    if f.exists():
        write("olx_offers_rent_live.json", olx_page(json.loads(f.read_text(encoding="utf-8")), [
            lambda it: _has_param(it, "rent") and _has_param(it, "winda"),
            lambda it: not _has_param(it, "rent"),
        ]))
    if not made:
        print(u"в %s нет файлов пробы — сначала scripts/probe_sources.py (sale и rent)" % probe)
        sys.exit(1)
    print(u"записано в %s:" % FIX)
    for name in made:
        print(u"  %s (%.1f КБ)" % (name, (FIX / name).stat().st_size / 1024.0))
    print(u"\nПЕРЕД КОММИТОМ просмотрите описания глазами: имена внутри текста скрипт узнаёт\n"
          u"только в типовых подписях («Opiekun oferty …»), остальное — на вашей совести.")


if __name__ == "__main__":
    main()
