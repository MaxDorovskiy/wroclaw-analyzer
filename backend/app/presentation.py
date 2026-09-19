# -*- coding: utf-8 -*-
"""PDF-подборка объявлений для клиента: Юлия отбирает квартиры и шлёт файл.

Почему Chromium, а не библиотека PDF: он уже стоит для обхода анти-бота OLX,
умеет верстать по CSS, тянет фотографии прямо с CDN площадок и сам решает
вопрос шрифтов — в файле и украинский, и польские диакритики. Своя вёрстка на
reportlab потребовала бы возиться со шрифтами и ставить ещё одну зависимость.

Язык выбирает отправитель: клиенту-украинцу — перевод, клиенту-поляку —
оригинал с площадки (перевод ему не нужен и выглядел бы странно).
Контакты в файле — ОТПРАВИТЕЛЯ (`user_profiles`), а не продавца объявления.
"""
import html
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .tz import to_kyiv

log = logging.getLogger("presentation")

MAX_ITEMS = 30          # больше — файл на десятки мегабайт и минуты рендера
PHOTOS_PER_ITEM = 3
DESC_CHARS = 700

L = {
    "uk": {
        "title": u"Підбірка квартир", "rent": u"оренда", "sale": u"продаж",
        "rooms": u"Кімнат", "area": u"Площа", "floor": u"Поверх", "year": u"Рік",
        "price": u"Ціна", "rate": u"Ставка", "czynsz": u"Експлуатаційний платіж",
        "sqm": u"за м²", "district": u"Дзельниця", "osiedle": u"Осиедле", "street": u"Вулиця",
        "condition": u"Стан", "market": u"Ринок", "building": u"Будинок",
        "month": u"/міс", "of": u"з", "source": u"Оголошення на сайті",
        "prepared": u"Підготував", "date": u"Дата", "objects": u"Об'єктів",
        "no_photo": u"фото недоступне", "parter": u"партер",
        "floor_note": u"польська нумерація: партер = наш 1-й поверх",
    },
    "pl": {
        "title": u"Wybrane mieszkania", "rent": u"wynajem", "sale": u"sprzedaż",
        "rooms": u"Pokoje", "area": u"Powierzchnia", "floor": u"Piętro", "year": u"Rok",
        "price": u"Cena", "rate": u"Czynsz najmu", "czynsz": u"Czynsz administracyjny",
        "sqm": u"za m²", "district": u"Dzielnica", "osiedle": u"Osiedle", "street": u"Ulica",
        "condition": u"Stan", "market": u"Rynek", "building": u"Budynek",
        "month": u"/mies.", "of": u"z", "source": u"Ogłoszenie na stronie",
        "prepared": u"Przygotował(a)", "date": u"Data", "objects": u"Obiektów",
        "no_photo": u"zdjęcie niedostępne", "parter": u"parter",
        "floor_note": u"numeracja polska: parter = 0",
    },
}

# Структурные значения: в UK берём готовый перевод из i18n, в PL — то, что
# написала площадка (полякам свой же язык).
COND_PL = {"developer_bare": u"stan deweloperski", "to_renovate": u"do remontu",
           "to_refresh": u"do odświeżenia", "renovated": u"po remoncie", "unknown": u"—"}
MARKET_PL = {"primary": u"pierwotny", "secondary": u"wtórny"}
BUILDING_PL = {"block": u"blok", "tenement": u"kamienica", "apartment": u"apartamentowiec",
               "house": u"dom", "infill": u"plomba", "ribbon": u"szeregowiec", "loft": u"loft",
               "other": u"inne"}


def _num(v, d=0):
    if v is None:
        return u"—"
    s = (u"%.*f" % (d, float(v))).replace(".", ",")
    int_part, _, frac = s.partition(",")
    neg = int_part.startswith("-")
    digits = int_part.lstrip("-")
    out = u""
    while len(digits) > 3:
        out = u" " + digits[-3:] + out
        digits = digits[:-3]
    out = (u"-" if neg else u"") + digits + out
    return out + (u"," + frac if frac else u"")


def _esc(s):
    return html.escape(s or u"")


