import React, { useEffect, useState } from 'react'
import { api, fmtNum } from '../api.js'
import Filters from '../components/Filters.jsx'
import ListingsTable from '../components/ListingsTable.jsx'
import Pager from '../components/Pager.jsx'
import ApiError from '../components/ApiError.jsx'

// Числовые параметры адреса. Из URLSearchParams всё приходит строками, а
// фильтры складываются как числа: page: "2" ломает листалку, а dupes: "0"
// в JS истинно — галочка не снималась бы.
const NUMERIC = new Set(['page', 'per_page', 'price_min', 'price_max', 'area_min', 'area_max',
  'sqm_min', 'sqm_max', 'build_year_min', 'build_year_max', 'floor_min', 'floor_max',
  'discount_min', 'yield_min', 'only_deals', 'dupes', 'favorites', 'first_seen_days', 'has_phone'])

function fromUrl(p) {
  const out = {}
  for (const [k, v] of Object.entries(p || {})) {
    if (k === 'id' || k === 'preset') continue   // открытая карточка и пресет «Вигідних» — не фильтры
    // Пустые значения пропускаем: адрес приходит и из памяти раздела, где у
    // незаполненного фильтра лежит undefined, — и такой «фильтр» затирал бы
    // пресет. Так выбор «чиє обране» молча возвращался к своему списку.
    if (v === undefined || v === null || v === '') continue
    out[k] = NUMERIC.has(k) ? Number(v) : v
  }
  return out
}

// Чип «4+» в фильтре — это НЕ значение для API: контракт ждёт `rooms` через
// запятую, и сервер, скорее всего, приводит каждое к числу. Раскрываем в
// перечисление, которое пройдёт через любой IN-фильтр.
const expandRooms = (s) => (s || '').split(',').filter(Boolean)
  .flatMap(r => r === '4+' ? ['4', '5', '6', '7', '8', '9', '10'] : [r]).join(',')

// offerType переопределяет пару sale/rent: разделу «Обране» нужен `all` —
// квартира на продажу и квартира в аренду там лежат одним списком.
export const toApiParams = (f, rent, offerType) => {
  const { preset, ...rest } = f
  return { ...rest, rooms: expandRooms(f.rooms), offer_type: offerType || (rent ? 'rent' : 'sale') }
}

const SORTS_SALE = [
  ['first_seen', 'нові в базі'], ['posted', 'за датою подачі'], ['discount', 'за знижкою'],
  ['price', 'за ціною'], ['price_sqm', 'за zł/м²'], ['area', 'за площею'],
  ['yield', 'за дохідністю'], ['price_drop', 'за зниженням ціни'],
]
const SORTS_RENT = SORTS_SALE.filter(([k]) => k !== 'discount' && k !== 'yield')

// rent — той самий каталог для оренди: offer_type=rent, ціна = ставка/міс,
// без знижки та дохідності.
export default function Catalog({ onOpen, preset, urlParams, onParams, geo, rent = false,
                                  offerType, extraSorts, toolbar, sel, onSel }) {
  const mixed = offerType === 'all'
  // Порядок важен: умолчания → пресет раздела → адрес. Адрес главнее всего,
  // иначе открытая ссылка показывала бы не то, что в ней записано.
  const [f, setF] = useState({
    sort: 'first_seen', order: 'desc', page: 1, per_page: 50,
    ...(preset || {}), ...fromUrl(urlParams),
  })
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      api.listings(toApiParams(f, rent, offerType))
        .then(d => { setData(d); setErr(null) })
        .catch(e => { setErr(e); setData({ items: [], total: 0 }) })
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [f, rent])

  // Фильтры — в адрес, с той же задержкой: набор в поле поиска не должен
  // переписывать адрес на каждую букву.
  useEffect(() => {
    if (!onParams) return undefined
    const t = setTimeout(() => onParams(f), 250)
    return () => clearTimeout(t)
  }, [f])

  // Ответ сервера главнее фильтров: per_page он урезает до 200, и считать
  // листалку по своему числу значило бы обещать страницы, которых нет.
  const per = data.per_page || f.per_page || 50
  const pager = (top) => (
    <Pager top={top} page={f.page || 1} perPage={per} total={data.total}
      onPage={n => setF({ ...f, page: n })}
      onPerPage={(v, n) => setF({ ...f, per_page: v, page: n })} />
  )
  const exportParams = toApiParams(f, rent, offerType)
  const sorts = [...(extraSorts || []), ...(rent ? SORTS_RENT : SORTS_SALE)]

  return (
    <>
      {toolbar}
      <Filters value={f} onChange={setF} geo={geo} rent={rent} />
      <div className="panel">
        <div className="row" style={{ marginBottom: 8 }}>
          <h3 style={{ margin: 0 }}>
            {loading ? <span className="spin" /> : null}
            Знайдено: {fmtNum(data.total)}
          </h3>
          <span style={{ flex: 1 }} />
          <label className="chk">сортування:
            <select value={f.sort} onChange={e => setF({ ...f, sort: e.target.value, page: 1 })}>
              {sorts.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={f.order} onChange={e => setF({ ...f, order: e.target.value, page: 1 })}>
              <option value="desc">↓ спадання</option>
              <option value="asc">↑ зростання</option>
            </select>
          </label>
          <a className="btn ghost" href={api.exportUrl(exportParams, 'csv')} title="Вивантажити поточну вибірку">Експорт CSV</a>
          <a className="btn ghost" href={api.exportUrl(exportParams, 'xlsx')}>XLSX</a>
        </div>
        <ApiError err={err} />
        {pager(true)}
        {/* Таблица гаснет, пока грузится: заголовок сортировки переключается
            мгновенно, а строки приходят с сервера — без этого на экране стоит
            СТАРЫЙ порядок под новой стрелкой (киевские грабли 06.09.2026) */}
        <div className="wrap" style={{ opacity: loading ? 0.45 : 1, transition: 'opacity .15s' }}>
          <ListingsTable items={data.items} onOpen={onOpen} rent={rent} mixed={mixed}
            sel={sel} onSel={onSel} sort={f.sort} order={f.order} loading={loading}
            onSort={(s, o) => setF({ ...f, sort: s, order: o, page: 1 })} />
        </div>
        {pager(false)}
      </div>
    </>
  )
}
