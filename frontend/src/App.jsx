import React, { useEffect, useState } from 'react'
import Catalog from './pages/Catalog.jsx'
import Deals from './pages/Deals.jsx'
import Rent from './pages/Rent.jsx'
import Contacts from './pages/Contacts.jsx'
import Favorites from './pages/Favorites.jsx'
import Stats from './pages/Stats.jsx'
import Runs from './pages/Runs.jsx'
import Settings from './pages/Settings.jsx'
import Journal from './pages/Journal.jsx'
import Card from './components/Card.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import LangSwitch from './components/LangSwitch.jsx'
import { api, fmtNum, fmtDateTime } from './api.js'
import { LangContext, readLang, writeLang } from './i18n.js'

const TABS = [
  ['catalog', 'Каталог'],
  ['deals', 'Вигідні'],
  ['rent', 'Оренда'],
  ['favorites', '★ Обране'],
  ['contacts', 'Контакти'],
  ['stats', 'Статистика'],
  ['runs', 'Прогони'],
  ['journal', 'Журнал'],
  ['settings', 'Налаштування'],
]
const TAB_IDS = TABS.map(([id]) => id)
// Разделы владельца. viewer (рієлторка Юлія) их вкладок не видит; по прямой
// ссылке «Журнал» и «Налаштування» отвечают «лише для адміністратора», а
// «Прогони» открываются в режиме чтения (GET /api/runs ей разрешён, спрятаны
// только кнопки). Сервер на закрытые ручки отвечает 403 и без нас — здесь
// лишь чтобы не показывать мёртвые кнопки.
const ADMIN_TABS = new Set(['journal', 'runs', 'settings'])
const ADMIN_ONLY_PAGES = new Set(['journal', 'settings'])