def _photos(l) -> List[str]:
    try:
        imgs = json.loads(l.images_json or "[]") or []
    except ValueError:
        imgs = []
    return [x for x in imgs[:PHOTOS_PER_ITEM] if isinstance(x, str)]


def _floor(l, t) -> str:
    if l.floor is None:
        return u"—" if not l.floors_total else u"— / %d" % l.floors_total
    f = t["parter"] if l.floor == 0 else str(l.floor)
    return u"%s / %d" % (f, l.floors_total) if l.floors_total else f


def _short(text: Optional[str]) -> str:
    if not text:
        return u""
    s = u" ".join(text.split())
    return s if len(s) <= DESC_CHARS else s[:DESC_CHARS].rsplit(" ", 1)[0] + u"…"


def _item_html(l, lang: str, t: Dict[str, str], i: int, total: int) -> str:
    from . import geo, i18n
    is_rent = l.offer_type == "rent"
    uk = lang == "uk"
    title = (l.title_uk or l.title_pl) if uk else (l.title_pl or l.title_uk)
    desc = (l.description_uk or l.description_pl) if uk else (l.description_pl or l.description_uk)
    osiedle = l.osiedle_override or l.osiedle
    district = geo.district_of(osiedle) or l.district
    cond = l.condition_override or l.condition
    rows = [
        (t["rooms"], _num(l.rooms) if l.rooms else u"—"),
        (t["area"], u"%s m²" % _num(l.area, 1) if l.area else u"—"),
        (t["floor"], _floor(l, t)),
        (t["year"], str(l.build_year) if l.build_year else u"—"),
        (t["district"], district or u"—"),
        (t["osiedle"], (geo.osiedle_uk(osiedle) if uk else osiedle) or osiedle or u"—"),
        (t["street"], l.street or u"—"),
        (t["condition"], (i18n.uk("condition", cond) if uk else COND_PL.get(cond)) or u"—"),
        (t["building"], (i18n.uk("building_type", l.building_type) if uk
                         else BUILDING_PL.get(l.building_type)) or u"—"),
        (t["market"], (i18n.uk("market", l.market) if uk else MARKET_PL.get(l.market)) or u"—"),
    ]
    # Пустые строки не показываем: у объявления OLX нет ни осиедле, ни года, ни
    # состояния, и таблица из семи прочерков в письме клиенту выглядит небрежно.
    cells = u"".join(u"<tr><td class='k'>%s</td><td>%s</td></tr>" % (_esc(k), _esc(v))
                     for k, v in rows if v and v != u"—")
    photos = _photos(l)
    imgs = u"".join(u"<div class='ph'><img src='%s'></div>" % _esc(p) for p in photos) \
        or u"<div class='ph none'>%s</div>" % _esc(t["no_photo"])
    price = u"%s zł%s" % (_num(l.price_pln), t["month"] if is_rent else u"")
    extra = u""
    if is_rent and l.czynsz_pln:
        extra = u"<span class='sub'>+ %s zł %s</span>" % (_num(l.czynsz_pln), _esc(t["czynsz"]))
    elif not is_rent and l.price_per_m2:
        extra = u"<span class='sub'>%s zł %s</span>" % (_num(l.price_per_m2), _esc(t["sqm"]))
    link = u"<a href='%s'>%s ↗</a>" % (_esc(l.url), _esc(t["source"])) if l.url else u""
    return u"""
<section class="item">
  <div class="item-head">
    <div class="num">%d / %d</div>
    <h2>%s</h2>
    <div class="price">%s %s</div>
  </div>
  <div class="photos">%s</div>
  <div class="body">
    <table class="params">%s</table>
    <div class="desc">%s</div>
  </div>
  <div class="src">%s</div>
</section>""" % (i, total, _esc(title), _esc(price), extra, imgs, cells, _esc(_short(desc)), link)


