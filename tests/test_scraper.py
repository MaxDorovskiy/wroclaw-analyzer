# -*- coding: utf-8 -*-
import json
from datetime import datetime, timedelta

from app import dedup, scraper
from app.models import Listing, PriceHistory, ScrapeRun
from app.sources.olx import Olx
from app.sources.otodom import Otodom, extract_next_data, find_search_block


def _load(fixtures):
    html = '<script id="__NEXT_DATA__">%s</script>' % (fixtures / "otodom_search.json").read_text(encoding="utf-8")
    items, _ = find_search_block(extract_next_data(html))
    oto = [Otodom().parse_item(it, "sale") for it in items]
    olx = [Olx().parse_item(it, "sale") for it in json.loads((fixtures / "olx_offers.json").read_text(encoding="utf-8"))["data"]]
    return oto, olx


def test_upsert_history_removal_dedup(clean_db, fixtures):
    db = clean_db
    oto, olx = _load(fixtures)
    run = ScrapeRun(kind="sale", status="running")
    db.add(run)
    db.commit()
    now = datetime.utcnow()
    unknown = {}
    for raw in oto + olx:
        scraper.upsert(db, raw, run, now, unknown)
    db.commit()
    assert run.new == 4 and db.query(Listing).count() == 4
    # повторный обход: цена изменилась -> история, статус new не растёт
    oto[0].price = 760000
    scraper.upsert(db, oto[0], run, now + timedelta(hours=1), unknown)
    db.commit()
    l = db.query(Listing).filter_by(source="otodom", source_id="65432101").one()
    assert l.price_pln == 760000
    assert db.query(PriceHistory).filter_by(listing_id=l.id).count() == 2
    assert run.price_changes == 1 and run.new == 4
    # ручная правка не перетирается
    l.condition_override = "to_renovate"
    db.commit()
    scraper.upsert(db, oto[0], run, now + timedelta(hours=2), unknown)
    db.commit()
    assert db.get(Listing, l.id).condition_override == "to_renovate"
    # снятие: не видели 4 дня при полном обходе
    old = db.query(Listing).filter_by(source="olx", source_id="900000001").one()
    old.last_seen = now - timedelta(days=4)
    db.commit()
    assert scraper.mark_removed(db, "sale", "olx", now) == 1
    assert db.get(Listing, old.id).is_active is False
    # дубли: зеркало OLX -> Otodom по external_url, представитель — дешевле
    stats = dedup.rebuild_groups(db)
    assert stats["mirror"] == 1
    mirror = db.query(Listing).filter_by(source="olx", source_id="900000002").one()
    assert mirror.dedup_group == l.dedup_group and mirror.group_size == 2
    assert l.is_representative is True and mirror.is_representative is False   # 760k < 780k
    # «інша квартира»
    dedup.detach(db, mirror.id)
    assert db.get(Listing, mirror.id).group_size == 1 and db.get(Listing, l.id).group_size == 1


def test_shared_render_does_not_merge_different_flats(clean_db):
    """У квартир застройщика первая картинка — общий рендер дома. Ключ «только
    картинка» на первом прогоне прятал 31.7% каталога (группы до 44 разных квартир)."""
    db = clean_db
    img = "https://ireland.apollo.olxcdn.com/v1/files/render-of-the-building/image;s=1280x1024"

    def flat(sid, rooms, area, floor, price):
        return Listing(source="otodom", source_id=sid, offer_type="sale", url="https://x/%s" % sid,
                       rooms=rooms, area=area, floor=floor, price_pln=price, osiedle=u"Żerniki",
                       first_image=img, is_active=True)

    a, b, c, d = flat("1", 2, 35.2, 1, 423524), flat("2", 3, 68.0, 11, 1051343), \
        flat("3", 2, 35.2, 1, 470000), flat("4", 2, 35.2, 5, 430000)
    db.add_all([a, b, c, d])
    db.commit()
    stats = dedup.rebuild_groups(db)
    for x in (a, b, c, d):
        db.refresh(x)
    assert a.dedup_group == c.dedup_group and a.group_size == 2      # тот же лот подан дважды (цена врозь на 11%)
    assert stats["image"] == 1 and stats["numeric"] == 0
    assert b.group_size == 1 and d.group_size == 1                  # другой метраж / другой этаж — другие квартиры
    assert a.is_representative and not c.is_representative          # представитель — дешевле


