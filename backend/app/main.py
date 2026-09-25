# -*- coding: utf-8 -*-
"""API и раздача фронтенда. Контракт — docs/API.md.

Сервер закрыт паролем (WRO_WEB_PASS) мидлваром — накрывает всё, включая
статику. Пустой пароль = открыт всем, об этом предупреждение в логе при старте
(так работает только превью на копии базы).
"""
import base64
import csv
import io
import json
import logging
import os
import random
import re
import secrets
import threading
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from . import analytics, dedup, fx, geo, i18n, presentation, rent_analytics, scraper, translate
from .config import (DATA_DIR, DB_PATH, FRONTEND_DIST, SAFE_KEYS, SCAN_HOUR_RENT,
                     SCAN_HOURS_SALE, SCAN_JITTER_SEC, SCAN_MINUTE_RENT, SECRET_KEYS,
                     SECRET_MASK, VERSION)
from .db import SessionLocal, ensure_columns, get_db
from .models import (AccessLog, Favorite, Listing, PriceHistory, ScrapeRun, UnknownValue,
                     UserAction, UserProfile)
from .settings_store import get_float, get_settings, set_setting
from .tz import KYIV, install_json_encoder

# ---------- логи ----------
# Под uvicorn basicConfig ничего не делает — ставим уровень и файл явно.
# Ротацию делает сам Python: на Windows нет launchd со StandardOutPath.
_root = logging.getLogger()
_root.setLevel(logging.INFO)
if not any(isinstance(h, RotatingFileHandler) for h in _root.handlers):
    _fh = RotatingFileHandler(str(DATA_DIR / "server.log"), maxBytes=20 * 1024 * 1024,
                              backupCount=3, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _root.addHandler(_fh)
logging.getLogger("httpx").setLevel(logging.WARNING)   # его INFO — половина лога
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("main")

app = FastAPI(title=u"Wrocław Analyzer", version=VERSION)
install_json_encoder()

# ---------- пароль, логины, роли ----------
# WRO_WEB_USERS = "admin:пароль;yulia:пароль2" — несколько логинов; WRO_WEB_USER /
# WRO_WEB_PASS оставлены для триггеров и совместимости (это логин администратора).
# Администратор — WRO_WEB_USER (по умолчанию admin): ему настройки, прогоны и
# журнал; остальным — каталог, карточки, избранное, заметки, экспорт.
ADMIN_USER = os.environ.get("WRO_WEB_USER", "admin")


def _users() -> Dict[str, str]:
    users: Dict[str, str] = {}
    for part in re.split(r"[;,]", os.environ.get("WRO_WEB_USERS", "")):
        if ":" in part:
            u, _, pw = part.partition(":")
            if u.strip() and pw:
                users[u.strip()] = pw
    pw = os.environ.get("WRO_WEB_PASS", "")
    if pw:
        users.setdefault(ADMIN_USER, pw)
    return users


if not _users():
    log.warning(u"WRO_WEB_PASS / WRO_WEB_USERS не заданы — сервер открыт всем, кто до него дотянется")

# Что считать действием человека (в журнал), а что — шумом страницы (нет).
_NOISE = ("/api/summary", "/api/runs", "/api/translate/status", "/api/jobs", "/api/health",
          "/api/geo", "/api/me", "/api/settings", "/api/activity", "/api/stats",
          "/api/price_index", "/api/trends", "/api/rent/yield_top", "/api/translate/unknown_values")


def _classify(method: str, path: str):
    """-> (action, listing_id) или None, если писать в журнал нечего."""
    m = re.match(r"^/api/listings/(\d+)(?:/(\w+))?$", path)
    if m:
        lid = int(m.group(1))
        sub = m.group(2)
        if method == "GET" and not sub:
            return "view_card", lid
        if sub in ("favorite", "manual", "detach", "translate"):
            return sub, lid
        return None
    if path == "/api/listings" and method == "GET":
        return "search", None
    if path.startswith("/api/export") or path.startswith("/api/contacts/export"):
        return "export", None
    if path.startswith("/api/presentation"):
        return "presentation", None
    if path.startswith("/api/contacts"):
        return "contacts", None
    if method == "POST" and path.startswith("/api/") and not path.startswith(_NOISE):
        return "other", None
    return None


def _write_access(user: str, method: str, path: str, query: str):
    cls = _classify(method, path)
    if not cls:
        return
    db = SessionLocal()
    try:
        db.add(AccessLog(user=user, action=cls[0], method=method, path=path,
                         query=query[:500] if query else None, listing_id=cls[1]))
        db.commit()
    except Exception as e:  # noqa: BLE001 — журнал не должен ронять запрос
        db.rollback()
        log.warning("журнал доступа: %s", e)
    finally:
        db.close()


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    users = _users()
    user = ADMIN_USER
    if users and request.url.path != "/api/health":
        auth = request.headers.get("authorization", "")
        ok = False
        if auth.startswith("Basic "):
            try:
                u, _, pwd = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                ok = u in users and secrets.compare_digest(pwd, users[u])
                user = u if ok else user
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response(u"Потрібен вхід", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Wroclaw Analyzer"'})
    request.state.user = user
    response = await call_next(request)
    if request.url.path.startswith("/api/") and response.status_code < 400:
        _write_access(user, request.method, request.url.path, str(request.url.query or ""))
    return response


def current_user(request: Request) -> str:
    return getattr(request.state, "user", ADMIN_USER)


def is_admin(request: Request) -> bool:
    return current_user(request) == ADMIN_USER


def require_admin(request: Request):
    """Настройки, прогоны, пересчёты и журнал — только администратору."""
    if not is_admin(request):
        raise HTTPException(403, u"лише для адміністратора")


@app.get("/api/me")
def api_me(request: Request):
    return {"user": current_user(request), "role": "admin" if is_admin(request) else "viewer",
            "users": sorted(_users()) if is_admin(request) else None}


# ---------- сериализация ----------
def _images(l: Listing, n: int = 3) -> List[str]:
    try:
        return (json.loads(l.images_json or "[]") or [])[:n]
    except ValueError:
        return []


def seller_key(l: Listing) -> Optional[str]:
    if l.seller_id:
        return l.seller_id
    if l.seller_phone:
        return "phone:" + l.seller_phone
    if l.seller_name:
        return "name:" + l.seller_name.strip().lower()
    return None


# ---------- обране (у каждого логина своё) ----------
def fav_ids(db: Session, user: str, listing_ids: Optional[List[int]] = None) -> set:
    q = select(Favorite.listing_id).where(Favorite.user == user)
    if listing_ids is not None:
        if not listing_ids:
            return set()
        q = q.where(Favorite.listing_id.in_(listing_ids))
    return {r[0] for r in db.execute(q).all()}


def fav_counts(db: Session) -> Dict[str, int]:
    return {u: n for u, n in db.execute(
        select(Favorite.user, func.count()).group_by(Favorite.user)).all()}


def row_dict(l: Listing, ph: Optional[dict] = None, is_fav: bool = False) -> Dict:
    cond = l.condition_override or l.condition or "unknown"
    osiedle = l.osiedle_override or l.osiedle
    district = geo.district_of(osiedle) or l.district
    start = l.posted_at or l.first_seen
    d = {
        "id": l.id, "source": l.source, "source_id": l.source_id, "url": l.url,
        "offer_type": l.offer_type, "external_url": l.external_url,
        "title_pl": l.title_pl, "title_uk": l.title_uk,
        "price_pln": l.price_pln, "price_usd": l.price_usd, "price_eur": l.price_eur,
        "price_per_m2": l.price_per_m2, "czynsz_pln": l.czynsz_pln, "hide_price": l.hide_price,
        "area": l.area, "rooms": l.rooms, "floor": l.floor, "floor_uk": i18n.floor_uk(l.floor),
        "floors_total": l.floors_total, "build_year": l.build_year,
        "market": l.market, "market_uk": i18n.uk("market", l.market),
        "building_type": l.building_type, "building_type_uk": i18n.uk("building_type", l.building_type),
        "condition": cond, "condition_uk": i18n.uk("condition", cond),
        "condition_src": "manual" if l.condition_override else l.condition_src,
        "district": district, "district_uk": geo.district_uk(district),
        "osiedle": osiedle, "osiedle_uk": geo.osiedle_uk(osiedle),
        "osiedle_src": "manual" if l.osiedle_override else (l.osiedle_src or "source"),
        "street": l.street, "lat": l.lat, "lon": l.lon,
        "seller_type": l.seller_type, "seller_type_uk": i18n.uk("seller_type", l.seller_type),
        "seller_name": l.seller_name, "seller_phone": l.seller_phone, "seller_id": l.seller_id,
        "seller_key": seller_key(l), "no_commission": l.no_commission,
        "images": _images(l), "image_count": l.image_count,
        "posted_at": l.posted_at, "first_seen": l.first_seen, "last_seen": l.last_seen,
        "is_active": l.is_active, "removed_at": l.removed_at,
        "days_on_market": (datetime.utcnow() - start).days if start else None,
        "dedup_group": l.dedup_group, "group_size": l.group_size, "is_representative": l.is_representative,
        # 'investment' — в группе РАЗНЫЕ квартиры одной инвестиции, а не одна и та же
        "group_kind": l.group_kind,
        "discount_pct": l.discount_pct, "baseline_sqm": l.baseline_sqm,
        "baseline_level": l.baseline_level, "baseline_level_uk": i18n.LEVELS.get(l.baseline_level or "", ("", ""))[1],
        "baseline_count": l.baseline_count, "deal_thin_base": l.deal_thin_base,
        "yield_pct": l.yield_pct, "rent_median_pln": l.rent_median_pln,
        "rent_baseline_level": l.rent_baseline_level, "rent_baseline_count": l.rent_baseline_count,
        "price_changes": (ph or {}).get("changes", 0), "price_drop_pct": (ph or {}).get("drop_pct"),
        "is_favorite": bool(is_fav), "translated": bool(l.title_uk),
        "furnished": l.furnished, "elevator": l.elevator,
    }
    return d


def _price_stats(db: Session, ids: List[int]) -> Dict[int, dict]:
    """Число смен цены и % от первой цены — одним запросом на страницу."""
    if not ids:
        return {}
    rows = db.execute(select(PriceHistory.listing_id, PriceHistory.price_pln, PriceHistory.seen_at)
                      .where(PriceHistory.listing_id.in_(ids)).order_by(PriceHistory.seen_at)).all()
    out: Dict[int, dict] = {}
    first: Dict[int, float] = {}
    for lid, price, _ in rows:
        o = out.setdefault(lid, {"changes": -1, "drop_pct": None})
        o["changes"] += 1
        first.setdefault(lid, price)
        if first[lid] and price:
            o["drop_pct"] = round((price - first[lid]) / first[lid] * 100, 1)
    for o in out.values():
        o["changes"] = max(0, o["changes"])
        if o["changes"] == 0:
            o["drop_pct"] = None
    return out


def _characteristics(l: Listing) -> List[dict]:
    try:
        chars = json.loads(l.characteristics_json or "{}") or {}
    except ValueError:
        chars = {}
    field_of = {"market": "market", "building_type": "building_type", "builttype": "building_type",
                "building_material": "building_material", "construction_status": "construction_status",
                "windows_type": "windows", "heating": "heating", "building_ownership": "ownership",
                "extras_types": "extras", "security_types": "extras", "media_types": "extras",
                "equipment_types": "extras"}
    out = []
    for key, c in chars.items():
        if not isinstance(c, dict):
            continue
        label_pl, label_uk = i18n.label_pair(key)
        if c.get("label"):
            label_pl = c["label"]
        value_pl = c.get("localized") or c.get("value")
        value_uk = None
        fld = field_of.get(key)
        raw_val = c.get("value")
        if fld == "extras" and raw_val:
            from .normalize import canon_extra
            parts = raw_val if isinstance(raw_val, list) else str(raw_val).replace("::", ",").split(",")
            uks = [i18n.uk("extras", canon_extra(p)) or p for p in parts if p]
            value_uk = u", ".join(uks)
        elif fld:
            from .normalize import _map, _BUILDING, _MATERIAL, _STATUS, _OWNERSHIP, _HEATING, _WINDOWS
            table = {"building_type": _BUILDING, "building_material": _MATERIAL,
                     "construction_status": _STATUS, "ownership": _OWNERSHIP,
                     "heating": _HEATING, "windows": _WINDOWS}.get(fld)
            canon = _map(table, raw_val) if table else None
            if fld == "market":
                from .normalize import parse_market
                canon = parse_market(raw_val)
            value_uk = i18n.uk(fld, canon)
        elif key in ("floor_no", "floor_select"):
            from .normalize import parse_floor
            value_uk = i18n.floor_uk(parse_floor(raw_val))
        elif raw_val is not None and str(raw_val).lower() in i18n.YES_NO:
            value_uk = i18n.YES_NO[str(raw_val).lower()][1]
        out.append({"key": key, "label_pl": label_pl, "label_uk": label_uk,
                    "value_pl": value_pl if value_pl is not None else "", "value_uk": value_uk})
    return out


def full_dict(db: Session, l: Listing, user: str = "") -> Dict:
    d = row_dict(l, _price_stats(db, [l.id]).get(l.id), is_fav=l.id in fav_ids(db, user, [l.id]))
    d.update({
        "description_pl": l.description_pl, "description_uk": l.description_uk,
        "translated_at": l.translated_at, "translate_provider": l.translate_provider,
        "characteristics": _characteristics(l),
        "images": _images(l, 40),
        "price_history": [{"price_pln": p, "seen_at": at} for p, at in db.execute(
            select(PriceHistory.price_pln, PriceHistory.seen_at).where(PriceHistory.listing_id == l.id)
            .order_by(PriceHistory.seen_at)).all()],
        "note": l.note, "raw_available": bool(l.raw_json), "details_fetched": l.details_fetched,
        "extras": json.loads(l.extras_json or "[]"), "media": json.loads(l.media_json or "[]"),
        "security": json.loads(l.security_json or "[]"),
        "heating": l.heating, "heating_uk": i18n.uk("heating", l.heating),
        "windows": l.windows, "windows_uk": i18n.uk("windows", l.windows),
        "ownership": l.ownership, "ownership_uk": i18n.uk("ownership", l.ownership),
        "building_material": l.building_material, "building_material_uk": i18n.uk("building_material", l.building_material),
        "construction_status": l.construction_status, "construction_status_uk": i18n.uk("construction_status", l.construction_status),
        "address_raw": l.address_raw, "location_raw": l.location_raw,
    })
    d["extras_uk"] = [i18n.uk("extras", x) or x for x in d["extras"]]
    dupes = db.query(Listing).filter(Listing.dedup_group == l.dedup_group, Listing.id != l.id).all() \
        if l.dedup_group else []
    d["dupes"] = [{"id": x.id, "source": x.source, "url": x.url, "price_pln": x.price_pln,
                   "seller_type": x.seller_type, "seller_type_uk": i18n.uk("seller_type", x.seller_type),
                   "seller_name": x.seller_name, "first_seen": x.first_seen, "is_active": x.is_active,
                   "rooms": x.rooms, "area": x.area, "floor": x.floor} for x in dupes]
    coef = {}
    try:
        coef = json.loads(get_settings(db).get("area_coef_sale") or "{}")
    except ValueError:
        pass
    band_lbl = analytics.band_label(analytics.band(l.area))
    d["deal_explain"] = None if l.discount_pct is None else {
        "level": l.baseline_level, "level_uk": i18n.LEVELS.get(l.baseline_level or "", ("", ""))[1],
        "key": json.loads(l.baseline_key) if l.baseline_key else None,
        "pool_size": l.baseline_count, "median_sqm": l.baseline_sqm,
        "price_sqm_adj": l.price_sqm_adj, "band": band_lbl, "area_coef": coef.get(band_lbl),
        "thin": l.deal_thin_base, "discount_pct": l.discount_pct,
    }
    d["rent_explain"] = rent_analytics.rent_explain(db, l)
    if d["rent_explain"]:
        d["rent_explain"]["level_uk"] = i18n.LEVELS.get(l.rent_baseline_level or "", ("", ""))[1]
    return d


# ---------- фильтры каталога ----------
def _csv(v: Optional[str]) -> List[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _apply_filters(q, p: dict):
    # offer_type=all — продажа и аренда вместе; нужно разделу «Обране», где
    # квартира на продажу и квартира в аренду лежат одним списком
    offer_type = p.get("offer_type") or "sale"
    if offer_type != "all":
        q = q.filter(Listing.offer_type == offer_type)
    if str(p.get("active", "1")) != "0":
        q = q.filter(Listing.is_active.is_(True))
    if str(p.get("dupes", "0")) != "1":
        q = q.filter(Listing.is_representative.is_(True))
    rooms = [int(x) for x in _csv(p.get("rooms")) if x.isdigit()]
    if rooms:
        conds = [Listing.rooms == r for r in rooms if r < 4]
        if any(r >= 4 for r in rooms):
            conds.append(Listing.rooms >= 4)
        q = q.filter(or_(*conds))
    for key, col in (("price_min", Listing.price_pln), ("area_min", Listing.area),
                     ("sqm_min", Listing.price_per_m2), ("build_year_min", Listing.build_year),
                     ("floor_min", Listing.floor), ("discount_min", Listing.discount_pct),
                     ("yield_min", Listing.yield_pct)):
        if p.get(key) not in (None, ""):
            q = q.filter(col >= float(p[key]))
    for key, col in (("price_max", Listing.price_pln), ("area_max", Listing.area),
                     ("sqm_max", Listing.price_per_m2), ("build_year_max", Listing.build_year),
                     ("floor_max", Listing.floor)):
        if p.get(key) not in (None, ""):
            q = q.filter(col <= float(p[key]))
    if _csv(p.get("district")):
        q = q.filter(Listing.district.in_(_csv(p["district"])))
    if _csv(p.get("osiedle")):
        vals = _csv(p["osiedle"])
        q = q.filter(or_(Listing.osiedle_override.in_(vals),
                         (Listing.osiedle_override.is_(None)) & (Listing.osiedle.in_(vals))))
    if p.get("market"):
        q = q.filter(Listing.market == p["market"])
    if _csv(p.get("condition")):
        vals = _csv(p["condition"])
        q = q.filter(or_(Listing.condition_override.in_(vals),
                         (Listing.condition_override.is_(None)) & (Listing.condition.in_(vals))))
    if p.get("source"):
        q = q.filter(Listing.source == p["source"])
    if p.get("seller_type"):
        q = q.filter(Listing.seller_type == p["seller_type"])
    if str(p.get("has_phone", "0")) == "1":
        q = q.filter(Listing.seller_phone.isnot(None))
    if p.get("seller_key"):
        sk = p["seller_key"]
        if sk.startswith("phone:"):
            q = q.filter(Listing.seller_phone == sk[6:])
        elif sk.startswith("name:"):
            q = q.filter(func.lower(Listing.seller_name) == sk[5:])
        else:
            q = q.filter(Listing.seller_id == sk)
    if p.get("first_seen_days") not in (None, ""):
        q = q.filter(Listing.first_seen >= datetime.utcnow() - timedelta(days=float(p["first_seen_days"])))
    if str(p.get("only_deals", "0")) == "1":
        q = q.filter(Listing.discount_pct >= p.get("_deal_threshold", 10.0))
    if str(p.get("favorites", "0")) == "1":
        # обране того логина, который смотрит (админ может смотреть чужое — fav_user).
        # Именно join, а не подзапрос: он же даёт сортировку по дате добавления.
        q = q.join(Favorite, Favorite.listing_id == Listing.id).filter(
            Favorite.user == (p.get("_fav_user") or ""))
    if p.get("q"):
        like = u"%%%s%%" % p["q"].strip()
        q = q.filter(or_(Listing.title_pl.ilike(like), Listing.title_uk.ilike(like),
                         Listing.street.ilike(like), Listing.seller_name.ilike(like),
                         Listing.source_id == p["q"].strip()))
    return q


SORTS = {
    "discount": Listing.discount_pct, "price": Listing.price_pln, "price_sqm": Listing.price_per_m2,
    "posted": Listing.posted_at, "first_seen": Listing.first_seen, "area": Listing.area,
    "yield": Listing.yield_pct, "price_drop": Listing.discount_pct, "last_seen": Listing.last_seen,
}


def _fav_user_of(request: Request, p: dict) -> str:
    """Чьё обране показываем. Своё — всегда; чужое (fav_user) — только
    администратору: иначе Юлия читала бы список владельца."""
    want = (p.get("fav_user") or "").strip()
    me = current_user(request)
    if want and want != me and not is_admin(request):
        raise HTTPException(403, u"чуже обране доступне лише адміністратору")
    return want or me


@app.get("/api/listings")
def api_listings(request: Request, db: Session = Depends(get_db)):
    p = dict(request.query_params)
    p["_deal_threshold"] = get_float(db, "deal_threshold_pct", 10.0)
    p["_fav_user"] = _fav_user_of(request, p)
    q = _apply_filters(db.query(Listing), p)
    total = q.count()
    key = p.get("sort") or "first_seen"
    # «за датою додавання» — только когда список и правда обране: без join
    # колонки Favorite в запросе нет
    if key == "fav" and str(p.get("favorites", "0")) != "1":
        key = "first_seen"
    sort = Favorite.at if key == "fav" else SORTS.get(key, Listing.first_seen)
    order = (p.get("order") or ("asc" if p.get("sort") in ("price", "price_sqm") else "desc")).lower()
    q = q.order_by(sort.asc().nullslast() if order == "asc" else sort.desc().nullslast(), Listing.id.desc())
    page = max(1, int(p.get("page") or 1))
    per_page = min(200, max(1, int(p.get("per_page") or 50)))
    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    ph = _price_stats(db, [r.id for r in rows])
    favs = fav_ids(db, current_user(request), [r.id for r in rows])
    return {"total": total, "page": page, "per_page": per_page,
            "fav_user": p["_fav_user"],
            "items": [row_dict(r, ph.get(r.id), is_fav=r.id in favs) for r in rows]}


@app.get("/api/listings/{lid}")
def api_listing(request: Request, lid: int, db: Session = Depends(get_db)):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404, u"оголошення не знайдено")
    return full_dict(db, l, current_user(request))


def _log_action(db: Session, lid: int, action: str, payload: dict, request: Optional[Request] = None):
    db.add(UserAction(listing_id=lid, action=action, payload=json.dumps(payload, ensure_ascii=False),
                      user=current_user(request) if request is not None else None))


@app.post("/api/listings/{lid}/favorite")
def api_favorite(request: Request, lid: int, body: Optional[dict] = None, db: Session = Depends(get_db)):
    """Звезда всегда своя: правим обране ТОГО, кто вошёл, — чужое не трогаем."""
    if db.get(Listing, lid) is None:
        raise HTTPException(404)
    user = current_user(request)
    row = db.query(Favorite).filter_by(user=user, listing_id=lid).one_or_none()
    value = (body or {}).get("value")
    want = (row is None) if value is None else bool(value)
    if want and row is None:
        db.add(Favorite(user=user, listing_id=lid))
    elif not want and row is not None:
        db.delete(row)
    _log_action(db, lid, "favorite", {"value": want}, request)
    db.commit()
    return {"is_favorite": want}


# ---------- візитка ріелтора і PDF-презентації ----------
PROFILE_FIELDS = ("display_name", "phone", "email", "agency", "about", "pres_lang")


def profile_dict(db: Session, user: str) -> Dict:
    row = db.get(UserProfile, user)
    d = {"user": user, "is_admin": user == ADMIN_USER}
    for f in PROFILE_FIELDS:
        d[f] = getattr(row, f) if row else None
    d["display_name"] = d["display_name"] or user
    d["pres_lang"] = d["pres_lang"] or "uk"
    return d


@app.get("/api/profile")
def api_profile(request: Request, db: Session = Depends(get_db)):
    """Своя визитка. Чужую не отдаём никому: это личные контакты."""
    return profile_dict(db, current_user(request))


@app.post("/api/profile")
def api_profile_save(request: Request, body: dict, db: Session = Depends(get_db)):
    user = current_user(request)
    row = db.get(UserProfile, user)
    if row is None:
        row = UserProfile(user=user)
        db.add(row)
    for f in PROFILE_FIELDS:
        if f in (body or {}):
            v = body[f]
            setattr(row, f, (str(v).strip() or None) if v is not None else None)
    if row.pres_lang not in ("uk", "pl"):
        row.pres_lang = "uk"
    row.updated_at = datetime.utcnow()
    db.commit()
    return profile_dict(db, user)


@app.post("/api/presentation")
def api_presentation(request: Request, body: dict, db: Session = Depends(get_db)):
    """PDF-подборка выбранных объявлений с контактами ОТПРАВИТЕЛЯ.

    Синхронно: файл нужен здесь и сейчас, а Chromium верстает его за секунды.
    Ручка объявлена обычным `def`, поэтому FastAPI держит её в рабочем потоке —
    синхронный Playwright внутри цикла событий не работает."""
    ids = [int(x) for x in (body or {}).get("ids") or []]
    if not ids:
        raise HTTPException(400, u"не вибрано жодного оголошення")
    if len(ids) > presentation.MAX_ITEMS:
        raise HTTPException(400, u"забагато оголошень: максимум %d" % presentation.MAX_ITEMS)
    prof = profile_dict(db, current_user(request))
    lang = (body.get("lang") or prof["pres_lang"] or "uk").lower()
    if lang not in ("uk", "pl"):
        raise HTTPException(400, u"мова: uk або pl")
    rows = db.query(Listing).filter(Listing.id.in_(ids)).all()
    if not rows:
        raise HTTPException(404, u"оголошення не знайдені")
    order = {lid: i for i, lid in enumerate(ids)}        # порядок — как выбрал человек
    rows.sort(key=lambda r: order.get(r.id, 10 ** 6))
    # Украинская подборка с польским описанием бесполезна клиенту, а очередь
    # дойдёт до этих объявлений через дни. Переводим отобранное прямо сейчас:
    # их единицы, и это ровно тот момент, когда перевод нужен.
    missed = 0
    if lang == "uk" and (body.get("translate_missing", True)):
        prov = translate.get_provider(get_settings(db))
        for r in rows:
            if prov is None:
                break
            if r.title_uk and (r.description_uk or not r.description_pl):
                continue
            try:
                translate.translate_listing(db, r, prov)
            except Exception as e:  # noqa: BLE001 — без перевода отдадим оригинал
                missed += 1
                log.warning("презентация: перевод %s не вышел: %s", r.id, e)
    if missed:
        log.warning("презентация: %d оголошень пішли мовою оригіналу", missed)
    html_text = presentation.build_html(rows, prof, lang, body.get("title"), body.get("comment"))
    try:
        pdf = presentation.render_pdf(html_text)
    except Exception as e:  # noqa: BLE001 — без Chromium файл не собрать
        log.error("презентация: %s", e)
        raise HTTPException(500, u"не вдалося зібрати PDF: %s. Потрібен Chromium "
                                 u"(playwright install chromium)" % e)
    for lid in ids:
        _log_action(db, lid, "presentation", {"lang": lang, "n": len(rows)}, request)
    db.commit()
    name = u"%s-%s.pdf" % (u"pidbirka" if lang == "uk" else u"oferta",
                           datetime.now().strftime("%Y%m%d-%H%M"))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=%s" % name,
        "Content-Length": str(len(pdf)),
    })


