# -*- coding: utf-8 -*-
"""Общий интерфейс адаптера и «сырое» объявление.

Адаптер знает ТОЛЬКО про свою площадку: как листать выдачу, как достать
карточку и как переложить ответ в RawListing. Всё, что общее (комнаты из
«two»/«2 pokoje», класс состояния по словам, осиедле по справочнику), — в
normalize.py, чтобы правило правилось в одном месте для всех источников.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Tuple


@dataclass
class RawListing:
    source: str
    source_id: str
    url: str
    offer_type: str                      # sale | rent
    title: str = ""
    description: Optional[str] = None    # None = ещё не качали (хвост)
    price: Optional[float] = None
    currency: str = "PLN"
    price_per_m2: Optional[float] = None
    czynsz: Optional[float] = None
    hide_price: bool = False
    area: Optional[float] = None
    rooms_raw: Optional[str] = None
    floor_raw: Optional[str] = None
    floors_total_raw: Optional[str] = None
    build_year_raw: Optional[str] = None
    market_raw: Optional[str] = None
    building_type_raw: Optional[str] = None
    building_material_raw: Optional[str] = None
    construction_status_raw: Optional[str] = None
    ownership_raw: Optional[str] = None
    heating_raw: Optional[str] = None
    windows_raw: Optional[str] = None
    elevator_raw: Optional[str] = None
    furnished_raw: Optional[str] = None
    extras: List[str] = field(default_factory=list)
    media: List[str] = field(default_factory=list)
    security: List[str] = field(default_factory=list)
    location_names: List[str] = field(default_factory=list)  # все имена мест, как их дал источник
    street: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    address_raw: Optional[str] = None
    seller_type_raw: Optional[str] = None    # private | agency | developer | business:true/false
    seller_name: Optional[str] = None
    seller_id: Optional[str] = None
    seller_phone: Optional[str] = None
    no_commission: Optional[bool] = None
    images: List[str] = field(default_factory=list)
    image_count: Optional[int] = None
    posted_at: Optional[datetime] = None
    refreshed_at: Optional[datetime] = None
    external_url: Optional[str] = None
    # key -> {"label": подпись PL, "value": ключ, "localized": значение PL}
    characteristics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    raw: Optional[dict] = None
    needs_details: bool = False


Page = Tuple[int, int, List[RawListing]]   # (номер страницы, всего страниц, объявления)


class Source:
    name = ""
    needs_details = False

    def __init__(self):
        # что адаптер сознательно не взял (причина -> сколько): попадает в сообщение
        # прогона, чтобы «пропущено» было видно владельцу, а не тонуло молча
        self.skipped: Dict[str, int] = {}

    def iter_pages(self, offer_type: str, fetcher, start_page: int = 1,
                   settings: Optional[Dict[str, str]] = None) -> Iterator[Page]:
        raise NotImplementedError

    def fetch_details(self, raw: RawListing, fetcher) -> RawListing:
        return raw


def parse_dt(v) -> Optional[datetime]:
    """«2025-09-10T12:34:56+02:00», «2025-09-10 12:34:56», «2025-09-10» -> наивный UTC."""
    if not v:
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    dt = datetime.strptime(s[:10], "%Y-%m-%d")
                except ValueError:
                    return None
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
