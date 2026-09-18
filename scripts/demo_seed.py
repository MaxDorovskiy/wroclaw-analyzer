# -*- coding: utf-8 -*-
"""Синтетические данные для превью интерфейса и тестов.

Не заменяет живые данные — нужен, чтобы посмотреть интерфейс и погонять
аналитику там, где площадки недоступны (среда разработки в облаке). Цены
привязаны к сентябрю 2026: медиана ~13.5 тыс. zł/м², аренда ~68 zł/м².

    .venv/bin/python scripts/demo_seed.py --db data/demo.db --sale 600 --rent 250
"""
import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# базовая цена м² по осиедле (zł), приближённо по срезам 2026
BASE_SQM = {
    u"Stare Miasto": 17500, u"Przedmieście Świdnickie": 16000, u"Szczepin": 14500,
    u"Plac Grunwaldzki": 15500, u"Ołbin": 13800, u"Nadodrze": 12500,
    u"Biskupin-Sępolno-Dąbie-Bartoszowice": 15000, u"Zacisze-Zalesie-Szczytniki": 15500,
    u"Krzyki-Partynice": 14500, u"Gaj": 13200, u"Huby": 12800, u"Borek": 14800, u"Tarnogaj": 12600,
    u"Jagodno": 11900, u"Wojszyce": 12200, u"Ołtaszyn": 13500, u"Klecina": 12900, u"Księże": 12000,
    u"Brochów": 11200, u"Powstańców Śląskich": 14200, u"Przedmieście Oławskie": 13600, u"Gajowice": 13000,
    u"Grabiszyn-Grabiszynek": 13100, u"Gądów-Popowice Płd.": 12800, u"Pilczyce-Kozanów-Popowice Płn.": 12100,
    u"Muchobór Wielki": 12600, u"Muchobór Mały": 12200, u"Nowy Dwór": 11500, u"Kuźniki": 11700,
    u"Maślice": 12000, u"Leśnica": 11000, u"Żerniki": 12400, u"Oporów": 12900, u"Pracze Odrzańskie": 10800,
    u"Karłowice-Różanka": 13500, u"Kleczków": 12000, u"Sołtysowice": 11600, u"Psie Pole-Zawidawie": 11300,
    # Widawa стоит на месте «Zakrzów» (это часть Psie Pole-Zawidawie, а не осиедле):
    # длина и порядок списка прежние — случайная последовательность генератора не съехала
    u"Widawa": 11000, u"Lipa Piotrowska": 11400, u"Kowale": 11800,
    u"Strachocin-Swojczyce-Wojnów": 11500, u"Osobowice-Rędzin": 11200,
}
COND_FACTOR = {"renovated": 1.06, "unknown": 1.0, "to_refresh": 0.93, "developer_bare": 0.96, "to_renovate": 0.84}
STREETS = [u"ul. Świeradowska", u"ul. Powstańców Śląskich", u"ul. Grabiszyńska", u"ul. Legnicka",
           u"ul. Krzycka", u"ul. Ślężna", u"ul. Hubska", u"ul. Zaporoska", u"ul. Kamienna", u"al. Hallera"]
AGENCIES = [u"Nieruchomości XYZ", u"Dom Wrocław", u"Estate Partners", u"Biuro Odra", u"Freedom Nieruchomości"]
PRIVATE = [u"Marek", u"Anna", u"Piotr", u"Kasia", u"Tomasz", u"Ola", u"Julia"]
FEATURES_PL = {"renovated": u"po generalnym remoncie", "to_refresh": u"do odświeżenia",
               "developer_bare": u"stan deweloperski", "to_renovate": u"do remontu", "unknown": u"z balkonem"}
FEATURES_UK = {"renovated": u"після капітального ремонту", "to_refresh": u"потребує косметичного оновлення",
               "developer_bare": u"стан від забудовника", "to_renovate": u"під ремонт", "unknown": u"з балконом"}
DESC_PL = (u"Na sprzedaż {rooms}-pokojowe mieszkanie o powierzchni {area} m² na osiedlu {os}, {floor_txt}. "
           u"Mieszkanie {feat}. Czynsz administracyjny {czynsz} zł. W pobliżu przystanki MPK, sklepy i szkoła.\n\n"
           u"Rok budowy {year}, {btype}. Ogrzewanie miejskie, okna plastikowe. Zapraszam na prezentację.")
DESC_UK = (u"Продається {rooms}-кімнатна квартира площею {area} м² в осиедле {os}, {floor_txt}. "
           u"Квартира {feat}. Експлуатаційний платіж {czynsz} zł. Поруч зупинки MPK, магазини та школа.\n\n"
           u"Рік будівництва {year}, {btype}. Опалення центральне, вікна металопластикові. Запрошую на показ.")
BTYPES = {"block": (u"blok", u"блочний будинок"), "tenement": (u"kamienica", u"кам'яниця"),
          "apartment": (u"apartamentowiec", u"апартаментний будинок")}


def _floor_txt(f):
    return (u"parter", u"партер") if f == 0 else (u"%d piętro" % f, u"%d поверх" % f)