@app.get("/api/favorites/users")
def api_favorite_users(request: Request, db: Session = Depends(get_db)):
    """Сколько у кого в обраному. Владельцу — по всем логинам (он выбирает,
    чей список смотреть), остальным — только свой."""
    counts = fav_counts(db)
    me = current_user(request)
    if not is_admin(request):
        return {"me": me, "users": [{"user": me, "count": counts.get(me, 0)}]}
    names = sorted(set(list(_users()) + list(counts)))
    return {"me": me, "users": [{"user": u, "count": counts.get(u, 0)} for u in names]}


@app.post("/api/listings/{lid}/translate")
def api_translate_one(request: Request, lid: int, db: Session = Depends(get_db)):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404)
    provider = translate.get_provider(get_settings(db))
    if provider is None:
        raise HTTPException(400, u"провайдер перекладу не налаштований (Налаштування)")
    try:
        # перевод прежней версии подсказки кнопка обновляет: иначе устаревшее не освежить
        stale = l.translate_version != translate.PROMPT_VERSION
        res = translate.translate_listing(db, l, provider, force=(not l.description_uk) or stale)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, u"перекладач не відповів: %s" % e)
    _log_action(db, lid, "translate", {"provider": res["provider"]}, request)
    db.commit()
    return res


@app.post("/api/listings/{lid}/manual")
def api_manual(request: Request, lid: int, body: dict, db: Session = Depends(get_db)):
    l = db.get(Listing, lid)
    if l is None:
        raise HTTPException(404)
    if "osiedle" in body:
        v = body["osiedle"]
        if v and not geo.match_osiedle(v):
            raise HTTPException(400, u"невідоме осиедле: %s" % v)
        l.osiedle_override = geo.match_osiedle(v) if v else None
    if "condition" in body:
        v = body["condition"]
        if v and v not in i18n.CONDITION:
            raise HTTPException(400, u"невідомий стан: %s" % v)
        l.condition_override = v or None
    if "note" in body:
        l.note = body["note"] or None
    _log_action(db, lid, "manual", body, request)
    db.commit()
    return full_dict(db, l, current_user(request))


