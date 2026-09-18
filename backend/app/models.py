# -*- coding: utf-8 -*-
"""Схема базы. Продажа и аренда — в одной таблице `listings` (offer_type).

У них одинаковые поля, одинаковые источники и одинаковая обработка, а
доходность считается соединением одного с другим; в Киеве аренда была
отдельной таблицей только потому, что у неё был другой источник.
"""
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Float, Index, Integer,
                        String, Text)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False, index=True)       # otodom | olx
    source_id = Column(String, nullable=False, index=True)    # id в источнике (строкой)
    url = Column(String)
    offer_type = Column(String, nullable=False, index=True)   # sale | rent
    # OLX-зеркало Otodom ссылается на оригинал — точный ключ склейки дублей
    external_url = Column(String, index=True)
    raw_json = Column(Text)                                   # сырой ответ источника

    # --- текст: оригинал и перевод ---
    title_pl = Column(String)
    description_pl = Column(Text)
    title_uk = Column(String)
    description_uk = Column(Text)
    translated_at = Column(DateTime)
    translate_provider = Column(String)
    translate_version = Column(String)      # версия подсказки/провайдера

    # --- цена ---
    price_pln = Column(Float, index=True)
    price_per_m2 = Column(Float, index=True)
    czynsz_pln = Column(Float)               # czynsz administracyjny / «dodatkowo»
    price_usd = Column(Float)
    price_eur = Column(Float)
    hide_price = Column(Boolean, default=False)

    # --- квартира ---
    area = Column(Float, index=True)
    rooms = Column(Integer, index=True)
    floor = Column(Integer)                  # 0 = parter (польская нумерация!)
    floors_total = Column(Integer)
    build_year = Column(Integer, index=True)
    market = Column(String, index=True)      # primary | secondary
    building_type = Column(String, index=True)
    building_material = Column(String)
    construction_status = Column(String)     # ready_to_use | to_completion | to_renovation
    condition = Column(String, index=True)   # developer_bare | to_renovate | to_refresh | renovated | unknown
    condition_src = Column(String)           # auto | status | text | manual
    condition_override = Column(String)      # ручная правка — сильнее автомата, скрапом не перетирается
    ownership = Column(String)
    heating = Column(String)
    windows = Column(String)
    elevator = Column(Boolean)
    furnished = Column(Boolean)
    extras_json = Column(Text)               # JSON-массив дополнений (balkon, garaż, ...)
    media_json = Column(Text)
    security_json = Column(Text)
    characteristics_json = Column(Text)      # JSON: key -> {label, value, localized}

    # --- место ---
    district = Column(String, index=True)    # 5 дзельниц
    osiedle = Column(String, index=True)     # 48 осиедле
    osiedle_override = Column(String)
    street = Column(String)
    lat = Column(Float)
    lon = Column(Float)
    address_raw = Column(String)
    location_raw = Column(String)            # все имена мест от источника, через « | »

    # --- продавец ---
    seller_type = Column(String, index=True) # private | agency | developer
    seller_name = Column(String)
    seller_id = Column(String, index=True)     # id агентства/пользователя на площадке
    seller_phone = Column(String, index=True)  # с карточки Otodom (owner.phones); OLX без входа не отдаёт
    no_commission = Column(Boolean)

    # --- жизнь объявления ---
    posted_at = Column(DateTime)             # дата подачи по данным площадки
    refreshed_at = Column(DateTime)          # последнее «поднятие» на площадке
    first_seen = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen = Column(DateTime, default=datetime.utcnow, index=True)
    is_active = Column(Boolean, default=True, index=True)
    removed_at = Column(DateTime)
    images_json = Column(Text)
    first_image = Column(String)              # для склейки дублей: у зеркал та же первая картинка
    image_count = Column(Integer, default=0)
    details_fetched = Column(Boolean, default=False, index=True)  # хвост Otodom пройден

    # --- дубли ---
    dedup_group = Column(String, index=True)
    group_size = Column(Integer, default=1)
    is_representative = Column(Boolean, default=True, index=True)
    dedup_detached = Column(Boolean, default=False)   # «інша квартира» — из группы вынесено вручную

    # --- выгодность ---
    discount_pct = Column(Float, index=True)
    baseline_sqm = Column(Float)
    baseline_level = Column(String)
    baseline_key = Column(String)
    baseline_count = Column(Integer)
    deal_thin_base = Column(Boolean)
    price_sqm_adj = Column(Float)            # цена за м² после поправки на площадь
    deal_updated_at = Column(DateTime)

    # --- доходность ---
    rent_median_pln = Column(Float)
    rent_baseline_level = Column(String)
    rent_baseline_count = Column(Integer)
    yield_pct = Column(Float, index=True)
    yield_investment_pln = Column(Float)
    yield_reno_cost_pln = Column(Float)

    # --- владелец ---
    is_favorite = Column(Boolean, default=False, index=True)
    note = Column(Text)

    __table_args__ = (
        Index("ix_listings_source_sid", "source", "source_id", unique=True),
        Index("ix_listings_type_active", "offer_type", "is_active"),
        Index("ix_listings_osiedle_rooms", "osiedle", "rooms"),
    )