def seed(db, n_sale=600, n_rent=250, rnd=1, post=True):
    from app import analytics, dedup, rent_analytics
    from app.models import FxRate, Listing, PriceHistory, ScrapeRun
    from app import geo
    r = random.Random(rnd)
    now = datetime.utcnow()
    osiedla = list(BASE_SQM)
    weights = [3 if BASE_SQM[o] < 13000 else 2 for o in osiedla]
    made = {"sale": 0, "rent": 0}
    cheap_marked = False
    for offer_type, n in (("sale", n_sale), ("rent", n_rent)):
        for i in range(n):
            os_ = r.choices(osiedla, weights)[0]
            rooms = r.choices([1, 2, 3, 4], [18, 42, 30, 10])[0]
            area = round({1: r.uniform(24, 38), 2: r.uniform(36, 55), 3: r.uniform(52, 78), 4: r.uniform(72, 110)}[rooms], 1)
            cond = r.choices(list(COND_FACTOR), [30, 25, 15, 18, 12])[0]
            market = "primary" if (cond == "developer_bare" or r.random() < 0.1) else "secondary"
            year = r.choice([1965, 1978, 1990, 2004, 2012, 2019, 2024, 2026]) if market == "secondary" else r.choice([2025, 2026, 2027])
            btype = r.choices(["block", "tenement", "apartment"], [55, 20, 25])[0]
            floor = r.randint(0, 10 if btype != "tenement" else 4)
            floors_total = max(floor, r.choice([4, 5, 10, 11, 16]))
            band_adj = {1: 1.12, 2: 1.03, 3: 0.97, 4: 0.92}[rooms]
            noise = r.gauss(1.0, 0.07)
            if offer_type == "sale":
                sqm = BASE_SQM[os_] * COND_FACTOR[cond] * band_adj * noise
                price = round(sqm * area, -3)
                czynsz = round(area * r.uniform(8, 14), -1)
            else:
                sqm = 68 * (BASE_SQM[os_] / 13000.0) ** 0.6 * band_adj * noise * (1.08 if cond == "renovated" else 1.0)
                price = round(sqm * area, -1)
                czynsz = round(area * r.uniform(8, 14), -1)
            source = "otodom" if r.random() < 0.62 else "olx"
            seller_type = r.choices(["agency", "private", "developer"], [58, 32, 10])[0]
            if market == "primary" and r.random() < 0.6:
                seller_type = "developer"
            seller_name = r.choice(AGENCIES) if seller_type == "agency" else (
                u"Deweloper %s" % r.choice([u"ABC", u"Odra", u"Silesia"]) if seller_type == "developer" else r.choice(PRIVATE))
            phone = "+48%09d" % r.randint(500000000, 899999999) if (source == "otodom" and r.random() < 0.7) else None
            posted = now - timedelta(days=r.uniform(0, 120))
            feat_pl, feat_uk = FEATURES_PL[cond], FEATURES_UK[cond]
            ft_pl, ft_uk = _floor_txt(floor)
            b_pl, b_uk = BTYPES[btype]
            title_pl = u"%d pokoje, %s m², %s, %s" % (rooms, area, os_, feat_pl) if rooms > 1 else u"Kawalerka %s m², %s, %s" % (area, os_, feat_pl)
            title_uk = u"%d кімнати, %s м², %s, %s" % (rooms, area, geo.osiedle_uk(os_) or os_, feat_uk) if rooms > 1 else \
                u"Однокімнатна %s м², %s, %s" % (area, geo.osiedle_uk(os_) or os_, feat_uk)
            translated = r.random() < 0.8
            sid = "%d%05d" % (7 if offer_type == "sale" else 8, i)
            l = Listing(
                source=source, source_id=sid, offer_type=offer_type,
                url=("https://www.otodom.pl/pl/oferta/demo-%s-ID%s" % (sid, sid)) if source == "otodom"
                else "https://www.olx.pl/d/oferta/demo-%s-ID%s.html" % (sid, sid),
                title_pl=title_pl, title_uk=title_uk if translated else None,
                description_pl=DESC_PL.format(rooms=rooms, area=area, os=os_, floor_txt=ft_pl, feat=feat_pl, czynsz=int(czynsz), year=year, btype=b_pl),
                description_uk=DESC_UK.format(rooms=rooms, area=area, os=geo.osiedle_uk(os_) or os_, floor_txt=ft_uk, feat=feat_uk, czynsz=int(czynsz), year=year, btype=b_uk) if translated else None,
                translated_at=now if translated else None, translate_provider="demo:seed" if translated else None,
                price_pln=price, price_per_m2=round(price / area, 2), czynsz_pln=czynsz,
                area=area, rooms=rooms, floor=floor, floors_total=floors_total, build_year=year,
                market=market, building_type=btype, building_material="brick" if btype == "tenement" else r.choice(["brick", "concrete_plate", "silikat"]),
                construction_status="to_completion" if cond == "developer_bare" else "ready_to_use",
                condition=cond, condition_src="text", heating="urban", windows="plastic",
                ownership="full_ownership", elevator=floors_total > 5, furnished=(offer_type == "rent" and r.random() < 0.8),
                extras_json=json.dumps(r.sample(["balcony", "basement", "garage", "lift", "terrace", "separate_kitchen"], 3)),
                characteristics_json=json.dumps({"market": {"label": u"Rynek", "value": market, "localized": u"wtórny" if market == "secondary" else u"pierwotny"},
                                                 "heating": {"label": u"Ogrzewanie", "value": "urban", "localized": u"miejskie"},
                                                 "floor_no": {"label": u"Piętro", "value": "floor_%d" % floor, "localized": str(floor)},
                                                 "build_year": {"label": u"Rok budowy", "value": str(year), "localized": str(year)}}, ensure_ascii=False),
                district=geo.district_of(os_), osiedle=os_, street=r.choice(STREETS),
                lat=51.1 + r.uniform(-0.08, 0.08), lon=17.03 + r.uniform(-0.12, 0.12),
                seller_type=seller_type, seller_name=seller_name, seller_phone=phone,
                seller_id=("agency:%d" % (AGENCIES.index(seller_name) + 1)) if seller_type == "agency" else None,
                images_json=json.dumps(["https://ireland.apollo.olxcdn.com/v1/files/demo%s%d/image;s=1000x700" % (sid, k) for k in range(3)]),
                first_image="https://ireland.apollo.olxcdn.com/v1/files/demo%s0/image;s=1000x700" % sid, image_count=r.randint(3, 20),
                posted_at=posted, first_seen=posted, last_seen=now, is_active=True, details_fetched=True,
                price_usd=round(price / 3.95), price_eur=round(price / 4.27),
            )
            if r.random() < 0.15:
                l.is_active = False
                l.removed_at = now - timedelta(days=r.uniform(1, 30))
                l.last_seen = l.removed_at
            db.add(l)
            db.flush()
            db.add(PriceHistory(listing_id=l.id, price_pln=price * (1.04 if r.random() < 0.3 else 1.0), seen_at=posted))
            if r.random() < 0.3:
                db.add(PriceHistory(listing_id=l.id, price_pln=price, seen_at=posted + timedelta(days=10)))
            # одно заведомо дешёвое объявление для теста выгодности
            if offer_type == "sale" and not cheap_marked and cond == "unknown" and rooms == 2 and BASE_SQM[os_] < 13000 and l.is_active:
                # скидка задаётся от «честной» цены ячейки БЕЗ шума, иначе объявление с
                # шумом +14% после среза 20% дешевле медианы лишь на 6% (так и падал тест)
                l.price_pln = round(BASE_SQM[os_] * COND_FACTOR[cond] * band_adj * area * 0.75, -3)
                l.price_per_m2 = round(l.price_pln / area, 2)
                l.note = "seed:cheap"
                cheap_marked = True
            # зеркало на OLX у части агентских объявлений Otodom
            if source == "otodom" and seller_type == "agency" and r.random() < 0.25 and l.is_active:
                m = Listing(source="olx", source_id="9" + sid, offer_type=offer_type, url="https://www.olx.pl/d/oferta/demo-9%s-ID9%s.html" % (sid, sid),
                            external_url=l.url, title_pl=title_pl, title_uk=l.title_uk, description_pl=l.description_pl,
                            description_uk=l.description_uk, price_pln=l.price_pln, price_per_m2=l.price_per_m2, area=area, rooms=rooms,
                            floor=floor, market=market, building_type=btype, condition=cond, district=l.district, osiedle=os_,
                            seller_type="agency", seller_name=seller_name, seller_id=l.seller_id, first_image=l.first_image,
                            images_json=l.images_json, posted_at=posted, first_seen=posted, last_seen=now, is_active=True,
                            details_fetched=True, price_usd=l.price_usd, price_eur=l.price_eur)
                db.add(m)
            made[offer_type] += 1
    for code, mid in (("USD", 3.95), ("EUR", 4.27)):
        db.add(FxRate(date=now.strftime("%Y-%m-%d"), code=code, mid=mid))
    for k, kind in enumerate(("sale", "rent", "sale")):
        st = now - timedelta(hours=6 * (k + 1))
        db.add(ScrapeRun(kind=kind, source="all", status="done", started_at=st, finished_at=st + timedelta(minutes=50),
                         last_beat=st + timedelta(minutes=50), pages=140 - k, seen=9500 - 40 * k, new=420, updated=9000,
                         price_changes=130, removed=380, details=410, errors=2, full=True, phase="finished",
                         message=u"демо-прогон"))
    db.commit()
    if post:
        dedup.rebuild_groups(db)
        analytics.recompute_deal_scores(db)
        rent_analytics.recompute_yields(db)
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "demo.db"))
    ap.add_argument("--sale", type=int, default=600)
    ap.add_argument("--rent", type=int, default=250)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    os.environ["WRO_DB"] = args.db
    from app.db import SessionLocal, ensure_columns
    ensure_columns()
    db = SessionLocal()
    try:
        made = seed(db, args.sale, args.rent, args.seed)
        print(u"записано: %s -> %s" % (made, args.db))
    finally:
        db.close()


if __name__ == "__main__":
    main()