@app.post("/api/listings/{lid}/detach")
def api_detach(request: Request, lid: int, db: Session = Depends(get_db)):
    g = dedup.detach(db, lid)
    if g is None:
        raise HTTPException(404)
    _log_action(db, lid, "detach", {}, request)
    db.commit()
    return {"dedup_group": g}


# ---------- справочники и сводка ----------
# Когда поднялся ЭТОТ процесс. По нему safe_restart.ps1 проверяет, что сервер и
# правда перезапустился: 18.09.2026 он рапортовал «сервер снова отвечает», хотя
# отвечал старый процесс (остановить его без прав администратора не вышло).
STARTED_AT = datetime.utcnow()


@app.get("/api/health")
def api_health():
    return {"ok": True, "db": str(DB_PATH), "version": VERSION,
            "started_at": STARTED_AT, "pid": os.getpid()}


@app.get("/api/geo")
def api_geo(db: Session = Depends(get_db)):
    counts = {}
    for offer_type, osiedle, n in db.execute(
            select(Listing.offer_type, func.coalesce(Listing.osiedle_override, Listing.osiedle), func.count())
            .where(Listing.is_active.is_(True), Listing.is_representative.is_(True))
            .group_by(Listing.offer_type, func.coalesce(Listing.osiedle_override, Listing.osiedle))).all():
        counts[(offer_type, osiedle)] = n
    out = geo.all_geo()
    for d in out:
        for o in d["osiedla"]:
            o["sale_active"] = counts.get(("sale", o["name"]), 0)
            o["rent_active"] = counts.get(("rent", o["name"]), 0)
        d["sale_active"] = sum(o["sale_active"] for o in d["osiedla"])
        d["rent_active"] = sum(o["rent_active"] for o in d["osiedla"])
    return {"districts": out}