// ---------- адресация ----------
// Хэш, а не «настоящие» пути: сервер отдаёт статику из frontend/dist, и путь
// вида /catalog/123 он бы не нашёл. Хэш обходится без правок на сервере и
// работает даже с file:// (так интерфейс проверяет scripts/ui_check.py).
// Формат: #/<раздел>?<фильтры>, открытая карточка — параметр id.
// #/listing/<id> — короткая ссылка на карточку (раздел подставляется сам).
function parseHash() {
  const raw = (window.location.hash || '').replace(/^#\/?/, '')
  const qi = raw.indexOf('?')
  const path = qi < 0 ? raw : raw.slice(0, qi)
  const params = Object.fromEntries(new URLSearchParams(qi < 0 ? '' : raw.slice(qi + 1)))
  const seg = path.split('/').filter(Boolean)
  if (seg[0] === 'listing' && seg[1]) return { tab: 'catalog', params: { id: seg[1] } }
  return { tab: TAB_IDS.includes(seg[0]) ? seg[0] : 'catalog', params }
}

function buildHash(tab, params) {
  const q = new URLSearchParams(
    Object.entries(params || {})
      .filter(([, v]) => v !== '' && v != null && v !== false)
      .map(([k, v]) => [k, String(v)])).toString()
  return '#/' + tab + (q ? '?' + q : '')
}

export default function App() {
  const first = parseHash()
  const [tab, setTab] = useState(first.tab)
  // Параметры раздела живут ЗДЕСЬ, а не только внутри страницы: их надо и
  // писать в адрес, и восстанавливать из него при открытии ссылки.
  const [params, setParams] = useState(first.params)
  const [openId, setOpenId] = useState(first.params.id ? Number(first.params.id) : null)
  // Переход в другой раздел с готовым фильтром (клик по продавцу, по осиедле
  // в статистике). `at` попадает в key страницы, чтобы она перемонтировалась
  // и взяла новый пресет, даже если раздел тот же.
  const [jump, setJump] = useState(null)
  const [summary, setSummary] = useState(null)
  const [geo, setGeo] = useState(null)
  const [me, setMe] = useState(null)
  // Сколько раз адрес меняли СНАРУЖИ (вставленная ссылка, «назад»). Число
  // входит в key страницы: без перемонтирования вставленная ссылка на том же
  // разделе молча ничего не меняла бы — фильтры уже стоят в состоянии.
  const [extNav, setExtNav] = useState(0)
  const [lang, setLangState] = useState(readLang)
  const setLang = (v) => { setLangState(v); writeLang(v) }

  // push — новая запись в истории (смена раздела, карточка: «назад» должно
  // возвращать оттуда); replace — правка текущей (фильтры, страница), иначе
  // история забивалась бы по записи на каждую букву в поиске.
  const writeUrl = (t, p, openIdVal, push) => {
    const all = { ...(p || {}) }
    if (openIdVal) all.id = openIdVal; else delete all.id
    const h = buildHash(t, all)
    if (h === window.location.hash) return
    if (push) window.history.pushState(null, '', h)
    else window.history.replaceState(null, '', h)
  }

  useEffect(() => {
    const onPop = () => {
      const r = parseHash()
      setTab(r.tab); setJump(null); setParams(r.params)
      setOpenId(r.params.id ? Number(r.params.id) : null)
      setExtNav(n => n + 1)
    }
    window.addEventListener('popstate', onPop)
    window.addEventListener('hashchange', onPop)
    return () => {
      window.removeEventListener('popstate', onPop)
      window.removeEventListener('hashchange', onPop)
    }
  }, [])
  useEffect(() => { writeUrl(tab, params, openId, false) }, [])

  const goTo = (t, preset) => {
    setOpenId(null)
    setJump({ preset, at: Date.now() })
    setParams(preset || {})
    setTab(t)
    writeUrl(t, preset || {}, null, true)
  }
  const openTab = (t) => {
    setJump(null); setParams({}); setTab(t)
    writeUrl(t, {}, null, true)
  }
  const onParams = (p) => { setParams(p); writeUrl(tab, p, openId, false) }
  const openCard = (id) => { setOpenId(id); writeUrl(tab, params, id, true) }
  const closeCard = () => { setOpenId(null); writeUrl(tab, params, null, true) }

  useEffect(() => {
    let stop = false
    const tick = async () => {
      try { const s = await api.summary(); if (!stop) setSummary(s) }
      catch { /* бэкенд ещё поднимается */ }
    }
    tick()
    const t = setInterval(tick, 30000)
    return () => { stop = true; clearInterval(t) }
  }, [])
  // Справочник дзельниц и осиедле — один на всё приложение: нужен фильтрам,
  // карточке (ручная правка осиедле) и контактам (перевод названий).
  useEffect(() => { api.geo().then(setGeo).catch(() => setGeo({ districts: [] })) }, [])
  // Нет ответа (старый сервер без /api/me или он ещё поднимается) — считаем
  // владельцем: до появления ролей других пользователей не было, а прятать
  // от владельца «Налаштування» из-за 404 после выкатки — та самая ловушка.
  // Ограничение здесь только косметическое, настоящее — 403 на сервере.
  useEffect(() => { api.me().then(setMe).catch(() => setMe(null)) }, [])

  const Page = {
    catalog: Catalog, deals: Deals, rent: Rent, favorites: Favorites, contacts: Contacts,
    stats: Stats, runs: Runs, journal: Journal, settings: Settings,
  }[tab]
  const isViewer = me?.role === 'viewer'
  const tabs = isViewer ? TABS.filter(([id]) => !ADMIN_TABS.has(id)) : TABS
  const sale = summary?.sale, fx = summary?.fx
  const lastRun = summary?.last_runs?.sale?.finished_at

  return (
    <LangContext.Provider value={{ lang, setLang }}>
      <div className="topbar">
        <h1>🏙️ Wrocław Analyzer</h1>
        <div className="tabs">
          {tabs.map(([id, name]) => (
            <button key={id} className={'tab' + (tab === id ? ' active' : '')}
              onClick={() => openTab(id)}>{name}</button>
          ))}
        </div>
        <div className="status">
          {summary?.scrape_running && <span><span className="spin" />іде прогін…</span>}
          {/* Забытая пауза = каталог тихо старіє, тому вона видна з будь-якого
              розділу, а не лише в «Прогонах» */}
          {summary?.paused_until && (
            <span className="badge drop" title="Прогони на паузі — нові оголошення не приходять. Зняти можна в «Прогонах»">
              {/* hours=0 — пауза до скасування; чем сервер её обозначит, контракт
                  не говорит, поэтому всё, что не дата, читаем как «безстроково» */}
              ⏸ Пауза {fmtDateTime(summary.paused_until, { year: undefined }) === '—'
                ? 'до скасування' : 'до ' + fmtDateTime(summary.paused_until, { year: undefined })}
            </span>
          )}
          {sale && <span title="Активних оголошень продажу · нових за добу">
            активних <b>{fmtNum(sale.active)}</b> · за добу <b>+{fmtNum(sale.new_24h)}</b>
          </span>}
          {sale?.median_sqm != null && <span title="Медіана ціни за м², продаж">медіана <b>{fmtNum(sale.median_sqm)} zł/м²</b></span>}
          {fx?.USD && <span title={'Курс НБП ' + (fx.date || '')}>$ {fmtNum(fx.USD, 2)} · € {fmtNum(fx.EUR, 2)} zł</span>}
          {lastRun && <span title="Кінець останнього прогону продажу">оновлено {fmtDateTime(lastRun, { year: undefined })}</span>}
          <LangSwitch />
          {me?.user && (
            <span className="small" title={isViewer
              ? 'Роль: перегляд — прогони, налаштування і журнал недоступні'
              : 'Роль: адміністратор'}>
              👤 <b>{me.user}</b>{isViewer ? ' · перегляд' : ''}
            </span>
          )}
        </div>
      </div>
      <div className="page">
        <ErrorBoundary key={tab}>
          {isViewer && ADMIN_ONLY_PAGES.has(tab) ? (
            <div className="panel admin-only">
              <h3>Лише для адміністратора</h3>
              <p className="muted">
                Цей розділ доступний лише власнику системи. Ви увійшли як <b>{me.user}</b> (перегляд).
              </p>
              <button className="btn" onClick={() => openTab('catalog')}>До каталогу</button>
            </div>
          ) : (
            <Page key={(jump ? 'j' + jump.at : tab) + '#' + extNav}
              onOpen={openCard} summary={summary} geo={geo} goTo={goTo} me={me}
              urlParams={params} onParams={onParams} />
          )}
        </ErrorBoundary>
      </div>
      {openId && <Card id={openId} onOpen={openCard} onClose={closeCard} geo={geo} goTo={goTo} />}
    </LangContext.Provider>
  )
}
