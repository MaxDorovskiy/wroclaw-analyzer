# Исследование: откуда брать объявления по Вроцлаву и что с ними делать

Дата: 18.09.2026. Автор исследования — Claude (сессия в облаке), заказчик — Максим.

## 0. Как проводилось и что НЕ удалось проверить

Среда, в которой писался этот документ, ходит в интернет через корпоративный
прокси, и он **закрывает все польские площадки** (otodom.pl, olx.pl, morizon.pl,
gratka.pl, nieruchomosci-online.pl, domiporta.pl, rynekpierwotny.pl, adresowo.pl)
и даже pl.wikipedia.org — на CONNECT приходит 403. Поэтому:

- структура страниц и JSON описана по **опубликованным описаниям парсеров и
  документации** (ссылки внизу) и по памяти о том, как эти площадки устроены
  в 2024-2025; точные имена полей нужно **подтвердить первым запуском**;
- для этого в проекте есть `scripts/probe_sources.py`: он делает по одному
  запросу к каждому источнику с домашнего IP, печатает статус, число
  объявлений и три разобранные записи, и сохраняет сырые ответы в
  `data/probe/` — по ним чинятся имена полей, если они разъехались;
- цифры рынка (цены, ставки) взяты из открытых сводок за сентябрь 2026 —
  они нужны только как ориентиры для санитарных порогов и проверок «похоже
  ли на правду».

## 1. Рынок Вроцлава в цифрах (сентябрь 2026)

| Показатель | Значение | Источник |
|---|---|---|
| Средняя ОФЕРТНАЯ цена, все квартиры | ≈13 540–13 600 zł/м² | tabelaofert.pl, cenametra.pl |
| Медиана ЦЕНЫ СДЕЛОК, вторичный рынок (12 мес) | 12 514 zł/м² | deweloperuch.pl (RCN) |
| Медиана цены сделок, первичный рынок | 13 140 zł/м² (+5% к вторичке) | deweloperuch.pl |
| Средняя цена сделок за 12 мес | 12 882 zł/м² (+1.1% к 2025) | там же |
| Аренда: средняя ставка / за м² | ≈2 800 zł/мес; 67–68 zł/м² | cenametra.pl, cenacheck.pl |
| Аренда 2-комн. 45–55 м², медиана | ≈3 400 zł/мес без czynsz и медиа | znajdznajem.pl |
| Первичка: предложений у застройщиков | 5 270 квартир в 110 инвестициях, из них 2 281 во Fabryczna | rynekpierwotny.pl |

Что из этого следует для системы:

- **Разрыв «оферта → сделка» около 8%** (13.5k против 12.5k). Скидка,
  которую покажет оценка выгодности, считается относительно ОФЕРТ, и это надо
  писать в подсказке, как в киевской системе.
- **Валовая доходность аренды ≈ 5–6%**: 3 400×12 / (50 м²×13 000) ≈ 6.3% до
  налога (ryczałt 8.5%), простоя и czynsz administracyjny. Порог «интересно»
  для фильтра доходности — от 6%.
- **Санитарные пороги** каталога: цена за м² вне 4 000–40 000 zł — мусор
  (гаражи, доли, опечатки); площадь < 12 м² — не квартира.

## 2. Площадки

| Площадка | Что это | Как забирать | Анти-бот | Приоритет |
|---|---|---|---|---|
| **otodom.pl** (OLX Group) | Крупнейший профильный портал, агентства + застройщики + частники, продажа и аренда | Next.js: JSON в `<script id="__NEXT_DATA__">` и на выдаче, и на карточке; `limit=72` на страницу; районы — 48 осиедле | DataDome (403 + заголовок `x-datadome`, cookie `datadome`); переживает низкий темп с домашнего IP, при блоке — Chromium через Playwright | **1 — основной** |
| **olx.pl** (та же группа) | Массовые объявления, много частников; часть — зеркала Otodom (`external_url` → otodom) | JSON API без ключа: `/api/v1/offers/?category_id&city_id&offset&limit=40`, параметры (`price`, `m`, `rooms`, `floor_select`, `market`, `builttype`, `furniture`, `rent`) и описание приходят СРАЗУ — карточку качать не надо | Мягкий rate-limit (429); потолок `offset` ~1000 → выдачу дробить по цене | **1 — основной** |
| **morizon.pl + gratka.pl** | Одна группа (Morizon-Gratka), агентские фиды, 35 на страницу | HTML + JSON-LD на карточке | Cloudflare (обычный) | 2 — после накопления базы: доля уникальных объявлений неизвестна, а дублей с Otodom много |
| **nieruchomosci-online.pl** | Большая база, **отдельно помечает собственников** («bez pośredników») | HTML | Слабый | 2 — ради признака «собственник» |
| **rynekpierwotny.pl / tabelaofert.pl / obido.pl** | Первичка от застройщиков: инвестиции, корпуса, планировки, цены за м² | HTML/JSON; отдельная сущность «инвестиция» (аналог справочника ЖК с ЛУН) | Слабый | 2 — когда появится задача «купить у застройщика» |
| domiporta.pl, adresowo.pl, szybko.pl | Мелкие агрегаторы | HTML | — | 3 — не нужны |
| **RCN** (Rejestr Cen Nieruchomości), sonarhome.pl, cenatorium/urban.one | ЦЕНЫ СДЕЛОК, не оферты | Платно, по запросу в геодезии Вроцлава / подписка | — | Позже: калибровка «оферта → сделка» |
| NBP (api.nbp.pl) | Курсы USD/EUR к злотому, JSON, бесплатно | `GET /api/exchangerates/rates/a/usd/?format=json` → `rates[0].mid` | — | В системе с первого дня |