def _run_dict(r: Optional[ScrapeRun]) -> Optional[dict]:
    if r is None:
        return None
    return {"id": r.id, "kind": r.kind, "source": r.source, "status": r.status, "phase": r.phase,
            "started_at": r.started_at, "finished_at": r.finished_at, "last_beat": r.last_beat,
            "pages": r.pages, "seen": r.seen, "new": r.new, "updated": r.updated,
            "price_changes": r.price_changes, "removed": r.removed, "details": r.details,
            "errors": r.errors, "message": r.message, "full": r.full}


_cache: Dict[str, tuple] = {}


def _cached(key: str, build, ttl: int = 300):
    """Тяжёлые срезы считаются секунды, а страница зовёт их при каждом
    открытии — держим 5 минут."""
    now = datetime.utcnow()
    hit = _cache.get(key)
    if hit and (now - hit[0]).total_seconds() < ttl:
        return hit[1]
    val = build()
    _cache[key] = (now, val)
    return val


@app.get("/api/summary")
def api_summary(db: Session = Depends(get_db)):
    paused = scraper.paused_until(db)
    sources = [{"source": s, "active": n, "last_seen": ls} for s, n, ls in db.execute(
        select(Listing.source, func.count(), func.max(Listing.last_seen))
        .where(Listing.is_active.is_(True)).group_by(Listing.source)).all()]
    out = _cached("summary", lambda: analytics.market_summary(db), 120)
    return dict(out, **{
        "last_runs": {"sale": _run_dict(scraper.last_run(db, "sale")),
                      "rent": _run_dict(scraper.last_run(db, "rent"))},
        "scrape_running": scraper.is_running(), "current_run_id": scraper.current_run_id(),
        "paused_until": _pause_value(paused), "translate": translate.status(db), "fx": fx.latest(db),
        "sources": sources, "version": VERSION,
    })


