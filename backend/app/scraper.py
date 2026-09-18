# -*- coding: utf-8 -*-
"""Прогон: обход выдачи источников, upsert, история цен, хвост с карточками
Otodom, снятие, пересчёты.

Правила, оплаченные потерянными прогонами в Киеве:
- отметка жизни (`last_beat`) пишется ОТДЕЛЬНОЙ сессией: commit на сессии с
  открытым курсором рвёт курсор;
- ошибка записи -> rollback, иначе сессия отравлена до конца прогона;
- источники по очереди, никогда параллельно (один IP);
- пауза/стоп проверяются перед каждым запросом и сворачивают прогон за
  полминуты; такой прогон — `stopped`, а не `done`, потому что он неполный;
- страница фиксируется после коммита (`resume:<kind>:<source>`), упавший
  прогон продолжает с неё, а не с первой.
"""
import json
import logging
import threading
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import INACTIVE_AFTER_DAYS, WATCHDOG_MINUTES
from .db import SessionLocal
from .fetcher import BlockedError, StopRequested, make_fetcher
from .models import Listing, PriceHistory, ScrapeRun, UnknownValue
from .normalize import normalize
from .settings_store import get_setting, get_settings, set_setting
from .sources import REGISTRY, RawListing, get_source

log = logging.getLogger("scraper")

_state = {"running": False, "run_id": None, "stop": False, "kind": None, "lock": threading.Lock()}
PAUSE_FOREVER = "9999-12-31T00:00:00"

# поля, которые прогон НЕ перетирает: ручные правки владельца и производные
PROTECTED = {"condition_override", "osiedle_override", "note", "is_favorite",
             "dedup_detached", "title_uk", "description_uk", "translated_at",
             "translate_provider", "translate_version"}
# что даёт только карточка — списком выдачи не затирать
DETAILS_ONLY = {"description_pl", "characteristics_json", "raw_json"}
# причины Source.skipped — для сообщения прогона
SKIP_LABELS = {"investment": u"инвестиций целиком", "outside": u"вне Вроцлава"}


# ---------- состояние ----------
def is_running() -> bool:
    return _state["running"]


def current_run_id() -> Optional[int]:
    return _state["run_id"]


def request_stop():
    _state["stop"] = True


def paused_until(db: Session) -> Optional[datetime]:
    v = get_setting(db, "scrape_paused_until")
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt > datetime.utcnow() else None


def set_pause(db: Session, hours: float) -> datetime:
    until = datetime.fromisoformat(PAUSE_FOREVER) if hours <= 0 else \
        datetime.utcnow() + timedelta(hours=hours)
    set_setting(db, "scrape_paused_until", until.isoformat())
    request_stop()
    return until


def resume(db: Session):
    set_setting(db, "scrape_paused_until", "")


def _stop_requested() -> bool:
    if _state["stop"]:
        return True
    # пауза могла быть включена из интерфейса уже во время прогона
    db = SessionLocal()
    try:
        return paused_until(db) is not None
    finally:
        db.close()


def beat_apart(run_id: int, phase: Optional[str] = None, **counters):
    """Отметка жизни отдельной сессией (см. докстринг модуля)."""
    db = SessionLocal()
    try:
        vals = {"last_beat": datetime.utcnow()}
        if phase:
            vals["phase"] = phase
        vals.update(counters)
        db.execute(update(ScrapeRun).where(ScrapeRun.id == run_id).values(**vals))
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("отметка жизни не записалась: %s", e)
        db.rollback()
    finally:
        db.close()


def close_stale_runs(db: Session) -> int:
    """Сторож: прогон без отметки жизни дольше WATCHDOG_MINUTES — failed."""
    limit = datetime.utcnow() - timedelta(minutes=WATCHDOG_MINUTES)
    stale = db.query(ScrapeRun).filter(ScrapeRun.status == "running",
                                       ScrapeRun.last_beat < limit).all()
    for r in stale:
        r.status = "failed"
        r.finished_at = datetime.utcnow()
        r.message = (r.message or "") + u"\nзакрыт сторожем: нет отметки жизни %d мин" % WATCHDOG_MINUTES
    if stale:
        db.commit()
    if not is_running():
        _state["run_id"] = None
    return len(stale)


# ---------- upsert ----------
def _record_unknown(bucket: Dict[tuple, int], field: str, values: List[str]):
    for v in values:
        v = (v or "").strip()[:120]
        if v:
            bucket[(field, v)] = bucket.get((field, v), 0) + 1


