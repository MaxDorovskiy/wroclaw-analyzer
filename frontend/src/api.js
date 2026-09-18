// Базовый адрес API. В бою пустой: фронтенд раздаётся тем же сервером, что и
// API, и fetch('/api/…') идёт на него же. Переопределение нужно проверке без
// сервера (scripts/ui_check.py): страница там открыта через file://, а fetch
// по схеме file: браузер запрещает ещё до сети — скрипт подставляет
// http-адрес и перехватывает его сам, отдавая фикстуры.
const BASE = (typeof window !== 'undefined' && window.__API_BASE__) || ''

// Параметры запроса без пустых: `''`, null, undefined и false не отправляем,
// иначе сервер получил бы price_min='' и решил бы, что это фильтр.
const qs = (params) => {
  const p = Object.entries(params || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== '' && v !== false)
    .map(([k, v]) => [k, v === true ? '1' : String(v)])
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

async function req(method, path, body) {
  const r = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const d = (await r.json()).detail
      // FastAPI при 422 кладёт в detail список ошибок, а не строку
      if (d) msg = typeof d === 'string' ? d : JSON.stringify(d)
    } catch { /* тело не JSON — оставляем statusText */ }
    const err = new Error(msg || `HTTP ${r.status}`)
    // Код нужен страницам, чтобы отличить «ручки ещё нет» от настоящей
    // поломки: фронтенд раздаётся из frontend/dist сразу после сборки, а
    // бэкенд подхватывает изменения только с перезапуском, и в этом окне
    // новая вкладка в Киеве встречала владельца голым «Error: Not Found».
    err.status = r.status
    throw err
  }
  return r.json()
}

// Текст ошибки для человека. 404 — почти всегда не «нет такой записи», а
// сервер, который ещё не перезапущен после выкатки (см. выше).
export const errorText = (err) => {
  if (!err) return ''
  if (err.status === 404) return 'Сервер ще не перезапущений після викатки — ручки ще немає'
  if (err.status === 401) return 'Потрібен вхід: сервер закритий паролем (basic-auth)'
  if (err.status === 403) return 'Доступ лише для адміністратора'
  if (err.status === 409) return err.message || 'Зараз не можна: іде прогін або стоїть пауза'
  return err.message || String(err)
}

export const api = {
  health: () => req('GET', '/api/health'),
  summary: () => req('GET', '/api/summary'),
  listings: (params) => req('GET', '/api/listings' + qs(params)),
  listing: (id) => req('GET', `/api/listings/${id}`),
  favorite: (id, value) =>
    req('POST', `/api/listings/${id}/favorite`, value === undefined ? {} : { value }),
  // синхронный перевод одной карточки вне очереди (до 30 с)
  translate: (id) => req('POST', `/api/listings/${id}/translate`),
  // ручные правки: {osiedle?, condition?, note?}, null снимает правку
  manual: (id, patch) => req('POST', `/api/listings/${id}/manual`, patch),
  // «інша квартира» — вынести размещение из группы дублей
  detach: (id) => req('POST', `/api/listings/${id}/detach`),
  geo: () => req('GET', '/api/geo'),
  stats: (params) => req('GET', '/api/stats' + qs(params)),
  priceIndex: (params) => req('GET', '/api/price_index' + qs(params)),
  trends: (params) => req('GET', '/api/trends' + qs(params)),
  yieldTop: (params) => req('GET', '/api/rent/yield_top' + qs(params)),
  runs: (limit = 50) => req('GET', '/api/runs' + qs({ limit })),
  // kind и source шлём и в строке запроса, и в теле: контракт (docs/API.md)
  // называет их «параметрами», не уточняя где, — так ручка получит их при
  // любом из двух объявлений на сервере.
  scrape: (kind, source = 'all') =>
    req('POST', '/api/scrape' + qs({ kind, source }), { kind, source }),
  scrapeStop: () => req('POST', '/api/scrape/stop'),
  // hours=0 — до отмены. Сворачивает текущий прогон и не даёт стартовать плановым
  scrapePause: (hours) => req('POST', '/api/scrape/pause', { hours }),
  scrapeResume: () => req('POST', '/api/scrape/resume'),
  translateStatus: () => req('GET', '/api/translate/status'),
  translateRun: (limit) => req('POST', '/api/translate/run', { limit }),
  unknownValues: () => req('GET', '/api/translate/unknown_values'),
  // дубли + выгодность + доходность, в фоне
  recompute: () => req('POST', '/api/recompute'),
  settings: () => req('GET', '/api/settings'),
  settingsSave: (body) => req('POST', '/api/settings', body),
  jobs: () => req('GET', '/api/jobs'),
  exportUrl: (params, format) => BASE + '/api/export' + qs({ ...params, format }),
  // Картки контактів продавців/орендодавців: одна строка на продавца, с
  // числом его размещений и телефоном (если площадка его отдаёт)
  contacts: (params) => req('GET', '/api/contacts' + qs(params)),
  contactsExportUrl: (params, format) => BASE + '/api/contacts/export' + qs({ ...params, format }),
  // Кто вошёл и с какой ролью: viewer (рієлторка Юлія) не видит прогонов,
  // настроек и журнала — сервер на них отвечает 403, интерфейс их прячет
  me: () => req('GET', '/api/me'),
  // журнал действий пользователей, только admin
  activity: (params) => req('GET', '/api/activity' + qs(params)),
}