@app.get("/api/stats")
def api_stats(offer_type: str = "sale", level: str = "osiedle", rooms: Optional[str] = None,
              market: Optional[str] = None, condition: Optional[str] = None,
              db: Session = Depends(get_db)):
    rooms_l = [int(x) for x in _csv(rooms) if x.isdigit()] or None
    cond_l = _csv(condition) or None
    key = "stats:%s:%s:%s:%s:%s" % (offer_type, level, rooms_l, market, cond_l)
    res = _cached(key, lambda: analytics.stats(db, offer_type, level, rooms_l, market, cond_l))
    coef = {}
    try:
        coef = json.loads(get_settings(db).get("area_coef_%s" % offer_type) or "{}")
    except ValueError:
        pass
    return dict(res, area_coef=coef)


@app.get("/api/price_index")
def api_price_index(period: str = "month", offer_type: str = "sale", db: Session = Depends(get_db)):
    return _cached("index:%s:%s" % (period, offer_type), lambda: analytics.price_index(db, period, offer_type))


@app.get("/api/trends")
def api_trends(weeks: int = 26, offer_type: str = "sale", db: Session = Depends(get_db)):
    return _cached("trends:%d:%s" % (weeks, offer_type), lambda: analytics.trends(db, weeks, offer_type))


@app.get("/api/rent/yield_top")
def api_yield_top(level: str = "osiedle", rooms: Optional[int] = None, min_rent: int = 8,
                  min_sale: int = 8, db: Session = Depends(get_db)):
    return _cached("yield:%s:%s:%d:%d" % (level, rooms, min_rent, min_sale),
                   lambda: rent_analytics.yield_top(db, level, rooms, min_rent, min_sale))


