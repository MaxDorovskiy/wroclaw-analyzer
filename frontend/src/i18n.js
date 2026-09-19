// Язык интерфейса — украинский, содержимое объявлений — двуязычное
// (оригинал PL и перевод UK). Здесь: режим показа (контекст), словари
// украинских подписей для кодов из API и подсказки к расчётным колонкам.
// JSX здесь нет намеренно: файл .js, esbuild его как JSX не разбирает.
import { createContext, useContext } from 'react'
import { fmtNum, fmtPln } from './api.js'

export const LANG_KEY = 'wro_lang'
export const LANG_MODES = [['pl', 'оригінал (PL)'], ['uk', 'переклад (UK)'], ['both', 'обидва']]

// localStorage в приватном окне и при заблокированных данных сайта бросает
// исключение уже на чтении — поэтому try/catch, а не проверка на null.
export const readLang = () => {
  try {
    const v = localStorage.getItem(LANG_KEY)
    return ['pl', 'uk', 'both'].includes(v) ? v : 'both'
  } catch { return 'both' }
}
export const writeLang = (v) => {
  try { localStorage.setItem(LANG_KEY, v) } catch { /* без памяти — просто не запомним */ }
}

export const LangContext = createContext({ lang: 'both', setLang: () => {} })
export const useLang = () => useContext(LangContext)

// Пара «оригінал/переклад» → что показать в текущем режиме.
// main — основная строка; sub — вторая строка мелким серым (только в режиме
// «обидва»); untranslated — перевода нет, показан оригинал с пометкой.
export function pickBi(lang, pl, uk) {
  const hasUk = !!(uk && String(uk).trim())
  const hasPl = !!(pl && String(pl).trim())
  if (lang === 'pl') return { main: hasPl ? pl : (uk || ''), sub: null, untranslated: false }
  if (lang === 'uk') return { main: hasUk ? uk : (pl || ''), sub: null, untranslated: !hasUk && hasPl }
  return {
    main: hasUk ? uk : (pl || ''),
    sub: hasUk && hasPl && pl !== uk ? pl : null,
    untranslated: !hasUk && hasPl,
  }
}

// Одной строкой: «Кшики (Krzyki)» в режиме «обидва», иначе одно из двух.
export const biText = (lang, pl, uk) => {
  const p = pickBi(lang, pl, uk)
  return p.sub ? `${p.main} (${p.sub})` : p.main
}

// Украинские подписи для кодов. Коды в API английские (renovated, agency),
// поэтому режим «оригінал» их не касается: код — не польский текст.
export const T = {
  condition: {
    developer_bare: 'стан від забудовника',
    to_renovate: 'під ремонт',
    to_refresh: 'під освіження',
    renovated: 'після ремонту',
    unknown: 'невідомо',
  },
  market: { primary: 'первинний', secondary: 'вторинний' },
  seller: { private: 'власник', agency: 'агенція', developer: 'забудовник' },
  source: { otodom: 'Otodom', olx: 'OLX' },
  // уровни пула для выгодности и доходности (docs/ARCHITECTURE.md §6-7)
  level: {
    osiedle_rooms: 'осиедле × кімнати',
    osiedle: 'осиедле',
    district_rooms: 'дзельниці × кімнати',
    district: 'дзельниці',
    city_rooms: 'місту × кімнати',
    city: 'місту',
  },
  runStatus: { running: 'іде', done: 'завершено', failed: 'збій', stopped: 'зупинено' },
  runKind: { sale: 'продаж', rent: 'оренда', all: 'усе' },
  provider: {
    ollama: 'Ollama (локальна модель)',
    anthropic: 'Anthropic (Claude)',
    google: 'Google Translate',
    deepl: 'DeepL',
    none: 'без перекладу',
  },
  fetchMode: { httpx: 'httpx (швидко, без браузера)', browser: 'браузер (Playwright)' },
  onOff: { 1: 'увімкнено', 0: 'вимкнено' },
}

export const tr = (dict, code) =>
  (code == null || code === '') ? '—' : ((T[dict] || {})[code] || String(code))

// Структурное поле с парой `key`/`key_uk`: перевод берём из ответа, а если
// сервер его не дал — из словаря выше; в режиме «оригінал» — сам код/PL.
export const fieldText = (lang, row, key, dict) => {
  if (!row) return '—'
  const pl = row[key]
  if (pl == null || pl === '') return '—'
  const uk = row[key + '_uk'] || (dict ? (T[dict] || {})[pl] : null) || null
  if (lang === 'pl') return String(pl)
  return uk || String(pl)
}

// Комнаты: чип «4+» в фильтре и «4+» в таблице
export const roomsLabel = (r) => r == null ? '—' : (r >= 4 ? '4+' : String(r))

// Поверх по-польски: 0 = parter, у нас это первый этаж. В данных так и
// лежит (docs/ARCHITECTURE.md §2), пересчитывать нельзя — это ключ дублей.
export const FLOOR_HINT = 'Нумерація польська: партер (0) = наш 1-й поверх'
export const floorText = (l) => {
  if (!l || l.floor == null) return l && l.floors_total ? `— / ${l.floors_total}` : '—'
  const f = l.floor === 0 ? 'партер' : String(l.floor)
  return l.floors_total ? `${f} / ${l.floors_total}` : f
}

// Подпись знижки: с чем сравнили и сколько таких нашлось. Без неё числу
// верить нельзя — оно выведено из ЧУЖИХ объявлений.
export const dealTitle = (l) => {
  if (!l || l.discount_pct == null) return ''
  const lvl = T.level[l.baseline_level] || l.baseline_level || ''
  return `медіана ${fmtNum(l.baseline_sqm)} zł/м² по ${lvl}, за ${l.baseline_count ?? '?'} схожими`
    + (l.deal_thin_base ? '; база тонка (менше 10) — знижка в межах похибки' : '')
}

