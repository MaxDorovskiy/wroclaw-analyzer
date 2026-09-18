# -*- coding: utf-8 -*-
"""HTTP-клиент для площадок: темп, ретраи, распознавание блокировки, фолбэк
на настоящий Chromium.

Почему так, а не «requests.get в цикле»:

- DataDome (Otodom) весит HTTP/1.1 как признак бота — ходим по HTTP/2 с
  полным набором браузерных заголовков.
- Темп ≤ 15 запросов в минуту с случайной паузой: тот же потолок, что уберёг
  киевскую систему от Cloudflare Error 1015 на 1.29 млн строк лога.
- Блок распознаётся по признакам, а не по одному коду: 403 + заголовок
  x-datadome / cookie datadome / «dd» в теле. На него — пауза и, если
  разрешено, тот же адрес через Playwright (в 3–5 раз медленнее, поэтому
  только как фолбэк).
- OLX стоит за CloudFront WAF, который режет САМ КЛИЕНТ (отпечаток TLS/HTTP2
  у Python), а не IP и не темп: 18.09.2026 с одного ПК httpx получал 403
  «Request blocked» на любой адрес olx.pl (даже robots.txt), а Chromium — 200.
  Пауза тут не лечит, поэтому на такой блок браузер зовём сразу, а хост
  запоминаем (`_browser_hosts`): дальше по нему ходим только браузером, без
  заведомо битого httpx-запроса — иначе темп к площадке удваивается, и
  половина запросов — сплошные блоки в её логах.
- JSON браузером берём через fetch() СО СТРАНИЦЫ того же origin — так ходит
  сам сайт (куки, Sec-Fetch-Site: same-origin). page.goto() на JSON не годится:
  friendly-links отдаёт application/x-json, и Chromium начинает «download».
- Перед каждым запросом спрашиваем `stop_check()`: пауза и «стоп» из
  интерфейса должны сворачивать прогон за полминуты, а не после страницы №140.
"""
import logging
import random
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set

import httpx

from .config import PROBE_DIR, REQUEST_TIMEOUT, REQUESTS_PER_MINUTE, USER_AGENT

log = logging.getLogger("fetcher")

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}
JSON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


class BlockedError(Exception):
    """Анти-бот отдал блок. Лечится паузой/браузером/прокси, не ретраем."""


class StopRequested(Exception):
    """Владелец нажал «стоп» или включил паузу."""


def fingerprint_blocked(resp: httpx.Response) -> bool:
    """403 от самого CloudFront («Request blocked», x-cache: Error from cloudfront):
    WAF отверг клиента по отпечатку. Пауза и ретрай бесполезны — только браузер."""
    if resp.status_code != 403:
        return False
    h = {k.lower(): v for k, v in resp.headers.items()}
    if "cloudfront" not in h.get("server", "").lower():
        return False
    if "error from cloudfront" in h.get("x-cache", "").lower():
        return True
    return "request blocked" in resp.text[:2000].lower()


def looks_blocked(resp: httpx.Response) -> bool:
    if resp.status_code not in (403, 401, 429, 503):
        return False
    if fingerprint_blocked(resp):
        return True
    h = {k.lower(): v for k, v in resp.headers.items()}
    if any(k.startswith("x-datadome") or k == "x-dd-b" for k in h):
        return True
    if "datadome" in h.get("set-cookie", "").lower():
        return True
    body = resp.text[:4000].lower() if resp.headers.get("content-type", "").startswith("text") else ""
    return ("datadome" in body or "captcha-delivery" in body or "cf-chl" in body
            or "attention required" in body or "access denied" in body)


# fetch() изнутри страницы: тело как текст + статус (разбор JSON — на стороне Python)
_FETCH_JS = """async (url) => {
  const r = await fetch(url, {headers: {"Accept": "application/json"}, credentials: "include"});
  return [r.status, await r.text()];
}"""