# ---------- контакты ----------
CONTACT_SQL = """
SELECT COALESCE(seller_id, 'phone:' || seller_phone, 'name:' || lower(trim(seller_name))) AS seller_key,
       MAX(seller_name) AS seller_name, MAX(seller_type) AS seller_type, MAX(seller_phone) AS seller_phone,
       MAX(source) AS source,
       SUM(CASE WHEN offer_type = 'sale' THEN 1 ELSE 0 END) AS listings_sale,
       SUM(CASE WHEN offer_type = 'rent' THEN 1 ELSE 0 END) AS listings_rent,
       COUNT(*) AS active_total, MIN(first_seen) AS first_seen, MAX(last_seen) AS last_seen,
       GROUP_CONCAT(DISTINCT COALESCE(osiedle_override, osiedle)) AS osiedla,
       GROUP_CONCAT(id) AS ids
FROM listings
WHERE is_active = 1 AND (seller_id IS NOT NULL OR seller_phone IS NOT NULL OR seller_name IS NOT NULL)
  {where}
GROUP BY seller_key
"""


def _contacts(db: Session, p: dict) -> List[dict]:
    where = []
    params = {}
    if p.get("offer_type") in ("sale", "rent"):
        where.append("AND offer_type = :ot")
        params["ot"] = p["offer_type"]
    if p.get("seller_type"):
        where.append("AND seller_type = :st")
        params["st"] = p["seller_type"]
    if p.get("q"):
        where.append("AND (lower(seller_name) LIKE :q OR seller_phone LIKE :q)")
        params["q"] = u"%%%s%%" % p["q"].strip().lower()
    sql = CONTACT_SQL.format(where=" ".join(where))
    rows = db.execute(text(sql), params).mappings().all()
    out = []
    for r in rows:
        ids = [int(x) for x in (r["ids"] or "").split(",") if x][:5]
        out.append({"seller_key": r["seller_key"], "seller_name": r["seller_name"],
                    "seller_type": r["seller_type"], "seller_type_uk": i18n.uk("seller_type", r["seller_type"]),
                    "seller_phone": r["seller_phone"], "source": r["source"],
                    "listings_sale": r["listings_sale"], "listings_rent": r["listings_rent"],
                    "active_total": r["active_total"], "first_seen": r["first_seen"], "last_seen": r["last_seen"],
                    "osiedla": [x for x in (r["osiedla"] or "").split(",") if x][:6], "sample_ids": ids})
    sort = p.get("sort") or "active_total"
    if sort not in ("active_total", "last_seen", "listings_rent", "listings_sale", "first_seen"):
        sort = "active_total"
    out.sort(key=lambda x: (x[sort] is None, x[sort]), reverse=(p.get("order") or "desc") == "desc")
    return out


@app.get("/api/contacts")
def api_contacts(request: Request, db: Session = Depends(get_db)):
    p = dict(request.query_params)
    rows = _contacts(db, p)
    page = max(1, int(p.get("page") or 1))
    per_page = min(500, max(1, int(p.get("per_page") or 50)))
    return {"total": len(rows), "page": page, "per_page": per_page,
            "items": rows[(page - 1) * per_page: page * per_page]}