# Колонки, которых хватает для аналитики: перебирать ORM-объекты с
# description_pl/raw_json на десятках тысяч строк — это гигабайты и минуты.
SCORE_COLUMNS = (
    "id", "offer_type", "source", "price_pln", "price_per_m2", "area", "rooms",
    "floor", "floors_total", "build_year", "market", "condition",
    "condition_override", "district", "osiedle", "osiedle_override",
    "is_active", "is_representative", "first_seen", "last_seen", "posted_at",
    "seller_type", "czynsz_pln", "seller_id", "seller_name", "seller_phone",
)


class PriceHistory(Base):
    """Пишется ТОЛЬКО при смене цены: цена на дату — переносом последней."""
    __tablename__ = "price_history"
    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, index=True, nullable=False)
    price_pln = Column(Float)
    seen_at = Column(DateTime, default=datetime.utcnow, index=True)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id = Column(Integer, primary_key=True)
    kind = Column(String, default="sale", index=True)     # sale | rent
    source = Column(String, default="all")                # otodom | olx | all
    status = Column(String, default="running", index=True)  # running | done | failed | stopped
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)
    last_beat = Column(DateTime, default=datetime.utcnow)
    phase = Column(String)                                # list:otodom | details:otodom | list:olx | post
    last_page = Column(Integer, default=0)                # для возобновления
    pages = Column(Integer, default=0)
    seen = Column(Integer, default=0)
    new = Column(Integer, default=0)
    updated = Column(Integer, default=0)
    price_changes = Column(Integer, default=0)
    removed = Column(Integer, default=0)
    details = Column(Integer, default=0)
    errors = Column(Integer, default=0)
    message = Column(Text)
    full = Column(Boolean, default=True)   # обход дошёл до конца у всех источников


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text)


class Translation(Base):
    """Кэш переводов: один и тот же текст (зеркала, повторные подачи)
    переводится один раз."""
    __tablename__ = "translations"
    id = Column(Integer, primary_key=True)
    src_hash = Column(String, index=True, nullable=False)   # sha1(norm(text))
    dst_lang = Column(String, default="uk")
    provider = Column(String)
    model = Column(String)
    prompt_version = Column(String)
    src_len = Column(Integer)
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_tr_hash_lang", "src_hash", "dst_lang"),)


class FxRate(Base):
    __tablename__ = "fx_rates"
    id = Column(Integer, primary_key=True)
    date = Column(String, index=True)        # YYYY-MM-DD по НБП
    code = Column(String, index=True)        # USD | EUR
    mid = Column(Float)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class UserAction(Base):
    """Журнал ручных правок владельца: что, когда и на каком объявлении."""
    __tablename__ = "user_actions"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    listing_id = Column(Integer, index=True)
    action = Column(String)                  # favorite | manual | detach | translate
    payload = Column(Text)
    user = Column(String, index=True)        # кто правил (логин)


class UnknownValue(Base):
    """Значения структурных полей, которых нет в словаре i18n — для пополнения."""
    __tablename__ = "unknown_values"
    id = Column(Integer, primary_key=True)
    field = Column(String, index=True)
    value_pl = Column(String)
    count = Column(Integer, default=1)
    last_seen = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (Index("ix_unknown_field_value", "field", "value_pl", unique=True),)


class AccessLog(Base):
    """Кто что смотрел и делал. Нужен владельцу, чтобы видеть работу Юлии
    (риелтор по аренде с отдельным логином): какие карточки открывала, что
    искала, что отмечала. Сводки и опросы состояния (summary, runs, status)
    сюда не пишутся — это шум страницы, а не действия человека."""
    __tablename__ = "access_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=datetime.utcnow, index=True)
    user = Column(String, index=True)
    action = Column(String, index=True)      # view_card | search | favorite | note | manual | detach | translate | export | contacts | other
    method = Column(String)
    path = Column(String)
    query = Column(Text)
    listing_id = Column(Integer, index=True)