Почему только два источника в первой версии: Otodom и OLX вместе покрывают
почти всё, что есть на рынке (Morizon/Gratka в основном зеркалят агентские
фиды, которые и так стоят на Otodom). Третий источник добавляется тем же
интерфейсом адаптера (`backend/app/sources/base.py`), когда база покажет,
сколько объявлений уникальны — см. `DEFERRED.md`, пункт 1.

### 2.1 Otodom — что известно о структуре

Выдача: `https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/dolnoslaskie/wroclaw/wroclaw/wroclaw?limit=72&page=N&by=LATEST&direction=DESC`
(аренда — `wynajem` вместо `sprzedaz`). В `__NEXT_DATA__`:

```
props.pageProps.data.searchAds.items[]   — объявления
props.pageProps.data.searchAds.pagination — totalPages, totalResults, itemsPerPage
```

Поля объявления на выдаче (по описаниям парсеров): `id`, `title`, `slug`,
`estate` (FLAT), `transaction` (SELL/RENT), `location.address.{street,city,district,province}`,
`location.reverseGeocoding.locations[]` (уровни: город, район, осиедле),
`totalPrice.value`, `pricePerSquareMeter.value`, `rentPrice`, `areaInSquareMeters`,
`roomsNumber` (ONE…TEN, MORE), `floorNumber` (GROUND, FLOOR_1…, FLOOR_HIGHER_10),
`images[].medium/large`, `isPrivateOwner`, `agency{name,type}`, `dateCreated`,
`dateCreatedFirst`, `investmentState`, `hidePrice`.

Карточка `https://www.otodom.pl/pl/oferta/<slug>-ID<id>`: `props.pageProps.ad` —
`description` (HTML), `characteristics[] {key, value, label, localizedValue}`
(ключи: `price`, `m`, `rooms_num`, `floor_no`, `building_floors_num`, `market`,
`build_year`, `building_type`, `building_material`, `construction_status`,
`windows_type`, `heating`, `rent` (czynsz), `lift`, `building_ownership`,
`extras_types`, `security_types`, `media_types`, `equipment_types`),
`target{...}` (те же данные плоско: `Build_year`, `Market`, `OwnerType`…),
`location.coordinates.{latitude,longitude}`, `owner{type}`, `agency`,
`createdAt`, `modifiedAt`, `images[]`.

Адаптер читает и `characteristics`, и `target`, и хранит сырой JSON в
`raw_json` — если имя поля разъедется, данные не потеряются, а разбор
можно повторить без повторного скрапа (`scripts/reparse.py`).

### 2.2 OLX — что известно о структуре

`GET https://www.olx.pl/api/v1/offers/?offset=0&limit=40&category_id=<14|15>&city_id=19701&sort_by=created_at:desc`
плюс фильтры `filter_float_price:from`, `filter_float_price:to`. Ответ:
`data[]` объявлений, `metadata.total_elements`, `links.next`.

Объявление: `id`, `url`, `title`, `description`, `created_time`,
`last_refresh_time`, `params[] {key, name, type, value{key,label,value}}`,
`location{city{id,name}, district{id,name}, region{...}}`, `map{lat,lon,zoom}`,
`photos[] {link}` (шаблон `;s={width}x{height}`), `user{id,name}`,
`business` (bool), `contact{phone: bool}`, `category{id}`,
`external_url` — **у зеркал Otodom ведёт на otodom.pl**, это готовый ключ
для склейки дублей между источниками.

