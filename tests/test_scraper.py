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