def flush_unknown(db: Session, bucket: Dict[tuple, int]):
    for (field, value), n in bucket.items():
        row = db.query(UnknownValue).filter_by(field=field, value_pl=value).one_or_none()
        if row is None:
            db.add(UnknownValue(field=field, value_pl=value, count=n))
        else:
            row.count = (row.count or 0) + n
            row.last_seen = datetime.utcnow()
    db.commit()
    bucket.clear()


def upsert(db: Session, raw: RawListing, run: ScrapeRun, now: datetime,
           unknown: Dict[tuple, int]) -> Listing:
    d = normalize(raw)
    _record_unknown(unknown, "place", d.pop("_unknown_places", []))
    row = db.query(Listing).filter_by(source=raw.source, source_id=str(raw.source_id)).one_or_none()
    if row is None:
        row = Listing(**{k: v for k, v in d.items() if v is not None})
        row.first_seen = row.last_seen = now
        row.is_active = True
        row.details_fetched = not raw.needs_details
        db.add(row)
        db.flush()
        if row.price_pln:
            db.add(PriceHistory(listing_id=row.id, price_pln=row.price_pln, seen_at=now))
        run.new += 1
        return row
    new_price = d.get("price_pln")
    if new_price and row.price_pln and abs(new_price - row.price_pln) > 0.5:
        db.add(PriceHistory(listing_id=row.id, price_pln=new_price, seen_at=now))
        run.price_changes += 1
    elif new_price and not row.price_pln:
        db.add(PriceHistory(listing_id=row.id, price_pln=new_price, seen_at=now))
    for k, v in d.items():
        if v is None or k in PROTECTED:
            continue
        if raw.needs_details and k in DETAILS_ONLY and getattr(row, k):
            continue
        setattr(row, k, v)
    if not raw.needs_details:
        row.details_fetched = True
    row.last_seen = now
    if not row.is_active:
        row.is_active = True
        row.removed_at = None
    run.updated += 1
    return row


# ---------- фазы ----------
def _resume_key(kind: str, source: str) -> str:
    return "resume:%s:%s" % (kind, source)


def _resume_page(db: Session, kind: str, source: str) -> int:
    v = get_setting(db, _resume_key(kind, source))
    if not v or "|" not in v:
        return 1
    page, iso = v.split("|", 1)
    try:
        if datetime.utcnow() - datetime.fromisoformat(iso) > timedelta(hours=20):
            return 1     # вчерашняя точка — выдача уже другая
        return max(1, int(page))
    except ValueError:
        return 1


def _scrape_list(db: Session, run: ScrapeRun, src, kind: str, fetcher, settings, unknown) -> bool:
    """Обход выдачи одного источника. True — дошли до конца."""
    start = _resume_page(db, kind, src.name)
    if start > 1:
        log.info("%s/%s: продолжаю с страницы %d", src.name, kind, start)
    now = datetime.utcnow()
    done = False
    total_pages = None
    for page, total_pages, items in src.iter_pages(kind, fetcher, start, settings):
        now = datetime.utcnow()
        for raw in items:
            try:
                upsert(db, raw, run, now, unknown)
                run.seen += 1
            except Exception as e:  # noqa: BLE001 — одна кривая запись не должна ронять страницу
                db.rollback()
                run.errors += 1
                log.warning("%s %s: %s", src.name, raw.source_id, e)
        run.pages += 1
        try:
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            run.errors += 1
            log.error("commit страницы %d: %s", page, e)
        set_setting(db, _resume_key(kind, src.name), "%d|%s" % (page + 1, datetime.utcnow().isoformat()))
        beat_apart(run.id, "list:%s %d/%s" % (src.name, page, total_pages or "?"),
                   pages=run.pages, seen=run.seen, new=run.new, updated=run.updated,
                   price_changes=run.price_changes, errors=run.errors)
        if _stop_requested():
            raise StopRequested()
    done = True
    set_setting(db, _resume_key(kind, src.name), "")
    return done


