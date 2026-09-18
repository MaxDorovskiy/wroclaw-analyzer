# -*- coding: utf-8 -*-
"""Конфигурация: пути, константы источников, настройки по умолчанию.

Всё, что владелец может захотеть подкрутить без правки кода, лежит в
DEFAULT_SETTINGS и правится в «Налаштуваннях». Всё остальное — константы с
объяснением, почему именно такие.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent      # wroclaw-analyzer/
# WRO_DATA — куда класть базу и логи: на ПК владельца это отдельный большой
# диск, а не папка проекта рядом с кодом
DATA_DIR = Path(os.environ.get("WRO_DATA") or (BASE_DIR / "data"))
# WRO_DB позволяет поднять сервер на копии базы (правки проверяются на копии,
# а не на боевой — правило из киевской системы, оплаченное потерянными прогонами).
DB_PATH = Path(os.environ.get("WRO_DB") or (DATA_DIR / "wro.db"))
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"
PROBE_DIR = DATA_DIR / "probe"          # сырые ответы источников для разбора
DATA_DIR.mkdir(parents=True, exist_ok=True)

VERSION = "1.0"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

CITY = u"Wrocław"

# ---------- Otodom ----------
# Выдача Otodom — Next.js, объявления лежат в <script id="__NEXT_DATA__">.
# limit=72 — максимум, который принимает выдача; меньше страниц = меньше
# запросов при том же темпе.
OTODOM_SEARCH = {
    "sale": "https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/dolnoslaskie/wroclaw/wroclaw/wroclaw",
    "rent": "https://www.otodom.pl/pl/wyniki/wynajem/mieszkanie/dolnoslaskie/wroclaw/wroclaw/wroclaw",
}
OTODOM_PAGE_SIZE = 72
# slug на выдаче уже оканчивается на «-ID<код>» (код в URL буквенно-цифровой и
# НЕ равен числовому id из JSON) — поэтому адрес карточки строится из slug
OTODOM_AD_URL = "https://www.otodom.pl/pl/oferta/{slug}"

# ---------- OLX ----------
# Публичный JSON API, которым ходит сам сайт. Id категорий и города со
# временем МЕНЯЮТСЯ (об этом пишут все авторы парсеров) — поэтому они в
# настройках, а перед прогоном адаптер пробует получить их по «дружественной»
# ссылке (friendly-links) и лишь при неудаче берёт настройку.
OLX_API = "https://www.olx.pl/api/v1/offers/"
OLX_FRIENDLY = "https://www.olx.pl/api/v1/friendly-links/query-params/"
OLX_PATHS = {
    "sale": "nieruchomosci/mieszkania/sprzedaz/wroclaw/",
    "rent": "nieruchomosci/mieszkania/wynajem/wroclaw/",
}
OLX_PAGE_SIZE = 40      # больше API не отдаёт
OLX_MAX_OFFSET = 1000   # дальше API отвечает ошибкой — выдачу дробим по цене

# ---------- темп и жизнь ----------
# ≤15 запросов в минуту — тот же потолок, что уберёг киевскую систему от
# Cloudflare Error 1015 (1.29 млн строк лога без единого бана).
REQUESTS_PER_MINUTE = 14
REQUEST_TIMEOUT = 40
INACTIVE_AFTER_DAYS = 3        # не видели N дней при полном обходе -> снято
WATCHDOG_MINUTES = 180         # прогон без отметки жизни -> failed
BEAT_EVERY_SEC = 30

# Санитарные пороги: ниже/выше — гаражи, доли, опечатки, «cena za m²»
# вместо цены. Числа — из оферт сентября 2026 (медиана ~13.5 тыс. zł/м²).
SANE_SQM_SALE = (4000, 40000)
SANE_SQM_RENT = (20, 250)      # zł/м²/мес
MIN_AREA = 12.0
MAX_AREA = 400.0

# ---------- расписание (Киев) ----------
# Окна не пересекаются с киевской системой (8/14/20 +30-50 мин и хвост до
# часа; аренда 13:05-13:25): с одного домашнего IP два обхода — тот же
# всплеск, что и один быстрый.
SCAN_HOURS_SALE = (11, 17)
SCAN_HOUR_RENT = 2
SCAN_MINUTE_RENT = 30
SCAN_JITTER_SEC = (0, 20 * 60)

# ---------- настройки по умолчанию ----------
DEFAULT_SETTINGS = {
    # перевод
    "translate_provider": "ollama",          # ollama | anthropic | google | deepl | none
    "translate_ollama_url": "http://127.0.0.1:11434",
    "translate_ollama_model": "gemma3:12b",
    "translate_anthropic_model": "claude-opus-5",
    "translate_anthropic_key": "",
    "translate_google_key": "",
    "translate_deepl_key": "",
    "translate_daily_cap": "800",            # описаний в сутки
    "translate_enabled": "1",
    # аналитика
    "deal_threshold_pct": "10",              # порог «вигідне»
    "renovation_cost_sqm_pln": "2000",       # отделка «stan deweloperski», zł/м²
    # источники
    "olx_category_sale": "14",
    "olx_category_rent": "15",
    "olx_city_id": "19701",
    "fetch_mode": "httpx",                   # httpx | browser
    "requests_per_minute": str(REQUESTS_PER_MINUTE),
    "sources_enabled": "otodom,olx",
    "details_per_run": "600",                # карточек Otodom за один хвост (~40 мин при 15/мин)
    # скрап
    "scrape_paused_until": "",               # ISO UTC; пусто — не на паузе
    "scrape_stop_requested": "0",
    # прочее
    "public_url": "http://127.0.0.1:8020",
    "telegram_token": "",
    "telegram_chat_id": "",
}

# Ключи, которые можно менять через API. Новая настройка НЕ сохранится,
# пока её ключ не внесён сюда — поле в интерфейсе будет молча ничего не
# делать (грабли из Киева).
SAFE_KEYS = {
    "translate_provider", "translate_ollama_url", "translate_ollama_model",
    "translate_anthropic_model", "translate_anthropic_key", "translate_google_key",
    "translate_deepl_key", "translate_daily_cap", "translate_enabled",
    "deal_threshold_pct", "renovation_cost_sqm_pln",
    "olx_category_sale", "olx_category_rent", "olx_city_id", "fetch_mode",
    "requests_per_minute", "sources_enabled", "details_per_run", "public_url",
    "telegram_token", "telegram_chat_id",
}
# Наружу не отдаются даже за паролем — вместо них маска.
SECRET_KEYS = {"translate_anthropic_key", "translate_google_key",
               "translate_deepl_key", "telegram_token"}
SECRET_MASK = u"••••••••"