def test_run_scrape_returns_id_and_reports_skipped(clean_db, fixtures, monkeypatch):
    """Прогон целиком на подставном источнике. Раньше `return run.id` после закрытия
    сессии падал с DetachedInstanceError, и каждый прогон — даже успешный —
    заканчивался в server.log строкой «прогон sale упал»."""
    db = clean_db
    oto, _ = _load(fixtures)

    class FakeSource(Otodom):
        name = "otodom"
        needs_details = False

        def iter_pages(self, offer_type, fetcher, start_page=1, settings=None):
            self.skipped["outside"] = 2
            yield 1, 1, oto

    class FakeFetcher:
        stats = {"requests": 1, "retries": 0, "blocked": 0, "browser": 0}

        def close(self):
            pass

    monkeypatch.setattr(scraper, "REGISTRY", {"otodom": FakeSource})
    monkeypatch.setattr(scraper, "get_source", lambda name: FakeSource())
    monkeypatch.setattr(scraper, "make_fetcher", lambda settings, stop_check=None, dump=False: FakeFetcher())
    calls = []

    def fake_post(db, run=None, kind="sale", with_translate=True):
        calls.append(("post", with_translate, scraper.is_running()))
        return u"пересчёты пропущены"

    monkeypatch.setattr(scraper, "post_process", fake_post)
    monkeypatch.setattr(scraper, "translate_after_run", lambda: calls.append(("translate", scraper.is_running())))
    run_id = scraper.run_scrape("sale", "otodom")
    run = db.get(ScrapeRun, run_id)
    assert run.status == "done" and run.full is True and run.seen == 2 and run.new == 2
    assert u"otodom: не взято — вне Вроцлава 2" in run.message
    assert scraper.is_running() is False
    # перевод — не шаг прогона: пересчёты идут без него, а очередь стартует, когда прогон
    # уже закрыт (иначе часы перевода на общей видеокарте держали бы 409 для триггеров)
    assert calls == [("post", False, True), ("translate", False)]


def test_gone_card_is_not_retried_forever(clean_db):
    """Otodom на снятое объявление отвечает 410 Gone (не 404): карточку больше не просим,
    ошибкой прогона это не считаем. Свежие — по дате подачи, а не по порядку вставки."""
    import httpx

    db = clean_db
    now = datetime.utcnow()
    gone = Listing(source="otodom", source_id="1", offer_type="rent", url="https://x/gone", title_pl="a",
                   is_active=True, details_fetched=False, posted_at=now, first_seen=now - timedelta(minutes=9))
    old = Listing(source="otodom", source_id="2", offer_type="rent", url="https://x/old", title_pl="b",
                  is_active=True, details_fetched=False, posted_at=now - timedelta(days=200), first_seen=now)
    db.add_all([gone, old])
    run = ScrapeRun(kind="rent", status="running")
    db.add(run)
    db.commit()
    asked = []

    class Src:
        name = "otodom"

        def fetch_details(self, raw, fetcher):
            asked.append(raw.url)
            req = httpx.Request("GET", raw.url)
            raise httpx.HTTPStatusError("410", request=req, response=httpx.Response(410, request=req))

    scraper._scrape_details(db, run, Src(), "rent", None, {"details_per_run": "1"}, {})
    assert asked == ["https://x/gone"]                        # поданное сегодня — первым, хотя вставлено раньше
    db.refresh(gone)
    assert gone.details_fetched is True and run.errors == 0
    scraper._scrape_details(db, run, Src(), "rent", None, {"details_per_run": "1"}, {})
    assert asked == ["https://x/gone", "https://x/old"]       # второй раз снятое не запрашивается


def test_pause_and_watchdog(clean_db):
    db = clean_db
    until = scraper.set_pause(db, 2)
    assert scraper.paused_until(db) is not None and until > datetime.utcnow()
    scraper.resume(db)
    assert scraper.paused_until(db) is None
    run = ScrapeRun(kind="sale", status="running", last_beat=datetime.utcnow() - timedelta(hours=4))
    db.add(run)
    db.commit()
    assert scraper.close_stale_runs(db) == 1
    assert db.get(ScrapeRun, run.id).status == "failed"


def test_osiedle_by_coordinates(clean_db, monkeypatch):
    """OLX даёт координаты и не даёт осиедле, Otodom даёт оба. Размеченные точки
    Otodom работают картой: сосед по дому получает его осиедле, а на отшибе
    система молчит, а не угадывает."""
    from app import geo_knn

    db = clean_db
    monkeypatch.setattr(geo_knn, "MIN_MAP_POINTS", 10)   # в бою порог 500 точек
    # 12 объявлений Otodom в одном месте (Gaj) и 12 в другом (Jagodno)
    pts = [(51.0800 + i * 0.0002, 17.0300 + i * 0.0002, u"Gaj") for i in range(12)]
    pts += [(51.0500 + i * 0.0002, 17.0600 + i * 0.0002, u"Jagodno") for i in range(12)]
    for i, (la, lo, name) in enumerate(pts):
        db.add(Listing(source="otodom", source_id="o%d" % i, offer_type="sale", is_active=True,
                       lat=la, lon=lo, osiedle=name))
    near = Listing(source="olx", source_id="n1", offer_type="rent", is_active=True,
                   lat=51.0802, lon=17.0302)                      # во дворе у Gaj
    far = Listing(source="olx", source_id="n2", offer_type="rent", is_active=True,
                  lat=51.2000, lon=17.3000)                       # за городом, соседей нет
    no_geo = Listing(source="olx", source_id="n3", offer_type="rent", is_active=True)
    db.add_all([near, far, no_geo])
    db.commit()

    res = geo_knn.fill_missing(db)
    db.refresh(near); db.refresh(far); db.refresh(no_geo)
    assert res["filled"] == 1 and res["unsure"] == 1
    assert near.osiedle == u"Gaj" and near.osiedle_src == "geo"
    assert far.osiedle is None                                    # далеко — молчим
    assert no_geo.osiedle is None                                 # без координат нечего решать
    # свои же догадки в карту не попадают, иначе ошибка расползётся
    assert all(p[2] != "geo" for p in [(0, 0, x[2]) for x in pts])
    assert geo_knn.build_map(db).size == 24
