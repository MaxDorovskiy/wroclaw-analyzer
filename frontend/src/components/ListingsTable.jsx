import React, { useState } from 'react'
import { api, fmtNum, fmtPln, fmtUsd, fmtDate } from '../api.js'
import { useLang, pickBi, tr, dealTitle, yieldTitle, roomsLabel } from '../i18n.js'
import Bi from './Bi.jsx'

function FavStar({ l }) {
  const [fav, setFav] = useState(!!l.is_favorite)
  return (
    <button type="button" className={'favstar' + (fav ? ' on' : '')}
      title={fav ? 'В обраних' : 'До обраних'}
      onClick={(e) => {
        e.stopPropagation()
        const next = !fav
        setFav(next); l.is_favorite = next
        api.favorite(l.id, next).catch(() => { setFav(!next); l.is_favorite = !next })
      }}>
      {fav ? '★' : '☆'}
    </button>
  )
}

// направление по умолчанию при первом клике на столбец: дешёвое, выгодное и
// свежее — наверх
const DEFAULT_ORDER = {
  discount: 'desc', price: 'asc', price_sqm: 'asc', posted: 'desc',
  first_seen: 'desc', area: 'desc', yield: 'desc', price_drop: 'asc',
}

// площадь: 60 → «60», 45.5 → «45,5»
const fmtArea = (a) => a == null ? '—' : fmtNum(a, Number.isInteger(Number(a)) ? 0 : 1)

// Осиедле · дзельниця одной строкой, а под ней оригинал (в режиме «обидва»).
// Два <Bi> подряд не годятся: у каждого своя вторая строка, и выходило
// «Ґай / Gaj / · Кшики / Krzyki» лесенкой.
function GeoCell({ l }) {
  const { lang } = useLang()
  const o = pickBi(lang, l.osiedle, l.osiedle_uk)
  const d = pickBi(lang, l.district, l.district_uk)
  const main = [o.main, d.main].filter(Boolean).join(' · ')
  const sub = [o.sub, d.sub].filter(Boolean).join(' · ')
  if (!main) return <span className="muted">—</span>
  return (
    <span className="bi">
      <span className="bi-main">{main}</span>
      {sub && <span className="bi-sub">{sub}</span>}
    </span>
  )
}

