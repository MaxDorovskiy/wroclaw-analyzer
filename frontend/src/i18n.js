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