def _table_response(rows: List[dict], columns: List[str], fmt: str, name: str):
    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError:
            raise HTTPException(500, u"openpyxl не встановлено: pip install openpyxl")
        wb = Workbook()
        ws = wb.active
        ws.append(columns)
        for r in rows:
            ws.append([_cell(r.get(c)) for c in columns])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": "attachment; filename=%s.xlsx" % name})
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(columns)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in columns])
    data = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=%s.csv" % name})


def _cell(v):
    if isinstance(v, (list, tuple)):
        return u", ".join(str(x) for x in v)
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, bool):
        return u"так" if v else u"ні"
    return v


@app.get("/api/contacts/export")
def api_contacts_export(request: Request, format: str = "csv", db: Session = Depends(get_db)):
    rows = _contacts(db, dict(request.query_params))
    cols = ["seller_name", "seller_type_uk", "seller_phone", "source", "listings_sale", "listings_rent",
            "active_total", "osiedla", "first_seen", "last_seen", "seller_key"]
    return _table_response(rows, cols, format, "contacts")


@app.get("/api/export")
def api_export(request: Request, format: str = "csv", db: Session = Depends(get_db)):
    p = dict(request.query_params)
    p["_deal_threshold"] = get_float(db, "deal_threshold_pct", 10.0)
    p["_fav_user"] = _fav_user_of(request, p)
    q = _apply_filters(db.query(Listing), p).order_by(Listing.first_seen.desc()).limit(5000)
    rows = q.all()
    ph = _price_stats(db, [r.id for r in rows])
    favs = fav_ids(db, current_user(request), [r.id for r in rows])
    dicts = [row_dict(r, ph.get(r.id), is_fav=r.id in favs) for r in rows]
    cols = ["id", "source", "url", "title_uk", "title_pl", "price_pln", "price_usd", "price_per_m2", "czynsz_pln",
            "area", "rooms", "floor", "floors_total", "build_year", "market_uk", "building_type_uk",
            "condition_uk", "district", "osiedle", "street", "seller_type_uk", "seller_name", "seller_phone",
            "discount_pct", "baseline_sqm", "baseline_count", "yield_pct", "rent_median_pln",
            "posted_at", "first_seen", "days_on_market", "price_changes", "price_drop_pct"]
    return _table_response(dicts, cols, format, "listings")