// rent — каталог оренди: ціна це ставка на місяць, колонок знижки та
// дохідності немає. mixed — продаж і оренда в одному списку («Обране»): тоді
// «/міс» і czynsz беремо по кожному рядку окремо, інакше ставка оренди
// виглядала б як ціна продажу.
export default function ListingsTable({ items, onOpen, rent = false, mixed = false, sort, order, onSort,
                                        sel, onSel }) {
  // Вибір галочками — для PDF-підбірки клієнту. Окремо від зірочки: обране
  // живе довго, а підбірка збирається під одного клієнта і тут же скидається.
  const picked = new Set(sel || [])
  const pageIds = (items || []).map(x => x.id)
  const allPicked = pageIds.length > 0 && pageIds.every(id => picked.has(id))
  const clickSort = (field) => {
    const dir = field === sort ? (order === 'asc' ? 'desc' : 'asc') : (DEFAULT_ORDER[field] || 'desc')
    onSort(field, dir)
  }
  const Th = ({ field, children, num, title }) => (
    <th className={(num ? 'num' : '') + (onSort && field ? ' sortable' : '')}
      onClick={onSort && field ? () => clickSort(field) : undefined}
      title={title || (field ? 'Сортувати' : undefined)}>
      {children}{onSort && field === sort ? (order === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  )
  const cols = (rent ? 12 : 14) + (onSel ? 1 : 0)

  return (
    <table className="grid">
      <thead>
        <tr>
          {onSel && (
            <th style={{ width: 26 }} title="Вибрати всі на сторінці для презентації">
              <input type="checkbox" checked={allPicked}
                onChange={() => onSel(pageIds, !allPicked)} />
            </th>
          )}
          <th></th>
          <th>Оголошення</th>
          <th>Осиедле · дзельниця</th>
          <Th num>Кімн.</Th>
          <Th field="area" num>м²</Th>
          <Th field="price" num>{rent ? 'Ставка' : 'Ціна'}</Th>
          <Th field="price_sqm" num>zł/м²</Th>
          {!rent && <Th field="discount" num title="Знижка до медіани zł/м² схожих квартир">Знижка</Th>}
          {!rent && <Th field="yield" num title="Валова дохідність від оренди, % річних">Дохідність</Th>}
          <th>Продавець</th>
          <th>Джерело</th>
          <Th field="first_seen" num title="Днів у продажу (з першої появи в базі)">Днів</Th>
          <Th field="price_drop" num>Зміни ціни</Th>
          <Th field="posted" num>Подано</Th>
        </tr>
      </thead>
      <tbody>
        {(items || []).map(l => {
          const rowRent = mixed ? l.offer_type === 'rent' : rent
          return (
          <tr key={l.id} className="clickable" onClick={() => onOpen(l.id)}>
            {onSel && (
              <td style={{ width: 26 }} onClick={e => e.stopPropagation()}>
                <input type="checkbox" checked={picked.has(l.id)} onChange={() => onSel([l.id])}
                  title="Додати до презентації" />
              </td>
            )}
            <td style={{ width: 28 }}><FavStar l={l} /></td>
            <td style={{ minWidth: 260 }}>
              <Bi pl={l.title_pl} uk={l.title_uk} strong />
              {l.street && <div className="muted small">{l.street}</div>}
              <div className="badges">
                {mixed && <span className={'badge ' + (rowRent ? 'owner' : 'gray')}>{rowRent ? 'оренда' : 'продаж'}</span>}
                <span className="badge gray">{tr('source', l.source)}</span>
                {l.group_size > 1 && (
                  <span className="badge gray" title="Та сама квартира розміщена кілька разів — усі розміщення видно в картці">
                    ще {l.group_size - 1} розміщ.
                  </span>
                )}
                {l.no_commission && <span className="badge deal">без комісії</span>}
                {l.condition && l.condition !== 'unknown' && (
                  <span className="badge gray" title={l.condition_src === 'manual' ? 'Стан виправлено вручну' : 'Стан за характеристиками й текстом оголошення'}>
                    {l.condition_uk || tr('condition', l.condition)}{l.condition_src === 'manual' ? ' ✎' : ''}
                  </span>
                )}
                {l.market === 'primary' && <span className="badge gray">первинний</span>}
                {l.build_year && <span className="badge gray">{l.build_year}</span>}
                {l.is_active === false && <span className="badge drop">знято</span>}
              </div>
            </td>
            <td><GeoCell l={l} /></td>
            <td className="num">{roomsLabel(l.rooms)}</td>
            <td className="num">{fmtArea(l.area)}</td>
            <td className="num">
              <b>{fmtPln(l.price_pln)}{rowRent ? '/міс' : ''}</b>
              {rowRent
                ? (l.czynsz_pln ? <div className="muted" style={{ fontSize: 10 }} title="Експлуатаційний платіж (czynsz), понад ставку">+ {fmtPln(l.czynsz_pln)} czynsz</div> : null)
                : <div className="muted" style={{ fontSize: 10 }} title="За курсом НБП на день останнього перегляду">{fmtUsd(l.price_usd)}</div>}
            </td>
            <td className="num">{fmtNum(l.price_per_m2)}</td>
            {!rent && (
              <td className="num">
                {l.discount_pct != null && l.discount_pct >= 3
                  ? <span className={'badge ' + (l.deal_thin_base ? 'gray' : 'deal')} title={dealTitle(l)}>
                      −{fmtNum(l.discount_pct, 1)}%{l.deal_thin_base ? ' ?' : ''}
                    </span>
                  /* знак явный: «+2,1%» — ДОРОЖЧЕ медіани, «−1,5%» — трохи дешевше;
                     без знака «2,1%» читалось як маленька знижка */
                  : <span className="muted" title={dealTitle(l) + (l.discount_pct < 0 ? '; дорожче за медіану' : '')}>
                      {l.discount_pct == null ? '—'
                        : (l.discount_pct < 0 ? '+' : '−') + fmtNum(Math.abs(l.discount_pct), 1) + '%'}
                    </span>}
              </td>
            )}
            {!rent && (
              <td className="num">
                {l.yield_pct != null
                  ? <>
                      <span className={'badge ' + (l.yield_pct >= 6 ? 'deal' : 'gray')} title={yieldTitle(l)}>
                        {fmtNum(l.yield_pct, 1)}%
                      </span>
                      <div className="muted" style={{ fontSize: 10 }}>{fmtPln(l.rent_median_pln)}/міс</div>
                    </>
                  : <span className="muted">—</span>}
              </td>
            )}
            <td>
              {l.seller_type === 'private'
                ? <span className="badge owner">власник</span>
                : <span className="muted small">{tr('seller', l.seller_type)}</span>}
              {l.seller_name && <div className="muted" style={{ fontSize: 11 }}>{l.seller_name}</div>}
            </td>
            <td style={{ whiteSpace: 'nowrap' }}>
              {l.url
                ? <a href={l.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()}
                    title="Відкрити оголошення на сайті">{tr('source', l.source)} ↗</a>
                : tr('source', l.source)}
            </td>
            <td className="num muted">{l.days_on_market ?? '—'}</td>
            <td className="num">
              {l.price_drop_pct != null && l.price_drop_pct < 0
                ? <span className="badge drop" title="Остання зміна ціни">▼ {fmtNum(Math.abs(l.price_drop_pct), 1)}%</span>
                : l.price_drop_pct != null && l.price_drop_pct > 0
                  ? <span className="muted">▲ {fmtNum(l.price_drop_pct, 1)}%</span>
                  : <span className="muted">—</span>}
              {l.price_changes > 0 && <span className="muted" style={{ fontSize: 10 }}> ×{l.price_changes}</span>}
            </td>
            <td className="num muted">{fmtDate(l.posted_at || l.first_seen)}</td>
          </tr>
        )})}
        {!(items || []).length && (
          <tr><td colSpan={cols} className="muted" style={{ textAlign: 'center', padding: 24 }}>
            Нічого не знайдено. Якщо база порожня — запустіть прогін у розділі «Прогони»
          </td></tr>
        )}
      </tbody>
    </table>
  )
}
