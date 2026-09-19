import React, { useEffect, useState } from 'react'
import { api, fmtNum, fmtPln } from '../api.js'
import { useLang, biText, roomsLabel } from '../i18n.js'
import Catalog from './Catalog.jsx'
import ApiError from '../components/ApiError.jsx'

// Топ осиедле для покупки під здачу: медіана ставки проти медіани ціни
// купівлі в тому ж місці (rent_analytics.rc_yield_top).
function YieldTop({ goTo }) {
  const { lang } = useLang()
  const [p, setP] = useState({ level: 'osiedle', rooms: '' })
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    setErr(null)
    api.yieldTop(p).then(d => setRows(d.rows || [])).catch(e => { setErr(e); setRows([]) })
  }, [p])
  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Топ за дохідністю: де купувати під оренду</h3>
        <span style={{ flex: 1 }} />
        <select value={p.level} onChange={e => setP({ ...p, level: e.target.value })}>
          <option value="osiedle">по осиедле</option>
          <option value="district">по дзельницях</option>
        </select>
        <select value={p.rooms} onChange={e => setP({ ...p, rooms: e.target.value })}>
          <option value="">кімнати: усі</option>
          {['1', '2', '3', '4'].map(r => <option key={r} value={r}>{r === '4' ? '4+' : r}</option>)}
        </select>
      </div>
      <ApiError err={err} />
      {rows === null ? <p className="muted"><span className="spin" />Рахуємо…</p> : (
        <div className="wrap">
          <table className="grid">
            <thead><tr>
              <th>Місце</th><th className="num">Кімн.</th>
              <th className="num" title="Медіана ставки оренди на місяць">Ставка</th>
              <th className="num" title="Ставка за м² на місяць">zł/м²/міс</th>
              <th className="num" title="Медіана ціни купівлі за м² там само">Купівля zł/м²</th>
              <th className="num" title="Валова: ставка × 12 / ціна">Дохідність</th>
              <th className="num" title="Оголошень оренди / продажу в базі">n оренда / продаж</th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={goTo ? 'clickable' : ''}
                  title="Показати квартири на продаж у цьому місці"
                  onClick={goTo ? () => goTo('catalog', {
                    [p.level === 'district' ? 'district' : 'osiedle']: r.name,
                    rooms: r.rooms != null ? (r.rooms >= 4 ? '4+' : String(r.rooms)) : '',
                    sort: 'yield', order: 'desc',
                  }) : undefined}>
                  <td>{biText(lang, r.name, r.name_uk)}</td>
                  <td className="num">{roomsLabel(r.rooms)}</td>
                  <td className="num">{fmtPln(r.rent_median_pln)}</td>
                  <td className="num">{fmtNum(r.rent_sqm, 1)}</td>
                  <td className="num">{fmtNum(r.sale_median_sqm)}</td>
                  <td className="num"><span className={'badge ' + (r.yield_pct >= 6 ? 'deal' : 'gray')}>{fmtNum(r.yield_pct, 1)}%</span></td>
                  <td className="num muted">{fmtNum(r.n_rent)} / {fmtNum(r.n_sale)}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={7} className="muted" style={{ textAlign: 'center', padding: 20 }}>Замало даних: потрібно ≥ 8 оголошень оренди і продажу в одному місці</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function Rent({ onOpen, urlParams, onParams, geo, goTo, sel, onSel }) {
  return (
    <>
      <Catalog rent onOpen={onOpen} urlParams={urlParams} onParams={onParams} geo={geo}
        sel={sel} onSel={onSel} />
      <YieldTop goTo={goTo} />
    </>
  )
}
