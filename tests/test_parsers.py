# -*- coding: utf-8 -*-
import json

from app.normalize import normalize
from app.sources.olx import Olx
from app.sources.otodom import Otodom, extract_next_data, find_search_block


def _html(fixtures, name):
    data = (fixtures / name).read_text(encoding="utf-8")
    return '<html><body><script id="__NEXT_DATA__" type="application/json">%s</script></body></html>' % data


def test_otodom_search_items(fixtures):
    data = extract_next_data(_html(fixtures, "otodom_search.json"))
    items, pagination = find_search_block(data)
    assert len(items) == 2 and pagination["totalPages"] == 3
    raw = Otodom().parse_item(items[0], "sale")
    assert raw.source_id == "65432101"
    assert raw.url.endswith("-ID4v4VB")           # адрес из slug, не из числового id
    assert raw.price == 780000 and raw.area == 60 and raw.rooms_raw == "THREE"
    assert raw.seller_type_raw == "agency" and raw.seller_id == "agency:123"
    d = normalize(raw)
    assert d["rooms"] == 3 and d["floor"] == 2
    assert d["district"] == "Krzyki" and d["osiedle"] == "Gaj"
    assert d["price_per_m2"] == 13000 and d["first_image"].startswith("https://")
    dev = normalize(Otodom().parse_item(items[1], "sale"))
    assert dev["seller_type"] == "developer" and dev["osiedle"] == "Jagodno"
    assert dev["condition"] == "developer_bare" and dev["floor"] == 0


def test_otodom_ad_details(fixtures):
    data = extract_next_data(_html(fixtures, "otodom_search.json"))
    items, _ = find_search_block(data)
    raw = Otodom().parse_item(items[0], "sale")
    ad = json.loads((fixtures / "otodom_ad.json").read_text(encoding="utf-8"))["props"]["pageProps"]["ad"]
    raw = Otodom().apply_ad(raw, ad)
    d = normalize(raw)
    assert d["condition"] == "renovated" and d["condition_src"] == "text"
    assert d["build_year"] == 2008 and d["floors_total"] == 4 and d["market"] == "secondary"
    assert d["building_type"] == "block" and d["building_material"] == "brick"
    assert d["heating"] == "urban" and d["windows"] == "plastic" and d["ownership"] == "full_ownership"
    assert d["czynsz_pln"] == 650 and d["elevator"] is True
    assert d["lat"] == 51.0812 and d["street"] == "ul. Świeradowska 12"
    assert d["seller_phone"] == "+48600100200" and d["seller_name"] == "Nieruchomości XYZ"
    extras = json.loads(d["extras_json"])
    assert {"balcony", "garage", "basement", "lift"} <= set(extras)
    assert "<p>" not in d["description_pl"] and "Czynsz 650" in d["description_pl"]
    chars = json.loads(d["characteristics_json"])
    assert chars["heating"]["localized"] == "miejskie"


def test_olx_items(fixtures):
    data = json.loads((fixtures / "olx_offers.json").read_text(encoding="utf-8"))
    raws = [Olx().parse_item(it, "sale") for it in data["data"]]
    a = normalize(raws[0])
    assert a["price_pln"] == 520000 and a["area"] == 48 and a["rooms"] == 2 and a["floor"] == 4
    assert a["market"] == "secondary" and a["building_type"] == "block" and a["furnished"] is False
    assert a["district"] == "Krzyki" and a["osiedle"] is None     # OLX даёт только дзельницу
    assert a["condition"] == "to_refresh" and a["seller_type"] == "private"
    assert a["first_image"].endswith(";s=1000x700") and a["lat"] == 51.0912
    b = normalize(raws[1])
    assert b["external_url"].endswith("ID4v4VB") and b["seller_type"] == "agency"
    assert b["condition"] == "renovated"