class Fetcher:
    def __init__(self, rpm: int = REQUESTS_PER_MINUTE, mode: str = "httpx",
                 stop_check: Optional[Callable[[], bool]] = None,
                 dump_dir: Optional[Path] = None, timeout: float = REQUEST_TIMEOUT):
        self.min_gap = 60.0 / max(1, rpm)
        self.mode = mode                     # httpx | browser
        self.stop_check = stop_check
        self.dump_dir = dump_dir
        self._last = 0.0
        self._blocked_streak = 0
        self.stats: Dict[str, int] = {"requests": 0, "retries": 0, "blocked": 0, "browser": 0}
        self.client = httpx.Client(http2=True, headers=BROWSER_HEADERS, timeout=timeout,
                                   follow_redirects=True)
        self._pw = None
        self._browser = None
        self._page = None
        self._page_origin: Optional[str] = None      # origin документа, открытого в браузере
        self._browser_hosts: Set[str] = set()        # хосты, где httpx блокируется, а браузер проходит

    # ---------- темп ----------
    def _throttle(self):
        if self.stop_check and self.stop_check():
            raise StopRequested()
        gap = self.min_gap + random.uniform(0.2, 1.5)
        wait = self._last + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _sleep(self, sec: float):
        # спим кусочками, чтобы «стоп» не ждал конца длинной паузы
        end = time.monotonic() + sec
        while time.monotonic() < end:
            if self.stop_check and self.stop_check():
                raise StopRequested()
            time.sleep(min(2.0, end - time.monotonic()))

    # ---------- запросы ----------
    def get(self, url: str, params: Optional[dict] = None, json_api: bool = False,
            retries: int = 3) -> httpx.Response:
        headers = JSON_HEADERS if json_api else None
        host = httpx.URL(url).host
        backoff = (8, 25, 70)
        last_exc = None
        for attempt in range(retries + 1):
            self._throttle()
            self.stats["requests"] += 1
            via_browser = host in self._browser_hosts
            if via_browser:
                resp = self.browser_get(url, params, json_api)
                if resp is None:
                    raise BlockedError(u"%s: httpx блокируется, а браузер не справился" % host)
            else:
                try:
                    resp = self.client.get(url, params=params, headers=headers)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_exc = e
                    log.warning("%s: %s (попытка %d)", url, e.__class__.__name__, attempt + 1)
                    self.stats["retries"] += 1
                    self._sleep(backoff[min(attempt, 2)])
                    continue
            if resp.status_code == 200:
                self._blocked_streak = 0
                return resp
            # браузером 401/403 — блок без оговорок: заголовков WAF fetch() не отдаёт
            if looks_blocked(resp) or (via_browser and resp.status_code in (401, 403)):
                self.stats["blocked"] += 1
                self._blocked_streak += 1
                fingerprint = fingerprint_blocked(resp)
                log.warning("Похоже на блок (%d%s) на %s, серия %d", resp.status_code,
                            u", отпечаток клиента" if fingerprint else "", url, self._blocked_streak)
                if not via_browser and (self.mode == "browser" or fingerprint or self._blocked_streak >= 3):
                    br = self.browser_get(url, params, json_api)
                    if br is not None and br.status_code == 200:
                        # браузер прошёл там, где httpx заблокирован: до конца прогона этот
                        # хост — только браузером (см. докстринг модуля)
                        self._browser_hosts.add(host)
                        self._blocked_streak = 0
                        log.info("%s: дальше через Chromium", host)
                        return br
                    if fingerprint and br is None:
                        raise BlockedError(u"%s -> %d: WAF режет httpx по отпечатку, нужен Chromium "
                                           u"(playwright install chromium)" % (url, resp.status_code))
                if attempt >= retries:
                    raise BlockedError("%s -> %d" % (url, resp.status_code))
                self._sleep(60 * (attempt + 1))
                continue
            if resp.status_code == 429:
                ra = resp.headers.get("retry-after")
                wait = float(ra) if ra and ra.isdigit() else 60.0 * (attempt + 1)
                log.warning("429 на %s, ждём %.0f с", url, wait)
                self.stats["retries"] += 1
                self._sleep(wait)
                continue
            if resp.status_code >= 500:
                self.stats["retries"] += 1
                self._sleep(backoff[min(attempt, 2)])
                continue
            # 404 и прочие 4xx — не ретраим, отдаём как есть
            return resp
        if last_exc:
            raise last_exc
        raise httpx.HTTPError("исчерпаны попытки: %s" % url)

    def get_html(self, url: str, params: Optional[dict] = None) -> str:
        resp = self.get(url, params)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError("%d на %s" % (resp.status_code, url),
                                        request=resp.request, response=resp)
        return resp.text

    def get_json(self, url: str, params: Optional[dict] = None) -> dict:
        resp = self.get(url, params, json_api=True)
        if resp.status_code != 200:
            raise httpx.HTTPStatusError("%d на %s" % (resp.status_code, url),
                                        request=resp.request, response=resp)
        return resp.json()

    # ---------- фолбэк: настоящий браузер ----------
    def browser_get(self, url: str, params: Optional[dict] = None,
                    json_api: bool = False) -> Optional[httpx.Response]:
        """Тот же адрес через Chromium (Playwright). HTML — page.goto() и содержимое
        страницы после челленджа; JSON — fetch() со страницы того же origin.
        None — Playwright не установлен или браузер упал: тогда работаем как есть."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error("Playwright не установлен: pip install playwright && playwright install chromium")
            return None
        full = httpx.URL(url, params=params) if params else httpx.URL(url)
        origin = "%s://%s" % (full.scheme, full.host)
        request = httpx.Request("GET", full)
        try:
            if self._pw is None:
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(headless=True)
                ctx = self._browser.new_context(locale="pl-PL", user_agent=USER_AGENT,
                                                viewport={"width": 1366, "height": 900})
                self._page = ctx.new_page()
            self.stats["browser"] += 1
            if json_api:
                if self._page_origin != origin:
                    # документ того же origin для fetch(): robots.txt лёгкий, без
                    # баннеров согласия и никогда не «download»
                    self._page.goto(origin + "/robots.txt", wait_until="domcontentloaded", timeout=60000)
                    self._page_origin = origin
                status, body = self._page.evaluate(_FETCH_JS, str(full))
                return httpx.Response(int(status), text=body, request=request)
            nav = self._page.goto(str(full), wait_until="domcontentloaded", timeout=60000)
            self._page_origin = origin
            # DataDome-челлендж решается скриптом на странице за пару секунд
            self._page.wait_for_timeout(2500)
            html = self._page.content()
            # после челленджа статус первого ответа уже ничего не значит: страница
            # с данными — это 200, что бы ни пришло сначала
            status = 200 if ("__NEXT_DATA__" in html or nav is None) else nav.status
            return httpx.Response(status, text=html, request=request)
        except Exception as e:  # noqa: BLE001 — любой сбой браузера = фолбэк не помог
            log.error("Браузер не справился с %s: %s", full, e)
            self._page_origin = None
            return None

    def close(self):
        try:
            self.client.close()
        finally:
            if self._browser is not None:
                try:
                    self._browser.close()
                    self._pw.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._browser = self._pw = self._page = None
                self._page_origin = None

    # ---------- сырые ответы для разбора ----------
    def dump(self, name: str, text: str):
        if not self.dump_dir:
            return
        try:
            self.dump_dir.mkdir(parents=True, exist_ok=True)
            (self.dump_dir / name).write_text(text, encoding="utf-8")
        except OSError as e:
            log.warning("не записал %s: %s", name, e)


def make_fetcher(settings: Dict[str, str], stop_check=None, dump: bool = False) -> Fetcher:
    try:
        rpm = int(float(settings.get("requests_per_minute") or REQUESTS_PER_MINUTE))
    except ValueError:
        rpm = REQUESTS_PER_MINUTE
    mode = settings.get("fetch_mode") or "httpx"
    return Fetcher(rpm=rpm, mode=mode, stop_check=stop_check,
                   dump_dir=PROBE_DIR if dump else None)
