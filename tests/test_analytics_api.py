# -*- coding: utf-8 -*-
import json

from fastapi.testclient import TestClient

from app import analytics, dedup, rent_analytics
from app.config import SECRET_MASK
from app.main import app
from app.models import Listing
from demo_seed import seed


def test_seed_and_analytics(clean_db):
    db = clean_db
    n = seed(db, n_sale=400, n_rent=160, rnd=7, post=False)
    assert n["sale"] == 400 and n["rent"] == 160
    dedup.rebuild_groups(db)
    res = analytics.recompute_deal_scores(db)
    assert res["scored"] > 300
    # заведомо дешёвое объявление (генератор кладёт его с id-меткой в note)
    cheap = db.query(Listing).filter(Listing.note == "seed:cheap").first()
    assert cheap.discount_pct is not None and cheap.discount_pct >= 8, cheap.discount_pct
    coef = res["area_coef"]
    assert "45-60 м²" in coef and coef["45-60 м²"] == 1.0
    ry = rent_analytics.recompute_yields(db)
    assert ry["scored"] > 200
    y = [l.yield_pct for l in db.query(Listing).filter(Listing.yield_pct.isnot(None)).all()]
    assert 2 < sorted(y)[len(y) // 2] < 10        # медиана доходности в разумных пределах
    st = analytics.stats(db, "sale", "osiedle")
    assert st["rows"] and st["rows"][0]["median_sqm"] > 5000
    idx = analytics.price_index(db, "month", "sale")
    assert idx["points"] and idx["points"][0]["index"] == 100.0
    tr = analytics.trends(db, 8, "sale")
    assert len(tr["points"]) == 8
    # по осиедле синтетика слишком тонкая (44 осиедле × 4 комнаты при 160 арендах),
    # поэтому топ проверяем по дзельницам
    top = rent_analytics.yield_top(db, "district", None, 5, 5)
    assert top["rows"] and 1 < top["rows"][0]["yield_pct"] < 15


def test_api_roundtrip(clean_db):
    db = clean_db
    seed(db, n_sale=150, n_rent=60, rnd=3, post=True)
    with TestClient(app) as c:
        s = c.get("/api/summary").json()
        assert s["sale"]["active"] > 100 and s["rent"]["active"] > 40
        r = c.get("/api/listings?rooms=2,3&per_page=10&sort=price_sqm&order=asc").json()
        assert r["total"] > 0 and all(x["rooms"] in (2, 3) for x in r["items"])
        assert r["items"][0]["price_per_m2"] <= r["items"][-1]["price_per_m2"]
        first = r["items"][0]
        assert first["osiedle_uk"] and first["condition_uk"] and first["district_uk"]
        full = c.get("/api/listings/%d" % first["id"]).json()
        for key in ("description_pl", "characteristics", "price_history", "dupes", "deal_explain", "rent_explain"):
            assert key in full
        assert c.post("/api/listings/%d/favorite" % first["id"], json={}).json()["is_favorite"] is True
        assert c.get("/api/listings?favorites=1").json()["total"] == 1
        assert c.post("/api/listings/%d/manual" % first["id"], json={"osiedle": "Nibylandia"}).status_code == 400
        m = c.post("/api/listings/%d/manual" % first["id"], json={"osiedle": "Gaj", "condition": "to_renovate", "note": "x"}).json()
        assert m["osiedle"] == "Gaj" and m["condition"] == "to_renovate" and m["osiedle_src"] == "manual"
        deals = c.get("/api/listings?only_deals=1").json()
        assert all(x["discount_pct"] >= 10 for x in deals["items"])
        rent = c.get("/api/listings?offer_type=rent&per_page=5").json()
        assert rent["total"] > 0 and rent["items"][0]["offer_type"] == "rent"
        geo = c.get("/api/geo").json()
        assert sum(d["sale_active"] for d in geo["districts"]) > 0
        assert c.get("/api/stats?level=district").json()["rows"]
        assert c.get("/api/price_index").json()["points"]
        contacts = c.get("/api/contacts?offer_type=all").json()
        assert contacts["total"] > 0 and contacts["items"][0]["seller_key"]
        owners = c.get("/api/contacts?seller_type=private").json()
        assert all(x["seller_type"] == "private" for x in owners["items"])
        assert c.get("/api/contacts/export?format=csv").status_code == 200
        assert c.get("/api/export?format=xlsx&rooms=2").status_code == 200
        # настройки: секреты маскируются и не перетираются маской
        assert c.post("/api/settings", json={"translate_anthropic_key": "sk-test", "bogus": "1"}).json()["saved"] == ["translate_anthropic_key"]
        st = c.get("/api/settings").json()
        assert st["translate_anthropic_key"] == SECRET_MASK
        c.post("/api/settings", json={"translate_anthropic_key": SECRET_MASK})
        from app.settings_store import get_setting
        assert get_setting(db, "translate_anthropic_key") == "sk-test"
        # пауза
        assert c.post("/api/scrape/pause", json={"hours": 1}).json()["paused_until"]
        assert c.post("/api/scrape?kind=sale").status_code == 409
        assert c.post("/api/scrape/resume").json()["paused_until"] is None
        assert c.get("/api/translate/status").json()["provider"] == "ollama"
        assert c.get("/api/runs").status_code == 200


def test_favorites_are_per_user(clean_db, monkeypatch):
    """Обране у каждого логина своё: раньше был один флаг listings.is_favorite,
    и снятая Юлией звезда исчезала бы у владельца."""
    from app.models import Favorite

    db = clean_db
    seed(db, n_sale=40, n_rent=10, rnd=5, post=False)
    # старая база: общий список обраного переносится владельцу один раз
    legacy = db.query(Listing).order_by(Listing.id).first()
    legacy.is_favorite = True
    db.commit()
    monkeypatch.setenv("WRO_WEB_USERS", "admin:s1;yulia:s2")
    monkeypatch.delenv("WRO_WEB_PASS", raising=False)
    with TestClient(app) as c:
        a = {"auth": ("admin", "s1")}
        y = {"auth": ("yulia", "s2")}
        assert db.query(Favorite).filter_by(user="admin").count() == 1      # перенос при старте
        ids = [x["id"] for x in c.get("/api/listings?per_page=3", **a).json()["items"]]
        mine, hers = ids[0], ids[1]
        assert c.post("/api/listings/%d/favorite" % mine, json={}, **a).json()["is_favorite"] is True
        assert c.post("/api/listings/%d/favorite" % hers, json={}, **y).json()["is_favorite"] is True
        # у каждого в списке только своё
        aids = {x["id"] for x in c.get("/api/listings?favorites=1&per_page=50", **a).json()["items"]}
        yids = {x["id"] for x in c.get("/api/listings?favorites=1&per_page=50", **y).json()["items"]}
        assert mine in aids and hers not in aids
        assert yids == {hers}
        # звезда в строке — своя: одно и то же объявление у них разное
        row_a = [x for x in c.get("/api/listings?per_page=3", **a).json()["items"] if x["id"] == hers][0]
        row_y = [x for x in c.get("/api/listings?per_page=3", **y).json()["items"] if x["id"] == hers][0]
        assert row_a["is_favorite"] is False and row_y["is_favorite"] is True
        assert c.get("/api/listings/%d" % hers, **y).json()["is_favorite"] is True
        assert c.get("/api/listings/%d" % hers, **a).json()["is_favorite"] is False
        # снятие у одного не трогает другого
        assert c.post("/api/listings/%d/favorite" % hers, json={"value": False}, **y).json()["is_favorite"] is False
        assert c.get("/api/listings?favorites=1", **a).json()["total"] == 2   # legacy + mine
        # владелец видит список Юлии, она его — нет
        c.post("/api/listings/%d/favorite" % hers, json={}, **y)
        assert {x["id"] for x in c.get("/api/listings?favorites=1&fav_user=yulia", **a).json()["items"]} == {hers}
        assert c.get("/api/listings?favorites=1&fav_user=admin", **y).status_code == 403
        users = c.get("/api/favorites/users", **a).json()
        assert {u["user"]: u["count"] for u in users["users"]} == {"admin": 2, "yulia": 1}
        assert c.get("/api/favorites/users", **y).json()["users"] == [{"user": "yulia", "count": 1}]
        # «Обране» показывает продажу и аренду одним списком
        rent_id = c.get("/api/listings?offer_type=rent&per_page=1", **a).json()["items"][0]["id"]
        c.post("/api/listings/%d/favorite" % rent_id, json={}, **a)
        got = c.get("/api/listings?favorites=1&offer_type=all&sort=fav&per_page=50", **a).json()
        assert got["items"][0]["id"] == rent_id                              # последнее добавленное — первым
        assert {x["offer_type"] for x in got["items"]} == {"sale", "rent"}


def test_profile_and_presentation(clean_db, monkeypatch):
    """Підбірка для клієнта: контакти — ТОГО, хто надсилає, мова на вибір.
    Chromium у тесті не запускаємо: перевіряємо HTML, який іде йому на вхід."""
    from app import presentation
    from app.models import UserProfile

    db = clean_db
    seed(db, n_sale=30, n_rent=10, rnd=9, post=False)
    monkeypatch.setenv("WRO_WEB_USERS", "admin:s1;yulia:s2")
    monkeypatch.delenv("WRO_WEB_PASS", raising=False)
    made = {}
    monkeypatch.setattr(presentation, "render_pdf", lambda h, **kw: made.setdefault("html", h) and b"" or b"%PDF-1.4 fake")
    with TestClient(app) as c:
        a, y = {"auth": ("admin", "s1")}, {"auth": ("yulia", "s2")}
        # визитка: своя у каждого, чужую никто не получает
        assert c.get("/api/profile", **y).json()["display_name"] == "yulia"
        saved = c.post("/api/profile", json={
            "display_name": u"Юлія Коваленко", "phone": "+48600100200",
            "email": "y@example.com", "agency": u"Оренда", "pres_lang": "pl"}, **y).json()
        assert saved["phone"] == "+48600100200" and saved["pres_lang"] == "pl"
        assert c.get("/api/profile", **a).json()["display_name"] == "admin"      # владельца не тронули
        assert db.get(UserProfile, "yulia").email == "y@example.com"

        rent = c.get("/api/listings?offer_type=rent&per_page=2", **y).json()["items"]
        sale = c.get("/api/listings?offer_type=sale&per_page=1", **y).json()["items"]
        ids = [rent[1]["id"], sale[0]["id"], rent[0]["id"]]
        r = c.post("/api/presentation", json={"ids": ids, "lang": "uk",
                                              "comment": u"Пані Олено, ось варіанти"}, **y)
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        assert "attachment" in r.headers["content-disposition"]
        html = made["html"]
        assert u"Юлія Коваленко" in html and "+48600100200" in html and u"Оренда" in html
        assert u"Пані Олено" in html
        assert u"Підбірка квартир" in html and u"Кімнат" in html          # украинские подписи
        # порядок — как выбрали, а не как в базе
        assert [html.index(u"%d / 3" % i) for i in (1, 2, 3)] == sorted(
            [html.index(u"%d / 3" % i) for i in (1, 2, 3)])
        # польская версия: подписи и тексты площадки
        made.clear()
        c.post("/api/presentation", json={"ids": ids[:1], "lang": "pl"}, **y)
        assert u"Wybrane mieszkania" in made["html"] and u"Pokoje" in made["html"]
        assert u"Кімнат" not in made["html"]
        # границы
        assert c.post("/api/presentation", json={"ids": []}, **y).status_code == 400
        assert c.post("/api/presentation", json={"ids": ids, "lang": "de"}, **y).status_code == 400
        assert c.post("/api/presentation", json={"ids": list(range(1, 40))}, **y).status_code == 400
        # действие видно владельцу в журнале
        acts = [x["action"] for x in c.get("/api/activity?user=yulia", **a).json()["rows"]]
        assert "presentation" in acts


def test_users_roles_and_activity(clean_db, monkeypatch):
    db = clean_db
    seed(db, n_sale=30, n_rent=10, rnd=11, post=False)
    monkeypatch.setenv("WRO_WEB_USERS", "admin:secret1;yulia:secret2")
    monkeypatch.delenv("WRO_WEB_PASS", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/listings").status_code == 401                  # без входа — нельзя
        y = {"auth": ("yulia", "secret2")}
        a = {"auth": ("admin", "secret1")}
        assert c.get("/api/me", **y).json() == {"user": "yulia", "role": "viewer", "users": None}
        lid = c.get("/api/listings?per_page=1", **y).json()["items"][0]["id"]
        assert c.get("/api/listings/%d" % lid, **y).status_code == 200
        assert c.post("/api/listings/%d/favorite" % lid, json={}, **y).status_code == 200
        assert c.post("/api/settings", json={"deal_threshold_pct": "5"}, **y).status_code == 403
        assert c.get("/api/settings", **y).status_code == 403
        assert c.post("/api/scrape", **y).status_code == 403
        assert c.get("/api/activity", **y).status_code == 403
        act = c.get("/api/activity?user=yulia", **a).json()
        actions = [r["action"] for r in act["rows"]]
        assert "view_card" in actions and "favorite" in actions and "search" in actions
        card = [r for r in act["rows"] if r["action"] == "view_card"][0]
        assert card["listing_id"] == lid and card["listing"]["title"]
        assert act["per_user"]["yulia"] >= 3
        assert c.get("/api/me", **a).json()["users"] == ["admin", "yulia"]
        assert c.get("/api/health").status_code == 200                    # проверка живости без входа


def test_yield_ignores_prices_that_are_not_flat_prices(clean_db):
    """Доходность считалась для ЛЮБОЙ цены, лишь бы была площадь.

    На боевой базе 09.10.2026 из-за этого в «Найкраща дохідність» на главном
    экране первыми шли не квартиры: торговое место за 1500 zł (931% годовых),
    доля 3/32 в квартире за 30 150 zł и объявление на 149 000 zł за 118 м²
    (48,8%). У выгодности такой фильтр был с самого начала (_sane: 4–40 тыс.
    zł/м²), у доходности — нет."""
    from datetime import datetime

    db = clean_db
    now = datetime.utcnow()
    # нормальная аренда, чтобы было с чем сравнивать
    for i in range(8):
        db.add(Listing(source="otodom", source_id="r%d" % i, offer_type="rent",
                       url="https://x/r%d" % i, title_pl="Wynajem", rooms=2, area=50.0,
                       price_pln=3000.0, osiedle="Gaj", district="Krzyki", is_active=True,
                       is_representative=True, first_seen=now, last_seen=now))
    normal = Listing(source="otodom", source_id="s1", offer_type="sale", url="https://x/s1",
                     title_pl="Mieszkanie", rooms=2, area=50.0, price_pln=650000.0,
                     osiedle="Gaj", district="Krzyki", is_active=True, is_representative=True,
                     first_seen=now, last_seen=now)
    junk = Listing(source="olx", source_id="s2", offer_type="sale", url="https://x/s2",
                   title_pl="Sprzedam stoisko", rooms=1, area=14.0, price_pln=1500.0,
                   osiedle="Gaj", district="Krzyki", is_active=True, is_representative=True,
                   first_seen=now, last_seen=now)
    db.add_all([normal, junk])
    db.commit()

    rent_analytics.recompute_yields(db)
    db.refresh(normal)
    db.refresh(junk)
    assert normal.yield_pct is not None and 0 < normal.yield_pct < 30
    assert junk.yield_pct is None          # 107 zł/м² — это не цена квартиры


def test_group_representative_is_a_live_listing(clean_db):
    """Представителем группы становилось СНЯТОЕ размещение, если цены нет ни
    у кого: каталог показывает is_active И is_representative, и живая квартира
    пропадала из выдачи. На боевой базе 09.10.2026 так пряталась группа g7327
    («запытайте о цене» на обоих размещениях)."""
    from datetime import datetime

    db = clean_db
    now = datetime.utcnow()
    gone = Listing(source="otodom", source_id="g1", offer_type="sale",
                   url="https://www.otodom.pl/pl/oferta/x-IDg1",
                   title_pl="Mieszkanie", rooms=3, area=60.0, osiedle="Gaj", district="Krzyki",
                   external_url=None, is_active=False, first_seen=now, last_seen=now)
    live = Listing(source="olx", source_id="g2", offer_type="sale", url="https://x/g2",
                   title_pl="Mieszkanie", rooms=3, area=60.0, osiedle="Gaj", district="Krzyki",
                   external_url="https://www.otodom.pl/pl/oferta/x-IDg1", is_active=True,
                   first_seen=now, last_seen=now)
    db.add_all([gone, live])
    db.commit()
    # цены нет ни у одного — именно этот случай и ломался
    dedup.rebuild_groups(db)
    db.refresh(gone)
    db.refresh(live)
    assert gone.dedup_group == live.dedup_group        # склеились по зеркалу
    assert live.is_representative is True and gone.is_representative is False


def test_price_drop_is_stored_and_sortable(clean_db):
    """Сортировка «Зміни ціни» была привязана к discount_pct — то есть молча
    сортировала по скидке, а не по изменению цены. Падение считалось только
    на лету по показанной странице и в базе не хранилось, поэтому блок
    «Знизили ціну» на главном экране показывал квартиры, у которых цена вообще
    не менялась (NULL идут первыми при сортировке по возрастанию)."""
    from datetime import datetime, timedelta

    from app.models import PriceHistory

    db = clean_db
    now = datetime.utcnow()
    dropped = Listing(source="otodom", source_id="d1", offer_type="sale", url="https://x/d1",
                      title_pl="Mieszkanie", rooms=2, area=50.0, price_pln=540000.0,
                      is_active=True, is_representative=True, first_seen=now, last_seen=now)
    steady = Listing(source="otodom", source_id="d2", offer_type="sale", url="https://x/d2",
                     title_pl="Mieszkanie", rooms=2, area=50.0, price_pln=600000.0,
                     is_active=True, is_representative=True, first_seen=now, last_seen=now)
    db.add_all([dropped, steady])
    db.commit()
    db.add_all([
        PriceHistory(listing_id=dropped.id, price_pln=600000.0, seen_at=now - timedelta(days=5)),
        PriceHistory(listing_id=dropped.id, price_pln=540000.0, seen_at=now),
        PriceHistory(listing_id=steady.id, price_pln=600000.0, seen_at=now - timedelta(days=5)),
    ])
    db.commit()

    res = analytics.recompute_price_drops(db)
    assert res["changed"] == 1
    db.refresh(dropped)
    db.refresh(steady)
    assert dropped.price_drop_pct == -10.0
    assert steady.price_drop_pct is None            # цена не менялась — это НЕ «ноль процентов»

    client = TestClient(app)
    r = client.get("/api/listings", params={"dropped": 1, "sort": "price_drop", "order": "asc"})
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["items"]]
    assert ids == [dropped.id]                      # тот, у кого цена не менялась, в список не попал