// Телефон в буфер обмена. navigator.clipboard есть только в безопасном
// контексте (https или localhost): по голому http с другого компьютера его
// нет, поэтому запасной путь — через выделение текста, как в старых браузерах.
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* пробуем запасной путь */ }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch { return false }
}

// ---------- форматирование ----------

// Неразрывный пробел между тысячами и перед валютой: обычный пробел браузер
// охотно переносит, и «780» с «000 zł» разъезжались по двум строкам.
const NBSP = ' '
const group = (n, d) => {
  const [int, frac] = Math.abs(n).toFixed(d).split('.')
  const g = int.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
  return (n < 0 ? '−' : '') + g + (frac ? ',' + frac : '')
}

export const fmtNum = (v, d = 0) =>
  (v == null || v === '' || isNaN(Number(v))) ? '—' : group(Number(v), d)
export const fmtPln = (v, d = 0) => v == null ? '—' : fmtNum(v, d) + NBSP + 'zł'
export const fmtUsd = (v) => v == null ? '—' : fmtNum(v) + NBSP + '$'
export const fmtEur = (v) => v == null ? '—' : fmtNum(v) + NBSP + '€'
export const fmtPct = (v, d = 1) => v == null ? '—' : fmtNum(v, d) + '%'

// Бэкенд отдаёт время с явным смещением («…T10:02:00+03:00», Киев). Строки
// без смещения считаем UTC — так хранит база. Показываем всегда по Киеву:
// владелец смотрит из Киева, а квартиры — во Вроцлаве, и «время сервера»
// без пояса читалось бы двояко.
const KYIV = 'Europe/Kyiv'
const parseDate = (s) => {
  if (!s) return null
  if (s instanceof Date) return isNaN(s) ? null : s
  const str = String(s)
  // «2026-09-10» без времени: new Date('2026-09-10Z') браузер не понимает
  if (/^\d{4}-\d\d-\d\d$/.test(str)) return new Date(str + 'T00:00:00Z')
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(str)
  const d = new Date(hasTz ? str : str + 'Z')
  return isNaN(d) ? null : d
}

export const fmtDate = (s) => {
  const d = parseDate(s)
  return d ? d.toLocaleDateString('uk-UA', {
    day: '2-digit', month: '2-digit', year: '2-digit', timeZone: KYIV,
  }) : '—'
}

export const fmtDateTime = (s, opts) => {
  const d = parseDate(s)
  return d ? d.toLocaleString('uk-UA', {
    timeZone: KYIV, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', ...(opts || {}),
  }) : '—'
}

// Сколько прошло: «3 хв тому», «2 год тому», «5 дн тому» — для отметок жизни
// прогона, где точное время менее важно, чем «он ещё жив?»
export const fmtAgo = (s) => {
  const d = parseDate(s)
  if (!d) return '—'
  const min = Math.round((Date.now() - d.getTime()) / 60000)
  if (min < 1) return 'щойно'
  if (min < 60) return `${min} хв тому`
  if (min < 48 * 60) return `${Math.round(min / 60)} год тому`
  return `${Math.round(min / 1440)} дн тому`
}

// Заглушка вместо секрета в «Налаштуваннях»: сервер не отдаёт наружу ключи
// API даже за паролем на вход, а присылает эти точки. Поле с ними нетронутым
// обратно не шлём — иначе ключ на сервере затёрся бы точками.
export const SECRET_MASK = '••••••••'