Ловушки, о которых пишут авторы парсеров: **id категорий и городов со
временем меняют** (при нуле объявлений первым делом проверять их); в OLX
районы Вроцлава — только 5 старых дзельниц, осиедле нет; частники без
`business`; телефон через API не отдаётся (флаг есть, номер — нет).
Id категорий (`14` продажа квартир, `15` аренда) и города (`19701` Вроцлав)
вынесены в настройки, а `probe_sources.py` печатает `category.id` и
`location.city` первых записей — по ним видно, туда ли попали.

## 3. Анти-бот, темп, этика

- **Otodom за DataDome.** Признаки блока: 403, заголовок `x-datadome` /
  `x-dd-b`, cookie `datadome`, в теле `dd` в `<script>`. DataDome весит
  HTTP/1.1 как признак бота — клиент ходит по **HTTP/2** (`httpx[http2]`),
  с полным набором браузерных заголовков и `Accept-Language: pl-PL`.
- **Темп — не быстрее 12–15 запросов в минуту на источник**, случайные
  паузы, источники **по очереди, не параллельно** (тот же урок, что и с
  rieltor.ua в Киеве: всплеск с домашнего IP = бан).
- **Возобновляемость:** прогон помнит страницу, с которой упал, и при
  повторе продолжает; полный обход Otodom (~150 страниц по 72) — это
  10–15 минут чистого времени, OLX — столько же.
- **Фолбэк на Chromium** (`WRO_FETCH_MODE=browser`): Playwright открывает
  страницу в настоящем браузере и отдаёт HTML; в 3–5 раз медленнее, включать
  только когда httpx получил 403 от DataDome три раза подряд. Драйвер тот же,
  что в киевском `phone_browser.py`.
- **Платные прокси** (владелец называл iproyal.com) — по тому же признаку,
  что и в Киеве: устойчивые 403/1015 при темпе ≤15/мин.
- **Этика и право:** данные — публичные объявления, использование — личный
  анализ рынка без перепубликации. Регламенты площадок автоматический
  сбор не приветствуют; при жалобе (письмо, бан) — остановиться и перейти на
  официальный API OLX для партнёров (developer.olx.pl, OAuth2).

## 4. География: 5 дзельниц и 48 осиедле

С 1991 года Вроцлав делится на **48 осиедле** (самоуправления); пять старых
дзельниц (Stare Miasto, Śródmieście, Krzyki, Fabryczna, Psie Pole) остались в
обиходе и на OLX. Распределение: Fabryczna 14, Krzyki 14, Psie Pole 12,
Śródmieście 5, Stare Miasto 3.

- Otodom даёт **осиедле** (в `reverseGeocoding` и `address.district`), OLX —
  только **дзельницу**. Единица аналитики — осиедле; дзельница — агрегат.
- Справочник — `backend/app/geo.py`: список 48 осиедле, украинская
  транскрипция для показа рядом с оригиналом («Krzyki · Кшики»), соответствие
  осиедле → дзельница. **Соответствие проставлено по памяти и требует
  сверки** с https://geoportal.wroclaw.pl/osiedla/ — сомнительные
  (Kleczków, Przedmieście Oławskie) помечены в коде.
- Для OLX-объявлений осиедле восстанавливается из улицы (`street` →
  справочник улиц; пока пусто — DEFERRED, пункт 3) или из текста.

## 5. Перевод на украинский

Требование: показывать оригинал по-польски и украинский перевод рядом, для
всего содержимого — заголовок, описание, структурные поля.

Объём: порядка **500 новых объявлений в день × ~1 500 символов ≈ 750 тыс.
символов в день**, ~22 млн в месяц (зеркала Otodom↔OLX с тем же текстом —
попадание в кэш, реальный объём меньше).

| Провайдер | Качество PL→UK | Цена при 22 млн симв./мес | Замечания |
|---|---|---|---|
| **Ollama, локально** (gemma3 12b / qwen3 8b / aya-expanse 8b) | Хорошее для описаний квартир; термины («stan deweloperski», «czynsz») надо закрепить в подсказке | 0 zł, ток | Та же карта, что считает ремонт в Киеве; 750 тыс. симв./день ≈ 1.5–2 ч работы 8–12b модели |
| **Anthropic API** (по умолчанию `claude-opus-5`; `claude-haiku-4-5` — дешёвый вариант) | Отличное, понимает риелторский жаргон обеих стран | Opus 5 ≈ $7/день (≈$215/мес); Haiku 4.5 ≈ $1.5/день (≈$45/мес) | Модель — настройка `translate_anthropic_model`; включён серверный фолбэк на отказ |
| Google Cloud Translation v2 | Хорошее, буквальное | 500 тыс. симв./мес бесплатно, дальше $20/млн → ≈$440/мес | Ключ API, без SDK |
| DeepL | Хорошее; украинский поддерживается с 09.2022 | Бесплатный API-план **новым клиентам не продаётся с 07.2026**; Developer-план по подписке | Оставлен как провайдер для тех, у кого ключ уже есть |