def _scrape_details(db: Session, run: ScrapeRun, src, kind: str, fetcher, settings, unknown):
    """Хвост: карточки Otodom у объявлений без описания, самые новые первыми."""
    try:
        limit = int(float(settings.get("details_per_run") or 600))
    except ValueError:
        limit = 600
    # Свежие — по дате ПОДАЧИ, а не по first_seen: в первом прогоне first_seen — это
    # порядок нашей вставки, и самыми «новыми» выходили последние страницы выдачи.
    # 18.09.2026 первые 250 карточек хвоста ушли на запасы застройщиков с глубоких
    # страниц, а объявления сегодняшнего дня ждали бы очереди ~16 прогонов
    # (9.4 тыс. объявлений при 600 карточках за прогон).
    ids = [r[0] for r in db.execute(
        select(Listing.id).where(Listing.source == src.name, Listing.offer_type == kind,
                                 Listing.is_active.is_(True), Listing.details_fetched.is_(False))
        .order_by(Listing.posted_at.desc(), Listing.first_seen.desc()).limit(limit)).all()]
    if not ids:
        return
    log.info("%s/%s: хвост, карточек %d", src.name, kind, len(ids))
    n = 0
    for lid in ids:
        row = db.get(Listing, lid)
        if row is None:
            continue
        raw = RawListing(source=row.source, source_id=row.source_id, url=row.url,
                         offer_type=row.offer_type, title=row.title_pl or u"",
                         images=json.loads(row.images_json or "[]"))
        try:
            raw = src.fetch_details(raw, fetcher)
            upsert(db, raw, run, datetime.utcnow(), unknown)
            row.details_fetched = True
            run.details += 1
            db.commit()
        except StopRequested:
            db.rollback()
            raise
        except BlockedError:
            db.rollback()
            raise
        except Exception as e:  # noqa: BLE001
            db.rollback()
            run.errors += 1
            # 404 = объявление уже снято; не ходить по кругу
            if "404" in str(e):
                db.execute(update(Listing).where(Listing.id == lid).values(details_fetched=True))
                db.commit()
            log.warning("карточка %s: %s", row.url, e)
        n += 1
        if n % 10 == 0:
            beat_apart(run.id, "details:%s %d/%d" % (src.name, n, len(ids)),
                       details=run.details, errors=run.errors, updated=run.updated)
            if _stop_requested():
                raise StopRequested()


def mark_removed(db: Session, kind: str, source: str, now: datetime) -> int:
    """Снятие — только после ПОЛНОГО обхода источника; строки не удаляются."""
    limit = now - timedelta(days=INACTIVE_AFTER_DAYS)
    res = db.execute(update(Listing)
                     .where(Listing.source == source, Listing.offer_type == kind,
                            Listing.is_active.is_(True), Listing.last_seen < limit)
                     .values(is_active=False, removed_at=now))
    db.commit()
    return res.rowcount or 0


def post_process(db: Session, run: Optional[ScrapeRun] = None, kind: str = "sale",
                 with_translate: bool = True):
    """Пересчёты после прогона. Каждый шаг ловит своё исключение: сломанная
    доходность не должна отменять склейку дублей. Прогон зовёт без перевода —
    см. translate_after_run."""
    from . import analytics, dedup, fx, rent_analytics, translate
    steps = [
        ("дубли", lambda: dedup.rebuild_groups(db)),
        ("курсы", lambda: (fx.refresh(db), fx.apply_to_listings(db))),
        ("выгодность", lambda: analytics.recompute_deal_scores(db)),
        ("доходность", lambda: rent_analytics.recompute_yields(db)),
    ]
    if with_translate:
        steps.append(("перевод", lambda: translate.translate_pending(db, stop_check=_stop_requested)))
    msgs = []
    for name, fn in steps:
        if _state["stop"]:
            break
        try:
            res = fn()
            msgs.append(u"%s: %s" % (name, res if res is not None else "ok"))
            if run:
                beat_apart(run.id, "post:" + name)
        except StopRequested:
            msgs.append(u"%s: остановлено" % name)
            break
        except Exception as e:  # noqa: BLE001
            db.rollback()
            msgs.append(u"%s: ОШИБКА %s" % (name, e))
            log.error("пересчёт «%s»: %s\n%s", name, e, traceback.format_exc())
    return u"; ".join(map(str, msgs))


def _translate_job():
    from . import translate
    db = SessionLocal()
    try:
        log.info("перевод после прогона: %s", translate.translate_pending(db, stop_check=_stop_requested))
    except Exception as e:  # noqa: BLE001 — поток фоновый, уронить ему некого
        log.error("перевод после прогона: %s\n%s", e, traceback.format_exc())
    finally:
        db.close()


def translate_after_run():
    """Перевод очереди — ПОСЛЕ закрытия прогона и в своём потоке, а не шагом прогона.

    Пока перевод был шагом пост-обработки, прогон числился идущим, пока не переведены
    до 3000 заголовков и суточный потолок описаний. Замер 18.09.2026 (видеокарту делит
    другой клиент Ollama, модели вытесняют друг друга): 20 заголовков и 20 описаний —
    24 минуты, 36 с на запрос. Вся очередь первого дня — десятки часов, и всё это время
    триггер продажи получал бы 409 (у него одна попытка): расписание срывалось бы на
    сутки-двое. Скрап и перевод делят только базу (WAL, короткие транзакции), поэтому
    идут независимо; от наложения переводов защищает замок в translate_pending, стоп и
    пауза из интерфейса действуют как прежде (stop_check)."""
    threading.Thread(target=_translate_job, name="translate-after-run", daemon=True).start()