# ---------- прогоны ----------
@app.get("/api/runs")
def api_runs(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(ScrapeRun).order_by(ScrapeRun.started_at.desc()).limit(limit).all()
    return [_run_dict(r) for r in rows]


def _bg(target, *args):
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def _scrape_bg(kind: str, sources: str):
    try:
        scraper.run_scrape(kind, sources)
    except Exception as e:  # noqa: BLE001
        log.error("прогон %s упал: %s", kind, e)
    _cache.clear()


def _start_scrape(db: Session, kind: str, sources: str = "all") -> dict:
    if scraper.is_running():
        raise HTTPException(409, u"прогін уже йде")
    if scraper.paused_until(db):
        raise HTTPException(409, u"скрапінг на паузі")
    _bg(_scrape_bg, kind, sources)
    return {"started": True, "kind": kind, "sources": sources}


@app.post("/api/scrape", dependencies=[Depends(require_admin)])
def api_scrape(kind: str = "sale", source: str = "all", db: Session = Depends(get_db)):
    if kind not in ("sale", "rent", "all"):
        raise HTTPException(400, u"kind: sale | rent | all")
    if kind == "all":
        if scraper.is_running() or scraper.paused_until(db):
            raise HTTPException(409, u"прогін уже йде або пауза")

        def both():
            _scrape_bg("sale", source)
            _scrape_bg("rent", source)
        _bg(both)
        return {"started": True, "kind": "all"}
    return _start_scrape(db, kind, source)


@app.post("/api/scrape/stop", dependencies=[Depends(require_admin)])
def api_scrape_stop():
    scraper.request_stop()
    return {"stopping": True}


def _pause_value(dt):
    """Бессрочная пауза хранится как 9999 год; наружу — «forever», чтобы
    интерфейс писал «до скасування», а не дату из десятого тысячелетия."""
    if dt is None:
        return None
    return "forever" if dt.year >= 9999 else dt


@app.post("/api/scrape/pause", dependencies=[Depends(require_admin)])
def api_scrape_pause(body: dict, db: Session = Depends(get_db)):
    until = scraper.set_pause(db, float(body.get("hours") or 0))
    return {"paused_until": _pause_value(until)}


@app.post("/api/scrape/resume", dependencies=[Depends(require_admin)])
def api_scrape_resume(db: Session = Depends(get_db)):
    scraper.resume(db)
    return {"paused_until": None}


def _recompute_bg():
    db = SessionLocal()
    try:
        log.info("пересчёт: %s", scraper.post_process(db, None))
    finally:
        db.close()
        _cache.clear()


@app.post("/api/recompute", dependencies=[Depends(require_admin)])
def api_recompute():
    _bg(_recompute_bg)
    return {"started": True}


# ---------- перевод ----------
@app.get("/api/translate/status")
def api_translate_status(db: Session = Depends(get_db)):
    return translate.status(db)


def _translate_bg(limit: Optional[int]):
    db = SessionLocal()
    try:
        log.info("перевод очереди: %s", translate.translate_pending(db, limit, manual=True))
    finally:
        db.close()


@app.post("/api/translate/run", dependencies=[Depends(require_admin)])
def api_translate_run(body: Optional[dict] = None, db: Session = Depends(get_db)):
    if translate.get_provider(get_settings(db)) is None:
        raise HTTPException(400, u"провайдер перекладу не налаштований")
    _bg(_translate_bg, (body or {}).get("limit"))
    return {"started": True}


@app.get("/api/translate/unknown_values")
def api_unknown_values(db: Session = Depends(get_db)):
    rows = db.query(UnknownValue).order_by(UnknownValue.count.desc()).limit(300).all()
    return [{"field": r.field, "value_pl": r.value_pl, "count": r.count, "last_seen": r.last_seen} for r in rows]


# ---------- настройки ----------
@app.get("/api/settings", dependencies=[Depends(require_admin)])
def api_settings(db: Session = Depends(get_db)):
    vals = get_settings(db)
    out = {}
    for k, v in vals.items():
        if k.startswith("resume:"):
            continue
        out[k] = (SECRET_MASK if v else "") if k in SECRET_KEYS else v
    return out


@app.post("/api/settings", dependencies=[Depends(require_admin)])
def api_settings_save(body: dict, db: Session = Depends(get_db)):
    saved = []
    for k, v in (body or {}).items():
        if k not in SAFE_KEYS:
            continue
        if k in SECRET_KEYS and v == SECRET_MASK:
            continue        # поле не трогали
        set_setting(db, k, "" if v is None else str(v))
        saved.append(k)
    _cache.clear()
    return {"saved": saved}


# ---------- журнал действий ----------
ACTION_UK = {"view_card": u"відкрив(ла) картку", "search": u"шукав(ла) в каталозі",
             "favorite": u"обране", "note": u"нотатка", "manual": u"ручна правка",
             "detach": u"«інша квартира»", "translate": u"переклад картки",
             "export": u"експорт", "contacts": u"контакти", "presentation": u"презентація PDF",
             "other": u"дія"}


@app.get("/api/activity", dependencies=[Depends(require_admin)])
def api_activity(user: Optional[str] = None, days: int = 14, limit: int = 300,
                 action: Optional[str] = None, db: Session = Depends(get_db)):
    """Кто что смотрел и делал — для владельца. Строки поиска расшифровываются
    из query, карточки — заголовком объявления."""
    q = db.query(AccessLog).filter(AccessLog.at >= datetime.utcnow() - timedelta(days=days))
    if user:
        q = q.filter(AccessLog.user == user)
    if action:
        q = q.filter(AccessLog.action == action)
    rows = q.order_by(AccessLog.at.desc()).limit(min(limit, 2000)).all()
    ids = {r.listing_id for r in rows if r.listing_id}
    titles = {}
    if ids:
        for lid, t_uk, t_pl, os_ in db.execute(select(Listing.id, Listing.title_uk, Listing.title_pl,
                                                       Listing.osiedle).where(Listing.id.in_(ids))).all():
            titles[lid] = {"title": t_uk or t_pl, "osiedle": os_}
    per_user = {}
    for u, n in db.execute(select(AccessLog.user, func.count()).where(
            AccessLog.at >= datetime.utcnow() - timedelta(days=days)).group_by(AccessLog.user)).all():
        per_user[u] = n
    return {"rows": [{"at": r.at, "user": r.user, "action": r.action, "action_uk": ACTION_UK.get(r.action, r.action),
                      "path": r.path, "query": r.query, "listing_id": r.listing_id,
                      "listing": titles.get(r.listing_id)} for r in rows],
            "per_user": per_user, "days": days}


# ---------- планировщик (только для разработки; в бою — Планировщик Windows) ----------
scheduler = BackgroundScheduler(timezone=KYIV)
# Сторож живёт отдельно от планировщика прогонов и включён ВСЕГДА — см. startup
watchdog_scheduler = BackgroundScheduler(timezone=KYIV)


def _sched_scrape(kind: str):
    delay = random.randint(*SCAN_JITTER_SEC)
    log.info("плановый прогон %s через %d с", kind, delay)
    threading.Timer(delay, lambda: _scrape_bg(kind, "all")).start()


def _watchdog():
    db = SessionLocal()
    try:
        n = scraper.close_stale_runs(db)
        if n:
            log.warning("сторож закрыл %d зависших прогонов", n)
    finally:
        db.close()


@app.get("/api/jobs")
def api_jobs():
    # Сторож показываем вместе с остальными: на боевом ПК планировщик
    # выключен (прогоны запускает Планировщик Windows), и раздел выглядел так,
    # будто не работает ничего — включая сторожа, из-за отсутствия которого прогон
    # висел в статусе running трое суток.
    jobs = list(scheduler.get_jobs()) if scheduler.running else []
    if watchdog_scheduler.running:
        jobs += list(watchdog_scheduler.get_jobs())
    return {"scheduler_running": scheduler.running,
            "watchdog_running": watchdog_scheduler.running,
            "disabled_by_env": os.environ.get("DISABLE_SCHEDULER") == "1",
            "jobs": [{"id": j.id, "next_run": j.next_run_time} for j in jobs]}


def migrate_favorites(db: Session) -> int:
    """Единственный общий список обраного (listings.is_favorite) — в личный
    список администратора. Один раз: пока таблица пуста. Сама колонка остаётся,
    но больше не читается, иначе после выкатки старые звёзды просто исчезли бы."""
    if db.execute(select(func.count()).select_from(Favorite)).scalar():
        return 0
    ids = [r[0] for r in db.execute(select(Listing.id).where(Listing.is_favorite.is_(True))).all()]
    for lid in ids:
        db.add(Favorite(user=ADMIN_USER, listing_id=lid))
    if ids:
        db.commit()
        log.info("обране: %d записей перенесено в личный список %s", len(ids), ADMIN_USER)
    return len(ids)


@app.on_event("startup")
def _startup():
    ensure_columns()
    db = SessionLocal()
    try:
        scraper.close_stale_runs(db, orphans=True)
        migrate_favorites(db)
    finally:
        db.close()
    # Сторож живёт ВСЕГДА: он не скрапит, а закрывает зависшие строки. Раньше он
    # выключался вместе с планировщиком (DISABLE_SCHEDULER=1 — это бой), и прогон,
    # оборванный перезапуском 20.09.2026, висел «running» трое суток.
    # replace_existing: планировщик теперь модульный (его видит /api/jobs), а
    # startup в тестах вызывается не один раз
    watchdog_scheduler.add_job(_watchdog, "interval", minutes=10, id="watchdog",
                               replace_existing=True)
    if not watchdog_scheduler.running:
        watchdog_scheduler.start()
    if os.environ.get("DISABLE_SCHEDULER") != "1":
        for h in SCAN_HOURS_SALE:
            scheduler.add_job(lambda: _sched_scrape("sale"), CronTrigger(hour=h, minute=0), id="sale_%d" % h)
        scheduler.add_job(lambda: _sched_scrape("rent"), CronTrigger(hour=SCAN_HOUR_RENT, minute=SCAN_MINUTE_RENT), id="rent")
        scheduler.add_job(lambda: _bg(_translate_bg, None), "interval", hours=1, id="translate")
        scheduler.start()
        log.info("внутренний планировщик включён: %d заданий", len(scheduler.get_jobs()))
    else:
        log.info("внутренний планировщик выключен (DISABLE_SCHEDULER=1) — расписанием управляет Планировщик Windows")


@app.on_event("shutdown")
def _shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def _no_frontend():
        return JSONResponse({"detail": u"фронтенд не зібраний: cd frontend && npm run build"}, status_code=200)