def build_html(listings, profile: Dict[str, str], lang: str,
               title: Optional[str] = None, comment: Optional[str] = None) -> str:
    t = L.get(lang) or L["uk"]
    today = to_kyiv(datetime.utcnow()).strftime("%d.%m.%Y")
    contact = []
    if profile.get("phone"):
        contact.append(u"<a href='tel:%s'>%s</a>" % (_esc(profile["phone"]), _esc(profile["phone"])))
    if profile.get("email"):
        contact.append(u"<a href='mailto:%s'>%s</a>" % (_esc(profile["email"]), _esc(profile["email"])))
    items = u"".join(_item_html(l, lang, t, i + 1, len(listings)) for i, l in enumerate(listings))
    return u"""<!doctype html><html lang="%(lang)s"><head><meta charset="utf-8"><style>
@page { size: A4; margin: 14mm 12mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Arial, sans-serif; color: #1b1f24; font-size: 11pt; margin: 0; }
a { color: #1a5fb4; text-decoration: none; }
.cover { border-bottom: 3px solid #1a5fb4; padding-bottom: 10mm; margin-bottom: 8mm; }
.cover h1 { font-size: 22pt; margin: 0 0 2mm; }
.cover .meta { color: #55606b; font-size: 10pt; }
.card { margin-top: 6mm; padding: 4mm 5mm; background: #f4f7fb; border-radius: 3mm; }
.card .who { font-size: 13pt; font-weight: 600; }
.card .row { color: #55606b; font-size: 10pt; margin-top: 1mm; }
.card .row a { margin-right: 5mm; }
.note { margin-top: 5mm; font-size: 10.5pt; white-space: pre-wrap; }
.item { page-break-before: always; page-break-inside: avoid; }
.item-head { border-bottom: 1px solid #d7dee6; padding-bottom: 2mm; margin-bottom: 3mm; }
.item-head .num { float: right; color: #8b97a3; font-size: 9pt; }
.item-head h2 { font-size: 14pt; margin: 0 0 1mm; }
.price { font-size: 16pt; font-weight: 700; color: #0b4a9c; }
.price .sub { font-size: 10pt; font-weight: 400; color: #55606b; margin-left: 3mm; }
.photos { display: flex; gap: 2mm; margin-bottom: 3mm; }
.ph { flex: 1; height: 52mm; background: #eef1f5; border-radius: 2mm; overflow: hidden;
      display: flex; align-items: center; justify-content: center; }
.ph img { width: 100%%; height: 100%%; object-fit: cover; }
.ph.none { color: #8b97a3; font-size: 9pt; }
.body { display: flex; gap: 5mm; }
table.params { width: 78mm; border-collapse: collapse; font-size: 10pt; }
table.params td { padding: 1.1mm 0; border-bottom: 1px solid #edf1f5; vertical-align: top; }
table.params td.k { color: #55606b; width: 34mm; }
.desc { flex: 1; font-size: 10pt; color: #2c343c; line-height: 1.45; }
.src { margin-top: 3mm; font-size: 9.5pt; }
.foot { position: running(foot); }
</style></head><body>
<div class="cover">
  <h1>%(title)s</h1>
  <div class="meta">%(date_l)s: %(today)s · %(objects_l)s: %(count)d</div>
  <div class="card">
    <div class="who">%(who)s</div>
    %(agency)s
    <div class="row">%(contact)s</div>
    %(about)s
  </div>
  %(comment)s
</div>
%(items)s
</body></html>""" % {
        "lang": lang,
        "title": _esc(title or t["title"]),
        "date_l": _esc(t["date"]), "today": today,
        "objects_l": _esc(t["objects"]), "count": len(listings),
        "who": _esc(profile.get("display_name") or profile.get("user") or u""),
        "agency": (u"<div class='row'>%s</div>" % _esc(profile["agency"])) if profile.get("agency") else u"",
        "contact": u" ".join(contact),
        "about": (u"<div class='row'>%s</div>" % _esc(profile["about"])) if profile.get("about") else u"",
        "comment": (u"<div class='note'>%s</div>" % _esc(comment)) if comment else u"",
        "items": items,
    }


def render_pdf(html_text: str, timeout_ms: int = 60000) -> bytes:
    """HTML -> PDF настоящим Chromium. Фото тянутся с CDN площадок, поэтому
    ждём сеть; если картинка не пришла, страница всё равно верстается."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context(locale="pl-PL").new_page()
            page.set_content(html_text, wait_until="load", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:  # noqa: BLE001 — часть фото не дошла, файл всё равно нужен
                log.warning("презентация: не все фото загрузились за 20 с")
            return page.pdf(format="A4", print_background=True,
                            margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()
