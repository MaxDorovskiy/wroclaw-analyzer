# Контракт API (v1)

Все ручки под basic-auth. Логины: `WRO_WEB_USER`/`WRO_WEB_PASS` (администратор,
по умолчанию `admin`) плюс `WRO_WEB_USERS="yulia:пароль;..."` (просмотр). Пусто =
открыто, с предупреждением в логе. Пометка **[admin]** — только администратору,
остальным 403. Все даты — ISO с явным смещением
(`2026-09-18T10:02:00+03:00`, Киев). Деньги — целые злотые, если не сказано иное.

## Объекты

**ListingRow** (строка каталога):

```json
{
  "id": 123, "source": "otodom", "source_id": "65432101", "url": "https://...",
  "offer_type": "sale",
  "title_pl": "Mieszkanie 3 pok. Krzyki, po remoncie", "title_uk": "Квартира 3 кімн. Кшики, після ремонту",
  "price_pln": 780000, "price_usd": 195000, "price_per_m2": 13000, "czynsz_pln": 650,
  "area": 60.0, "rooms": 3, "floor": 2, "floors_total": 4, "build_year": 2008,
  "market": "secondary", "building_type": "block", "building_type_uk": "блочний будинок",
  "condition": "renovated", "condition_uk": "після ремонту", "condition_src": "auto",
  "district": "Krzyki", "district_uk": "Кшики", "osiedle": "Gaj", "osiedle_uk": "Ґай",
  "street": "ul. Świeradowska", "lat": 51.08, "lon": 17.03,
  "seller_type": "agency", "seller_name": "Nieruchomości XYZ", "no_commission": false,
  "images": ["https://..."], "image_count": 14,
  "posted_at": "2026-09-10T00:00:00+03:00", "first_seen": "...", "last_seen": "...",
  "is_active": true, "days_on_market": 8,
  "dedup_group": "g:otodom:65432101", "group_size": 2,
  "discount_pct": 11.4, "baseline_sqm": 14670, "baseline_level": "osiedle_rooms",
  "baseline_count": 17, "deal_thin_base": false,
  "yield_pct": 5.9, "rent_median_pln": 3850, "rent_baseline_level": "osiedle_rooms", "rent_baseline_count": 12,
  "price_changes": 1, "price_drop_pct": -4.9,
  "is_favorite": false, "translated": true
}
```

**ListingFull** = ListingRow + `description_pl`, `description_uk`,
`characteristics: [{key, label_pl, label_uk, value_pl, value_uk}]`,
`price_history: [{price_pln, seen_at}]`,
`dupes: [{id, source, url, price_pln, seller_type, first_seen, is_active}]`,
`deal_explain: {level, key, pool_size, median_sqm, area_coef, price_sqm_adj, steps: [{level, key, n, ok}]}`,
`rent_explain: {level, count, median_sqm, expected_rent, investment_pln, renovation_cost_pln}`,
`note`, `raw_available: true`.

## Ручки