// Подпись дохідності: откуда ставка. Валовая (ставка × 12 / вкладення), у
// «стану від забудовника» и «під ремонт» во вкладення входит и оздоблення.
export const yieldTitle = (l) => {
  if (!l || l.yield_pct == null) return ''
  const lvl = T.level[l.rent_baseline_level] || l.rent_baseline_level || ''
  const parts = [
    `очікувана оренда ${fmtPln(l.rent_median_pln)}/міс за медіаною по ${lvl}`
      + (l.rent_baseline_count ? ` (${l.rent_baseline_count} оголош.)` : ''),
    'валова: ставка × 12 / вкладення',
  ]
  if (l.condition === 'developer_bare' || l.condition === 'to_renovate') {
    parts.push('у вкладеннях ціна ПЛЮС оздоблення')
  }
  return parts.join('; ')
}

// ---------- журнал дій ----------
// Подписи действий — запасные: сервер присылает action_uk, но фильтр «дія»
// в журнале строится до первого ответа и берёт названия отсюда.
T.action = {
  view_card: 'відкрив(ла) картку',
  search: 'пошук у каталозі',
  favorite: 'обране',
  manual: 'ручна правка',
  detach: "від'єднання дубля",
  translate: 'переклад',
  export: 'експорт',
  contacts: 'контакти',
  presentation: 'презентація PDF',
  other: 'інше',
}

const SORT_UK = {
  first_seen: 'нові в базі', posted: 'дата подачі', discount: 'знижка', price: 'ціна',
  price_sqm: 'zł/м²', area: 'площа', yield: 'дохідність', price_drop: 'зниження ціни',
  active_total: 'активні', last_seen: 'останній перегляд', listings_rent: 'оренда', listings_sale: 'продаж',
}

// «4,5,6,7,8,9,10» — это чип «4+», раскрытый каталогом для API (Catalog.expandRooms);
// в журнале сворачиваем обратно, иначе строка нечитаема
const PLUS = ['4', '5', '6', '7', '8', '9', '10']
const collapseRooms = (v) => {
  const set = new Set(String(v).split(',').filter(Boolean))
  if (PLUS.every(r => set.has(r))) { PLUS.forEach(r => set.delete(r)); set.add('4+') }
  return Array.from(set).join('/')
}
const list = (v) => String(v).split(',').filter(Boolean).join('/')

// Расшифровка строки запроса в журнале: «оренда · 2 кімн. · ціна до 3 000 ·
// осиедле Gaj». Ключи — параметры /api/listings и /api/contacts; незнакомый
// ключ остаётся как есть, чтобы новый фильтр не пропал из журнала молча.
const Q = {
  offer_type: v => v === 'rent' ? 'оренда' : v === 'sale' ? 'продаж' : v === 'all' ? 'продаж + оренда' : `тип ${v}`,
  rooms: v => `${collapseRooms(v)} кімн.`,
  price_min: v => `ціна від ${fmtNum(v)}`, price_max: v => `ціна до ${fmtNum(v)}`,
  area_min: v => `від ${v} м²`, area_max: v => `до ${v} м²`,
  sqm_min: v => `від ${fmtNum(v)} zł/м²`, sqm_max: v => `до ${fmtNum(v)} zł/м²`,
  district: v => `дзельниця ${list(v)}`, osiedle: v => `осиедле ${list(v)}`,
  market: v => `ринок ${T.market[v] || v}`,
  condition: v => `стан ${String(v).split(',').map(c => T.condition[c] || c).join('/')}`,
  source: v => `джерело ${T.source[v] || v}`,
  seller_type: v => `продавець ${T.seller[v] || v}`,
  build_year_min: v => `рік від ${v}`, build_year_max: v => `рік до ${v}`,
  floor_min: v => `поверх від ${v}`, floor_max: v => `поверх до ${v}`,
  only_deals: () => 'лише вигідні', discount_min: v => `знижка ≥ ${v}%`, yield_min: v => `дохідність ≥ ${v}%`,
  favorites: () => 'обрані', dupes: () => 'усі розміщення', has_phone: () => 'є телефон',
  active: v => String(v) === '0' ? 'активні + зняті' : 'лише активні',
  q: v => `пошук «${v}»`, seller_key: v => `продавець ${v}`, first_seen_days: v => `нові за ${v} дн`,
  sort: v => `сортування: ${SORT_UK[v] || v}`, order: () => null, per_page: () => null, limit: () => null,
  page: v => String(v) === '1' ? null : `стор. ${v}`, format: v => `формат ${String(v).toUpperCase()}`,
  level: v => `рівень: ${T.level[v] || v}`, period: v => `період ${v}`, weeks: v => `${v} тижнів`,
  days: v => `${v} дн`, user: v => `користувач ${v}`, action: v => `дія ${T.action[v] || v}`,
}
export function describeQuery(query, path) {
  if (!query) return ''
  let sp
  try { sp = new URLSearchParams(query) } catch { return String(query) }
  const parts = []
  for (const [k, v] of sp.entries()) {
    const fn = Q[k]
    const text = fn ? fn(v) : `${k}=${v}`
    if (text) parts.push(text)
  }
  const prefix = path && path.includes('/contacts') ? 'контакти' : ''
  return [prefix, ...parts].filter(Boolean).join(' · ')
}

// «1 дія», «3 дії», «42 дій»
export const actionsWord = (n) => {
  const m10 = n % 10, m100 = n % 100
  if (m10 === 1 && m100 !== 11) return 'дія'
  if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return 'дії'
  return 'дій'
}