# ---------- прогон ----------
def run_scrape(kind: str = "sale", sources: str = "all", dump: bool = False) -> int:
    """Синхронный прогон (main.py запускает в потоке). Возвращает id прогона."""
    with _state["lock"]:
        if _state["running"]:
            raise RuntimeError(u"прогон уже идёт")
        _state["running"] = True
        _state["stop"] = False
        _state["kind"] = kind
    db = SessionLocal()
    run = ScrapeRun(kind=kind, source=sources, status="running", phase="start")
    db.add(run)
    db.commit()
    # id запоминаем сразу: в конце сессия уже закрыта, а commit «просрочил» атрибуты,
    # и `return run.id` падал с DetachedInstanceError — КАЖДЫЙ прогон, даже успешный,
    # заканчивался в server.log строкой «прогон sale упал» (замечено 18.09.2026)
    run_id = run.id
    _state["run_id"] = run_id
    settings = get_settings(db)
    enabled = [s.strip() for s in (settings.get("sources_enabled") or "otodom,olx").split(",") if s.strip()]
    if sources != "all":
        enabled = [s for s in enabled if s == sources]
    unknown: Dict[tuple, int] = {}
    fetcher = make_fetcher(settings, stop_check=_stop_requested, dump=dump)
    completed: List[str] = []
    status = "done"
    notes: List[str] = []
    try:
        if paused_until(db):
            raise StopRequested()
        for name in enabled:
            if name not in REGISTRY:
                notes.append(u"неизвестный источник %s" % name)
                continue
            src = get_source(name)
            try:
                if _scrape_list(db, run, src, kind, fetcher, settings, unknown):
                    completed.append(name)
                if src.needs_details:
                    _scrape_details(db, run, src, kind, fetcher, settings, unknown)
            except StopRequested:
                raise
            except BlockedError as e:
                run.errors += 1
                notes.append(u"%s: блок анти-бота (%s) — источник пропущен" % (name, e))
                log.error("%s: %s", name, e)
                db.rollback()
            except Exception as e:  # noqa: BLE001
                run.errors += 1
                notes.append(u"%s: %s" % (name, e))
                log.error("%s: %s\n%s", name, e, traceback.format_exc())
                db.rollback()
            if src.skipped:
                notes.append(u"%s: не взято — %s" % (name, u", ".join(
                    u"%s %d" % (SKIP_LABELS.get(k, k), n) for k, n in sorted(src.skipped.items()))))
        now = datetime.utcnow()
        for name in completed:
            run.removed += mark_removed(db, kind, name, now)
        run.full = len(completed) == len(enabled)
        flush_unknown(db, unknown)
        db.commit()
        notes.append(post_process(db, run, kind, with_translate=False))
    except StopRequested:
        status = "stopped"
        notes.append(u"остановлено (стоп/пауза)")
        db.rollback()
    except Exception as e:  # noqa: BLE001
        status = "failed"
        notes.append(u"сбой: %s" % e)
        log.error("прогон %d: %s\n%s", run_id, e, traceback.format_exc())
        db.rollback()
    finally:
        fetcher.close()
        try:
            run = db.get(ScrapeRun, run_id) or run
            run.status = status
            run.finished_at = datetime.utcnow()
            run.last_beat = run.finished_at
            run.phase = "finished"
            run.message = u"\n".join(n for n in notes if n) + u"\nзапросов %d, повторов %d, блоков %d, браузер %d" % (
                fetcher.stats["requests"], fetcher.stats["retries"], fetcher.stats["blocked"], fetcher.stats["browser"])
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.error("не смог закрыть прогон: %s", e)
            db.rollback()
        finally:
            db.close()
            with _state["lock"]:
                _state["running"] = False
                _state["stop"] = False
                _state["kind"] = None
    if status == "done":
        translate_after_run()
    return run_id


def last_run(db: Session, kind: str) -> Optional[ScrapeRun]:
    return (db.query(ScrapeRun).filter(ScrapeRun.kind == kind)
            .order_by(ScrapeRun.started_at.desc()).first())


def last_full_success(db: Session, kind: str) -> Optional[datetime]:
    r = (db.query(ScrapeRun).filter(ScrapeRun.kind == kind, ScrapeRun.status == "done",
                                    ScrapeRun.full.is_(True))
         .order_by(ScrapeRun.finished_at.desc()).first())
    return r.finished_at if r else None
