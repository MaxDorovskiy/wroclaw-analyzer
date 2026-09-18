# Wrocław Analyzer

Сбор и анализ объявлений о квартирах во Вроцлаве (продажа и аренда) по образцу
киевского RE Analyzer: otodom.pl + olx.pl → SQLite → выгодность, доходность,
срезы по осиедле, индекс цен, карточки контактов — с украинским переводом
рядом с польским оригиналом. Бэкенд FastAPI, фронтенд React/Vite, интерфейс
на украинском. Стоит на ПК с Windows 11 (см. `deploy/windows/README.md`).

Документы: `docs/RESEARCH.md` (площадки, анти-бот, перевод, цифры рынка),
`docs/ARCHITECTURE.md`, `docs/API.md` (контракт), `docs/SPEC.md` (ТЗ),
`docs/FIRST_RUN.md` (что делать при первом запуске на ПК), `DEFERRED.md`
(отложенное с признаком возврата), `CLAUDE.md` (правила работы с проектом).

## Быстрый старт (разработка, любая ОС)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests -q                       # 6 тестов на фикстурах
.venv/bin/python scripts/demo_seed.py --db data/demo.db   # синтетика для интерфейса
cd frontend && npm install && npm run build && cd ..
WRO_DB=data/demo.db DISABLE_SCHEDULER=1 .venv/bin/uvicorn app.main:app --app-dir backend --port 8020
```

Открыть http://127.0.0.1:8020. Пароль — `WRO_WEB_PASS` (пустой = открыто,
только для локальной проверки); дополнительные логины — `WRO_WEB_USERS`
(`yulia:пароль`), их действия видны администратору в «Журналі».
Данные и логи — `data/` или `WRO_DATA`.

## Боевой запуск (Windows 11)

`deploy/windows/install.ps1` — venv, зависимости, Chromium для Playwright,
сборка фронтенда, задачи Планировщика (сервер + прогоны 11:00 / 17:00 /
аренда 02:30), брандмауэр. Пароль и путь к данным — в `deploy/windows/env.ps1`
(не в git). Перезапуск — только `safe_restart.ps1`.

**Перед первым прогоном** — `scripts/probe_sources.py`: среда, в которой
писался код, не имела доступа к польским площадкам, и имена полей в JSON
надо подтвердить на живых ответах (сырые ответы лягут в `data/probe/`).

## Что где

| Файл | Что делает |
|---|---|
| `backend/app/sources/otodom.py`, `olx.py` | адаптеры площадок (выдача, карточка) |
| `backend/app/normalize.py` | приведение полей, класс состояния по словам |
| `backend/app/geo.py` | 5 дзельниц, 48 осиедле, украинская транскрипция |
| `backend/app/scraper.py` | прогон: upsert, история цен, хвост, снятие, пауза, сторож |
| `backend/app/dedup.py` | дубли: зеркало OLX→Otodom, числа, первая картинка |
| `backend/app/analytics.py` | выгодность (пулы с релаксацией), срезы, индекс цен |
| `backend/app/rent_analytics.py` | доходность от сдачи, топ мест |
| `backend/app/translate.py`, `i18n.py` | перевод PL→UK: провайдеры, кэш, словарь полей |
| `backend/app/main.py` | API (docs/API.md), пароль, статика, планировщик |
| `scripts/probe_sources.py` | проверка адаптеров на новом месте |
| `scripts/explain_deal.py <id>` | почему такая скидка — по шагам |
| `scripts/reparse.py` | повторный разбор raw_json после правки парсера |
| `scripts/translate_backlog.py` | догнать очередь перевода |
| `scripts/ui_check.py` | скриншоты интерфейса на фикстурах без сервера |
| `deploy/windows/` | установка, сервер, триггеры, безопасный перезапуск |

## Проверка правок

На КОПИИ базы: `sqlite3.backup()` → `data/wro-copy.db`, `WRO_DB=data/wro-copy.db`,
порт 8021; фронтенд dev-сервером `VITE_API=http://127.0.0.1:8021 npm run dev -- --port 5175`.
Тесты — `.venv/bin/python -m pytest tests -q`.