Решение:

1. Провайдер — настройка (`translate_provider`: `ollama` | `anthropic` |
   `google` | `deepl` | `none`), по умолчанию `ollama`.
2. **Кэш переводов** по хэшу текста (`translations`): один и тот же текст
   (зеркала, повторные подачи) переводится один раз.
3. **Структурные поля переводятся словарём** (`i18n.py`): тип дома, рынок,
   отопление, окна, форма собственности, состояние — детерминированно и
   бесплатно. Осиедле — транскрипция из справочника.
4. Заголовки — сразу при появлении объявления; описания — очередью с
   суточным потолком (`translate_daily_cap`) и **по требованию** при открытии
   карточки (кнопка «Перекласти зараз»).
5. Оригинал хранится всегда; перевод — производная, её можно пересчитать
   другим провайдером (`translate_version` в записи).

## 6. Что взять из киевской системы, а что нет

Берём: контур «прогон → история цен → снятие → дубли → выгодность →
доходность», UTC внутри / Киев наружу, basic-auth мидлвар, launchd-триггеры с
паролем из plist, `safe_restart.sh`, правило «проверять на копии базы»,
`err.status` во фронтенде, отметку жизни отдельной сессией.

Не берём: телефоны (на польских площадках их не отдают без формы),
скачивание фотографий (37 ГБ в Киеве; здесь храним только ссылки на CDN,
фото нужны модели ремонта — это DEFERRED), ЖК-консенсус (в Польше
«inwestycja» есть только у первички — придёт с rynekpierwotny), проверку
ремонта моделью (сначала база, потом модель).

## 7. Открытые вопросы владельцу

1. Только квартиры или ещё дома/участки? (Сейчас — квартиры, продажа и аренда.)
2. Нужна ли первичка от застройщиков отдельным разделом (rynekpierwotny)?
3. ~~Где будет крутиться~~ — решено: ПК с Windows 11 в Киеве (общий домашний
   IP с киевской системой → окна прогонов разведены; польского IP нет —
   DataDome может быть строже, фолбэк на Chromium и прокси предусмотрены).
4. Перевод: локальная модель (бесплатно, медленнее) или API (быстро, платно)?

## Источники

- Otodom, структура `__NEXT_DATA__`: https://apify.com/scrapyx/otodom-properties-scraper , https://pyotodom.readthedocs.io/en/latest/api.html , https://www.scrapingbee.com/scrapers/otodom-scraper-api/
- DataDome, признаки блока: https://scrapfly.io/blog/posts/how-to-bypass-datadome-anti-scraping , https://www.aethyn.io/blog/datadome-403-same-status-different-outcomes
- OLX API: https://apify.com/solidcode/olx-pl-scraper , https://apify.com/automation-lab/olx-poland-classifieds-scraper , партнёрский API: https://developer.olx.pl/api/doc
- Morizon/Gratka/NO: https://apify.com/studio-amba/morizon-scraper , https://apify.com/studio-amba/nieruchomosci-online-scraper , https://apify.com/alexist/gratka-property-details-scraper/api
- Первичка: https://rynekpierwotny.pl/s/nowe-mieszkania-wroclaw/ , https://apify.com/trev0n/rynekpierwotny-scraper/api
- Цены: https://tabelaofert.pl/ceny-mieszkan/wroclaw , https://cenametra.pl/ceny-mieszkan/wroclaw , https://deweloperuch.pl/statystyki/ceny-transakcyjne/mieszkania/wroclaw , https://sonarhome.pl/ceny-mieszkan/wroclaw
- Аренда: https://znajdznajem.pl/poradnik/ile-kosztuje-wynajem-wroclaw , https://cenacheck.pl/poradnik/ceny-wynajmu-mieszkan
- Районы: https://pl.wikipedia.org/wiki/Podzia%C5%82_administracyjny_Wroc%C5%82awia , https://geoportal.wroclaw.pl/osiedla/ , https://www.wroclaw.pl/dla-mieszkanca/kiedy-wroclaw-podzielono-na-dzielnice
- Перевод: https://support.deepl.com/hc/en-us/articles/360019925219-DeepL-Translator-languages , https://www.eesel.ai/blog/deepl-pricing , https://langbly.com/blog/google-translate-api-pricing-guide/
- Курсы: https://api.nbp.pl/en.html