| Метод и путь | Параметры | Ответ |
|---|---|---|
| `GET /api/health` | — | `{ok: true, db: "...", version: "1.0"}` (без входа) |
| `GET /api/me` | — | `{user, role: "admin"\|"viewer", users: [..]\|null}` |
| `GET /api/activity` **[admin]** | `user`, `days` (14), `limit` (300), `action` | `{rows: [{at, user, action, action_uk, path, query, listing_id, listing: {title, osiedle}\|null}], per_user: {user: n}, days}` — журнал: карточки, поиски, избранное, правки, экспорт |
| `GET /api/summary` | — | `{sale: {active, new_24h, median_sqm, median_price, removed_7d}, rent: {active, new_24h, median_rent, median_rent_sqm}, last_runs: {sale: Run, rent: Run}, scrape_running: bool, paused_until: str|null, translate: {pending_titles, pending_descriptions, done_total, provider, model}, fx: {USD: 4.0, EUR: 4.3, date: "2026-09-18"}, sources: [{source, active, last_seen}]}` |
| `GET /api/listings` | `offer_type` (sale\|rent, по умолчанию sale), `rooms` (через запятую), `price_min/max`, `area_min/max`, `sqm_min/max`, `district` (через запятую), `osiedle` (через запятую), `market`, `condition` (через запятую), `source`, `seller_type`, `build_year_min/max`, `floor_min/max`, `only_deals` (1 = discount_pct ≥ deal_threshold), `discount_min`, `yield_min`, `favorites` (1), `active` (1 по умолчанию, 0 = все), `dupes` (1 = показывать все размещения, по умолчанию только представителей), `q` (поиск по заголовку/улице), `sort` (discount\|price\|price_sqm\|posted\|first_seen\|area\|yield\|price_drop), `order` (asc\|desc), `page`, `per_page` (≤ 200) | `{total, page, per_page, items: [ListingRow]}` |
| `GET /api/listings/{id}` | — | ListingFull |
| `POST /api/listings/{id}/favorite` | `{value?: bool}` (без value — переключить) | `{is_favorite}` |
| `POST /api/listings/{id}/translate` | — | `{title_uk, description_uk, provider, cached: bool}` — переводит сейчас, синхронно (до 30 с) |
| `POST /api/listings/{id}/manual` | `{osiedle?, condition?, note?}` (null снимает правку) | ListingFull |
| `POST /api/listings/{id}/detach` | — | `{dedup_group}` — «інша квартира»: вынести из группы |
| `GET /api/geo` | — | `{districts: [{name, name_uk, osiedla: [{name, name_uk, sale_active, rent_active}]}]}` |
| `GET /api/stats` | `offer_type`, `level` (osiedle\|district), `rooms`, `market`, `condition` | `{rows: [{name, name_uk, district, count, median_sqm, p25_sqm, p75_sqm, median_price, median_area, new_30d, removed_30d, median_days}], total, area_coef: {band: coef}}` |
| `GET /api/price_index` | `period` (month\|quarter), `offer_type` | `{points: [{period, index, change_pct, n}]}` — индекс по одним и тем же объявлениям, база 100 |
| `GET /api/trends` | `weeks` (26), `offer_type` | `{points: [{week, new, removed, median_sqm, active}]}` |
| `GET /api/rent/yield_top` | `level` (osiedle\|district), `rooms`, `min_rent` (8), `min_sale` (8) | `{rows: [{name, name_uk, rooms, rent_median_pln, rent_sqm, sale_median_sqm, yield_pct, n_rent, n_sale}]}` |
| `GET /api/runs` | `limit` (50) | `[Run]`, Run = `{id, kind, source, status, started_at, finished_at, last_beat, pages, seen, new, updated, removed, errors, message}` |
| `POST /api/scrape` **[admin]** | `kind` (sale\|rent\|all), `source` (otodom\|olx\|all) | `{started: true, run_id}`; 409 если идёт прогон или пауза |
| `POST /api/scrape/stop` **[admin]** | — | `{stopping: true}` |
| `POST /api/scrape/pause` **[admin]** | `{hours}` (0 = до отмены) | `{paused_until}` |
| `POST /api/scrape/resume` **[admin]** | — | `{paused_until: null}` |
| `GET /api/translate/status` | — | `{provider, model, pending_titles, pending_descriptions, done_total, done_today, last_error, running}` |
| `POST /api/translate/run` **[admin]** | `{limit}` | `{started: true}` — фоновая обработка очереди |
| `GET /api/translate/unknown_values` | — | `[{field, value_pl, count}]` — что не нашлось в словаре |
| `POST /api/recompute` **[admin]** | — | `{started: true}` — дубли + выгодность + доходность в фоне |
| `GET /api/settings` **[admin]** | — | `{key: value}`; секреты замаскированы `••••••••` |
| `POST /api/settings` **[admin]** | `{key: value, ...}` — только ключи из `SAFE_KEYS` | `{saved: [keys]}` |
| `GET /api/jobs` | — | `{scheduler_running, disabled_by_env, jobs: [{id, next_run}]}` |
| `GET /api/export` | те же фильтры, что у `/api/listings`, + `format` (csv\|xlsx) | файл |

Ошибки — `{detail: "текст"}` с кодом 4xx/5xx; фронтенд показывает `detail`,
а при 404 на ручке — подсказку «сервер ещё не перезапущен после выкатки».
