#!/usr/bin/env python3
"""Проверка интерфейса БЕЗ сервера: сборка frontend/dist открывается через
file://, все запросы к /api/ перехватываются и получают JSON-фикстуры из
tests/fixtures/ui/. Делает скриншоты разделов и падает с ненулевым кодом,
если в консоли браузера была ошибка (pageerror или console.error).

    .venv/bin/python scripts/ui_check.py [каталог_для_скриншотов]

Зачем так: сервер обслуживает живую базу, а фронтенд меняется чаще бэкенда.
Смотреть каждую правку вёрстки на боевом сервере — значит перезапускать его
(и рисковать прогоном), на копии — поднимать второй uvicorn. Фикстуры по
контракту docs/API.md дают ту же картинку за пять секунд и ещё ловят разъезд
фронтенда с контрактом: неизвестная ручка отвечает 404 и валит проверку.

Почему подставляется http-адрес: со страницы file:// браузер запрещает
fetch по схеме file: ещё до сети, перехватить нечего. Поэтому api.js читает
window.__API_BASE__ (в бою пустой), а здесь он указывает на несуществующий
хост, который целиком перехватывает page.route.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'frontend' / 'dist' / 'index.html'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'ui'
API_BASE = 'http://ui-check.invalid'
# куда класть скриншоты, если путь не передан аргументом. Раньше здесь
# стоял путь чужой машины (переехал из киевского репозитория) — на Windows
# он создавал папку tmp в корне диска C, и найти картинки было негде.
DEFAULT_OUT = str(Path(tempfile.gettempdir()) / 'wro-ui')
VIEWPORT = {'width': 1440, 'height': 900}

# Картинки объявлений в фикстурах — настоящие CDN-адреса; сети здесь нет, и
# каждая несостоявшаяся загрузка — console.error, который валил бы проверку.
PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="120">'
    '<rect width="100%" height="100%" fill="#c3c2b7"/>'
    '<text x="50%" y="54%" font-family="sans-serif" font-size="14" text-anchor="middle" '
    'fill="#52514e">фото</text></svg>'
).encode('utf-8')

CORS = {'Access-Control-Allow-Origin': '*'}

# Страница открыта через file://, а сборка Vite подключает скрипт как ES-модуль:
# такие скрипты всегда грузятся в CORS-режиме, и Chromium с origin «null» их
# режет («Cross origin requests are only supported for protocol schemes…»).
# Флаг разрешает file:// читать file:// — только в этой проверке, боевой
# сервер раздаёт dist по http и флага не требует.
CHROME_ARGS = ['--allow-file-access-from-files']


def fixture_name(path, query):
    """/api/listings/101 -> listing.json; /api/listings?offer_type=rent ->
    listings_rent.json; /api/translate/status -> translate_status.json."""
    p = path[len('/api/'):].strip('/')
    if re.fullmatch(r'listings/\d+', p):
        return 'listing.json'
    if p == 'listings' and query.get('offer_type', [''])[0] == 'rent':
        return 'listings_rent.json'
    return p.replace('/', '_') + '.json'


def post_response(path):
    """Ответы на действия — по контракту, минимально правдоподобные."""
    if path.endswith('/favorite'):
        return {'is_favorite': True}
    if path.endswith('/translate'):
        return {'title_uk': 'Перекладений заголовок', 'description_uk': 'Перекладений опис',
                'provider': 'ollama', 'cached': False}
    if path.endswith('/manual'):
        return json.loads((FIXTURES / 'listing.json').read_text(encoding='utf-8'))
    if path.endswith('/detach'):
        return {'dedup_group': 'g:detached'}
    if path.endswith('/scrape/pause'):
        return {'paused_until': '2026-09-19T09:00:00+03:00'}
    if path.endswith('/scrape/resume'):
        return {'paused_until': None}
    if path.endswith('/scrape/stop'):
        return {'stopping': True}
    if path.endswith('/scrape'):
        return {'started': True, 'run_id': 42}
    if path.endswith('/settings'):
        return {'saved': []}
    return {'started': True}


def launch_chromium(p):
    """Обычный запуск, а если пакет playwright и скачанные браузеры разных
    версий (пакет ждёт сборку N, на диске лежит N−1 — так было 18.09.2026:
    playwright 1.63 против chromium-1194 от 1.56), берём любой Chromium из
    PLAYWRIGHT_BROWSERS_PATH через executable_path. Протокол между соседними
    сборками совместим, а `playwright install` в этой среде запрещён."""
    try:
        return p.chromium.launch(args=CHROME_ARGS)
    except Exception as e:   # noqa: BLE001 — любая причина, дальше ищем сами
        first_error = e
    root = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
                or Path.home() / '.cache' / 'ms-playwright')
    patterns = [
        'chromium_headless_shell-*/chrome-linux/headless_shell',
        'chromium-*/chrome-linux/chrome',
        'chromium_headless_shell-*/chrome-win/headless_shell.exe',
        'chromium-*/chrome-win/chrome.exe',
        'chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium',
    ]
    for pat in patterns:
        for exe in sorted(root.glob(pat), reverse=True):
            try:
                b = p.chromium.launch(executable_path=str(exe), args=CHROME_ARGS)
                print(f'  браузер по умолчанию не запустился ({first_error.__class__.__name__}), '
                      f'взяли {exe}')
                return b
            except Exception:   # noqa: BLE001
                continue
    raise first_error


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not DIST.exists():
        print(f'Немає сборки: {DIST} — сначала `npm run build` в frontend/')
        return 2

    errors = []          # ошибки консоли и страницы
    missing = []         # ручки без фикстуры — разъезд с контрактом
    served = []

    try:
        run_scenario(errors, missing, served, out_dir)
    finally:
        report(errors, missing, served)
    return 0 if not errors and not missing else 1


def report(errors, missing, served):
    print(f'фикстур отдано: {len(served)}, разных: {len(set(served))}')
    if missing:
        print('РУЧКИ БЕЗ ФИКСТУРЫ (разъезд с контрактом или опечатка в api.js):')
        for m in sorted(set(missing)):
            print('  ' + m)
    if errors:
        print('ОШИБКИ В КОНСОЛИ БРАУЗЕРА:')
        for e in errors:
            print('  ' + e)
    print('OK' if not errors and not missing else 'ПРОВАЛ')


def run_scenario(errors, missing, served, out_dir):
    # Подмена фикстур по ходу сценария: {'me.json': 'me_viewer.json'} делает
    # из владельца рієлторку с ролью viewer.
    overrides = {}

    def viewer_mode():
        return overrides.get('me.json') == 'me_viewer.json'

    def handle(route, request):
        url = urlparse(request.url)
        if not url.path.startswith('/api/'):
            route.fulfill(status=200, content_type='image/svg+xml', body=PLACEHOLDER_SVG, headers=CORS)
            return
        # viewer: закрытые ручки отвечают 403, как боевой сервер — если страница
        # их всё-таки дёрнет, 403 попадёт в консоль и завалит проверку
        if viewer_mode() and (url.path.startswith('/api/activity') or url.path == '/api/settings'
                              or (request.method == 'POST' and (url.path.startswith('/api/scrape')
                                  or url.path in ('/api/recompute', '/api/translate/run')))):
            route.fulfill(status=403, content_type='application/json',
                          body='{"detail": "Лише для адміністратора"}', headers=CORS)
            return
        if request.method == 'POST':
            body = json.dumps(post_response(url.path), ensure_ascii=False)
            route.fulfill(status=200, content_type='application/json', body=body, headers=CORS)
            return
        name = fixture_name(url.path, parse_qs(url.query))
        name = overrides.get(name, name)
        f = FIXTURES / name
        if not f.exists():
            missing.append(f'{request.method} {url.path}?{url.query} -> {name}')
            route.fulfill(status=404, content_type='application/json',
                          body='{"detail": "Not Found"}', headers=CORS)
            return
        served.append(name)
        route.fulfill(status=200, content_type='application/json',
                      body=f.read_bytes(), headers=CORS)

    with sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page(viewport=VIEWPORT)
        page.add_init_script(f'window.__API_BASE__ = {json.dumps(API_BASE)}')
        page.route(re.compile(r'^https?://'), handle)
        # На шаге «ручки нет» 404 ожидаем нарочно — браузер всё равно пишет
        # об этом в консоль, и тот единственный ответ ошибкой не считаем.
        allow_404 = [False]
        page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}')
                if m.type == 'error' and not (allow_404[0] and 'status of 404' in m.text) else None)
        page.on('requestfailed', lambda r: errors.append(f'requestfailed: {r.url} {r.failure}'))

        def shot(name, full_page=True):
            path = out_dir / f'{name}.png'
            page.screenshot(path=str(path), full_page=full_page)
            print(f'  скриншот: {path}')

        def go(hash_, wait_for):
            page.evaluate(f'location.hash = {json.dumps(hash_)}')
            page.wait_for_selector(wait_for, timeout=15000)
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(300)   # даём дорисоваться графикам и шрифтам

        base = DIST.as_uri()
        print(f'открываем {base}')
        page.goto(base + '#/catalog', wait_until='load')
        page.wait_for_selector('table.grid tbody tr.clickable', timeout=15000)
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(300)
        shot('catalog')

        # переключатель языка: оригинал — заголовки польские
        page.click('.lang-switch button:has-text("оригінал")')
        page.wait_for_timeout(200)
        shot('catalog_pl')
        page.click('.lang-switch button:has-text("обидва")')
        page.wait_for_timeout(200)

        # карточка: высокий viewport, потому что оверлей фиксированный и
        # full_page его не разворачивает
        page.set_viewport_size({'width': 1440, 'height': 2600})
        go('#/catalog?id=101', '.modal table.chars')
        shot('card', full_page=False)
        # действия в карточке: перевод «зараз» подменяет заголовок ответом
        # ручки, обране переключается — ловим ошибки в обработчиках
        page.click('.modal button:has-text("Перекласти зараз")')
        page.wait_for_selector('.modal h2:has-text("Перекладений заголовок")', timeout=10000)
        page.click('.modal button:has-text("В обраних")')
        page.wait_for_timeout(300)
        page.keyboard.press('Escape')
        page.wait_for_selector('.modal', state='detached', timeout=5000)
        page.set_viewport_size(VIEWPORT)

        # сортировка кликом по заголовку — повторный запрос и стрелка
        page.click('table.grid th:has-text("Ціна")')
        page.wait_for_selector('table.grid th:has-text("Ціна ▲")', timeout=5000)
        page.wait_for_load_state('networkidle')

        # тёмная тема: та же страница при prefers-color-scheme: dark
        page.emulate_media(color_scheme='dark')
        page.wait_for_timeout(200)
        shot('catalog_dark')
        page.emulate_media(color_scheme='light')

        # Огляд — домашний экран, на нём открывается система
        go('#/home', '.cards .card')
        if 'Стан системи' not in page.inner_text('body'):
            errors.append('огляд: немає панелі стану системи')
        shot('home')

        go('#/deals?preset=d15', 'table.grid tbody tr.clickable')
        shot('deals')
        go('#/rent', 'table.grid tbody tr.clickable')
        shot('rent')
        # обране: свій список, у власника — вибір чийого (звірка з /api/favorites/users)
        go('#/favorites', 'table.grid tbody tr.clickable')
        if '★ Обране' not in page.inner_text('.panel'):
            errors.append('обране: немає заголовка розділу')
        if 'yulia' not in page.inner_text('.panel'):
            errors.append('обране: власник не бачить вибору чийого списку дивитись')
        shot('favorites')

        go('#/contacts', 'table.grid tbody tr.clickable')
        shot('contacts')
        go('#/stats', '.recharts-line')
        shot('stats')
        go('#/runs', 'table.grid tbody tr')
        shot('runs')
        go('#/settings', '.form-grid input')
        shot('settings')

        # журнал дій: плашки per_user и расшифрованный запрос поиска
        go('#/journal', 'table.grid tbody tr')
        if 'yulia' not in page.inner_text('.filters'):
            errors.append('журнал: немає плашки per_user для yulia')
        if '4+ кімн.' not in page.inner_text('table.grid'):
            errors.append('журнал: запит пошуку не розшифровано (rooms=4,5,…,10 → «4+ кімн.»)')
        shot('journal')

        # роль viewer: /api/me отдаёт другую фикстуру; роль читается при
        # старте приложения, поэтому страница перезагружается целиком
        overrides['me.json'] = 'me_viewer.json'
        page.evaluate('location.hash = "#/catalog"')
        page.reload(wait_until='load')
        page.wait_for_selector('table.grid tbody tr.clickable', timeout=15000)
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(300)
        tabs = page.locator('.tabs button').all_inner_texts()
        for hidden in ('Журнал', 'Прогони', 'Налаштування'):
            if hidden in tabs:
                errors.append(f'viewer бачить вкладку «{hidden}»: {tabs}')
        if 'yulia' not in page.inner_text('.topbar .status'):
            errors.append("viewer: ім'я користувача не показано в шапці")
        go('#/journal', '.admin-only')
        if 'лише для адміністратора' not in page.inner_text('.admin-only').lower():
            errors.append('viewer: прямий перехід у журнал не пояснено')
        shot('viewer')
        go('#/runs', 'table.grid tbody tr')
        if page.locator('button:has-text("Запустити продаж")').count():
            errors.append('viewer бачить кнопку запуску прогону')
        del overrides['me.json']

        # Ручки ещё нет (сервер не перезапущен после выкатки): страница обязана
        # объяснить это словами, а не показать голое «Not Found». Маршрут,
        # зарегистрированный позже, у Playwright главнее — перекрываем stats.
        allow_404[0] = True
        page.route('**/api/stats*', lambda route, req: route.fulfill(
            status=404, content_type='application/json', body='{"detail": "Not Found"}', headers=CORS))
        go('#/stats', '.error-box')
        hint = page.inner_text('.error-box')
        if 'не перезапущений' not in hint:
            errors.append(f'404 без подсказки о выкатке: {hint!r}')
        shot('stats_404')
        allow_404[0] = False

        browser.close()


if __name__ == '__main__':
    sys.exit(main())
