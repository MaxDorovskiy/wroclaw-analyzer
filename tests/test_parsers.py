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


def test_otodom_private_seller_phone(fixtures):
    """У частника `owner.phones` ВСЕГДА пустой, номер лежит в
    `contactDetails.phones` и `owner.contacts[].phone`. Адаптер читал только
    первое: 1670 телефонов собственников лежали в базе и не были видны
    (боевая база 24.09.2026). Именно частники и нужны — агентство перезвонит
    само."""
    data = extract_next_data(_html(fixtures, "otodom_search.json"))
    items, _ = find_search_block(data)
    ad = json.loads((fixtures / "otodom_ad.json").read_text(encoding="utf-8"))["props"]["pageProps"]["ad"]
    ad = dict(ad)
    ad.pop("agency", None)
    ad["owner"] = {"id": 5, "name": "Jan", "type": "PRIVATE", "phones": [],
                   "contacts": [{"name": "Jan", "phone": "+48600100299", "hasPhoneNumber": True}]}
    ad["contactDetails"] = {"name": "Jan", "type": "private", "phones": ["+48600100299"]}
    d = normalize(Otodom().apply_ad(Otodom().parse_item(items[0], "sale"), ad))
    assert d["seller_type"] == "private" and d["seller_phone"] == "+48600100299"


def test_condition_respects_negation():
    """«Nie wymaga remontu» читалось как «требует ремонта»: регулярка находила
    фразу и не смотрела, что перед ней «nie». 15.10.2026 так 50 из 784
    квартир «под ремонт» (6,4%) на самом деле писали обратное, и им к
    доходности приплюсовывалась отделка по 3860 zł/м²."""
    from app.normalize import classify_condition as c
    cases = [
        (u"Mieszkanie nie wymaga remontu, gotowe do zamieszkania", "renovated"),
        (u"Lokal nie wymaga generalnego remontu", "unknown"),
        (u"To nie jest mieszkanie do remontu w typowym sensie", "unknown"),
        (u"To nie jest standard deweloperski – to unikalny design", "unknown"),
        # отрицание не перепрыгивает через запятую в соседнюю фразу
        (u"Nie jest po remoncie, wymaga odświeżenia", "to_refresh"),
        # \xabbez windy\xbb, \xabbez prowizji\xbb — \xabbez\xbb про лифт и комиссию, а не про ремонт
        (u"3 piętro, bez windy   mieszkanie po remoncie 6 lat temu", "renovated"),
        (u"Bez prowizji! Mieszkanie po remoncie", "renovated"),
        # утвердительные — как и раньше
        (u"Mieszkanie do remontu", "to_renovate"),
        (u"Stan deweloperski, do wykończenia", "developer_bare"),
    ]
    for text, want in cases:
        assert c(None, None, text, None)[0] == want, text


def test_net_price_plus_vat_is_flagged_only_when_the_price_is_net():
    """Codex 28.10.2026 (F-003): цена нетто стояла в выгодных с «−50,7%». Но
    «Netto» — ещё и сеть магазинов, и «… zł netto + VAT» у паркинга или
    мебели при цене квартиры брутто — не признак."""
    from app.normalize import price_note
    assert price_note(u"Podana cenna jest ceną netto plus 23%VAT. Możliwość odliczenia", 234359.0) == "net_vat"
    assert price_note(u"Cena: 373 983,73 zł netto + VAT 23% tj. 460 000 zł brutto.", 373983.0) == "net_vat"
    # сохранена брутто-цена — признака нет
    assert price_note(u"Cena: 308 130 zł netto + 23% VAT = 379 000,00 zł brutto", 379000.0) is None
    assert price_note(u"miejsce parkingowe w cenie 8 130,08 zł netto + 23%VAT razem 10 000 zł brutto", 630228.0) is None
    assert price_note(u"W pobliżu sklep Netto i Biedronka", 500000.0) is None
    assert price_note(u"przychód 8 000 zł netto miesięcznie", 8000.0) is None
    # F-003 Codex 03.11.2026 — формулировки живых объявлений, которые первая версия пропускала
    for text, price in (
            (u"Cena podana w ogłoszeniu jest wartością netto i należy ją powiększyć o 23% VAT.", 275972.0),
            (u"Cena podana w ogłoszeniu jest wartością netto i będzie powiększona o 23%VAT", 330403.0),
            (u"z wyposażeniem apartamentu. Do ceny należy doliczyć podatek VAT w wysokości 23%", 369931.0),
            (u"Cena: 320 000 zł Netto (+ VAT 23%)  POLECAM!!!", 320000.0),
            (u"za cenę 269 900 zł netto (331 977zł brutto).", 269900.0),
            (u"Opłata za wynajem apartamentu: 3.800 zł Netto + 23% VAT", 3800.0)):
        assert price_note(text, price) == "net_vat", text
    # и контрпримеры: после «netto plus» не VAT; нетто — у гаража или комиссии, не у квартиры
    for text, price in (
            (u"Opłaty: 1200,00 zł netto plus liczniki", 1200.0),
            (u"Oczekiwany czynsz najmu 30 000 zł netto plus opłaty eksploatacyjne.", 30000.0),
            (u"Cena mieszkania 500 000 zł brutto. Cena garażu jest ceną netto plus VAT.", 500000.0),
            (u"Cena 500 000 zł zawiera VAT. Prowizja 2% netto + VAT.", 500000.0)):
        assert price_note(text, price) is None, text


def test_ollama_stream_yields_gpu_mid_answer(monkeypatch):
    """Codex 28.10.2026 (F-005): запрос к модели шёл одним куском до 300 с, и
    реестр видеокарты не спрашивали, пока он не кончится. Теперь — потоком, и
    между кусками ответа: карту забрали — обрываем, текст остаётся в очереди."""
    import json as _json
    import pytest
    from app import translate as T

    chunks = [{"message": {"content": u"При"}}, {"message": {"content": u"віт"}},
              {"message": {"content": u"!"}, "done": True}]

    class FakeResp:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            for c in chunks:
                yield _json.dumps(c)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(T.httpx, "stream", lambda *a, **kw: FakeResp())
    p = T.OllamaProvider("http://x", "m")
    T._state["yield_check"] = None
    assert p.translate([u"Cześć!"]) == [u"Привіт!"]
    answers = iter([True, False])                       # на втором куске карту забрали
    T._state["yield_check"] = lambda: next(answers)
    try:
        with pytest.raises(T.GpuYield):
            p.translate([u"Cześć!"])
    finally:
        T._state["yield_check"] = None
