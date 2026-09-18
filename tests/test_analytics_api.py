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
