import React, { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { api, fmtNum, fmtPln } from '../api.js'
import { useLang, biText, T, roomsLabel } from '../i18n.js'
import ApiError from '../components/ApiError.jsx'

const AXIS = { fill: 'var(--muted)', fontSize: 11 }
const TIP = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 8, fontSize: 12, color: 'var(--ink)',
}

function Summary({ s }) {
  if (!s) return null
  const sale = s.sale || {}, rent = s.rent || {}
  return (
    <div className="cards">
      <div className="card"><div className="label">Активних продаж</div><div className="value">{fmtNum(sale.active)}</div>
        <div className="sub">нових за добу: {fmtNum(sale.new_24h)} · знято за тиждень: {fmtNum(sale.removed_7d)}</div></div>
      <div className="card"><div className="label">Медіана zł/м² (продаж)</div><div className="value">{fmtNum(sale.median_sqm)}</div>
        <div className="sub">медіана ціни {fmtPln(sale.median_price)}</div></div>
      <div className="card"><div className="label">Активних оренди</div><div className="value">{fmtNum(rent.active)}</div>
        <div className="sub">нових за добу: {fmtNum(rent.new_24h)}</div></div>
      <div className="card"><div className="label">Медіана ставки</div><div className="value">{fmtPln(rent.median_rent)}</div>
        <div className="sub">{fmtNum(rent.median_rent_sqm, 1)} zł/м²/міс</div></div>
      {s.fx && <div className="card"><div className="label">Курс НБП {s.fx.date || ''}</div>
        <div className="value">{fmtNum(s.fx.USD, 2)}</div><div className="sub">$ = {fmtNum(s.fx.USD, 2)} zł · € = {fmtNum(s.fx.EUR, 2)} zł</div></div>}
    </div>
  )
}

// Индекс по ОДНИМ И ТЕМ ЖЕ объявлениям (база 100): медиана по дате подачи
// движением рынка не является — дешёвое уходит быстрее (ARCHITECTURE §6).
function PriceIndex() {
  const [period, setPeriod] = useState('month')
  const [pts, setPts] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    setErr(null)
    api.priceIndex({ period, offer_type: 'sale' }).then(d => setPts(d.points || [])).catch(e => { setErr(e); setPts([]) })
  }, [period])
  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Індекс цін (ті самі оголошення, база 100)</h3>
        <span style={{ flex: 1 }} />
        <select value={period} onChange={e => setPeriod(e.target.value)}>
          <option value="month">по місяцях</option>
          <option value="quarter">по кварталах</option>
        </select>
      </div>
      <ApiError err={err} />
      {pts && pts.length > 1 ? (
        <div className="chart-box">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pts} margin={{ top: 5, right: 15, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" tick={AXIS} stroke="var(--baseline)" tickLine={false} />
              <YAxis tick={AXIS} stroke="transparent" tickLine={false} width={50} domain={['auto', 'auto']} />
              <Tooltip contentStyle={TIP}
                formatter={(v, name, item) => [
                  `${fmtNum(v, 1)}${item?.payload?.change_pct != null ? ` (${item.payload.change_pct > 0 ? '+' : ''}${fmtNum(item.payload.change_pct, 1)}% за період)` : ''}`,
                  `індекс · n=${fmtNum(item?.payload?.n)}`]} />
              <Line dataKey="index" type="monotone" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : pts && <p className="muted">Індексу ще немає: потрібні оголошення, що жили на двох межах періоду</p>}
    </div>
  )
}

// Нові / зняті за тиждень і медіана zł/м² — на двох осях
function Trends() {
  const [weeks, setWeeks] = useState(26)
  const [pts, setPts] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    setErr(null)
    api.trends({ weeks, offer_type: 'sale' }).then(d => setPts(d.points || [])).catch(e => { setErr(e); setPts([]) })
  }, [weeks])
  const last = pts && pts[pts.length - 1]
  return (
    <div className="panel">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>Тренди по тижнях</h3>
        {last && <span className="muted small">останній тиждень: нових {fmtNum(last.new)}, знято {fmtNum(last.removed)}, активних {fmtNum(last.active)}, медіана {fmtNum(last.median_sqm)} zł/м²</span>}
        <span style={{ flex: 1 }} />
        <select value={weeks} onChange={e => setWeeks(+e.target.value)}>
          <option value={12}>12 тижнів</option><option value={26}>26 тижнів</option><option value={52}>52 тижні</option>
        </select>
      </div>
      <ApiError err={err} />
      {pts && pts.length > 0 ? (
        <div className="chart-box">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pts} margin={{ top: 5, right: 15, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="week" tick={AXIS} stroke="var(--baseline)" tickLine={false} />
              <YAxis yAxisId="n" tick={AXIS} stroke="transparent" tickLine={false} width={45} />
              <YAxis yAxisId="sqm" orientation="right" tick={AXIS} stroke="transparent" tickLine={false} width={55} domain={['auto', 'auto']} />
              <Tooltip contentStyle={TIP} formatter={(v, name) => [fmtNum(v), name]} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line yAxisId="n" dataKey="new" name="нові" type="monotone" stroke="var(--series-2)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="n" dataKey="removed" name="зняті" type="monotone" stroke="var(--series-3)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line yAxisId="sqm" dataKey="median_sqm" name="медіана zł/м²" type="monotone" stroke="var(--series-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : pts && <p className="muted">Даних ще немає</p>}
    </div>
  )
}

export default function Stats({ summary, goTo }) {
  const { lang } = useLang()
  const [p, setP] = useState({ offer_type: 'sale', level: 'osiedle', rooms: '', market: '', condition: '' })
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [sort, setSort] = useState(['count', 'desc'])
  useEffect(() => {
    setErr(null)
    api.stats(p).then(d => setData(d)).catch(e => { setErr(e); setData({ rows: [] }) })
  }, [p])
  const set = (k, v) => setP({ ...p, [k]: v })
  const rent = p.offer_type === 'rent'
  const rows = [...(data?.rows || [])].sort((a, b) => {
    const [k, o] = sort
    const x = a[k] ?? -Infinity, y = b[k] ?? -Infinity
    return (x < y ? -1 : x > y ? 1 : 0) * (o === 'asc' ? 1 : -1)
  })
  const Th = ({ k, children, title }) => (
    <th className={'num sortable'} title={title || 'Сортувати'}
      onClick={() => setSort([k, sort[0] === k && sort[1] === 'desc' ? 'asc' : 'desc'])}>
      {children}{sort[0] === k ? (sort[1] === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  )
  const coef = data?.area_coef && Object.entries(data.area_coef)

  return (
    <>
      <Summary s={summary} />
      <div className="panel">
        <div className="filters">
          <h3 style={{ margin: 0 }}>Зрізи ринку</h3>
          <span style={{ display: 'flex', gap: 4 }}>
            {[['sale', 'продаж'], ['rent', 'оренда']].map(([k, v]) => (
              <button key={k} type="button" className={'chip' + (p.offer_type === k ? ' on' : '')} onClick={() => set('offer_type', k)}>{v}</button>
            ))}
          </span>
          <select value={p.level} onChange={e => set('level', e.target.value)}>
            <option value="osiedle">по осиедле</option>
            <option value="district">по дзельницях</option>
          </select>
          <select value={p.rooms} onChange={e => set('rooms', e.target.value)}>
            <option value="">кімнати: усі</option>
            {['1', '2', '3', '4'].map(r => <option key={r} value={r}>{r === '4' ? '4+' : r}</option>)}
          </select>
          <select value={p.market} onChange={e => set('market', e.target.value)}>
            <option value="">ринок: будь-який</option>
            <option value="primary">первинний</option>
            <option value="secondary">вторинний</option>
          </select>
          <select value={p.condition} onChange={e => set('condition', e.target.value)}>
            <option value="">стан: будь-який</option>
            {Object.entries(T.condition).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {data?.total != null && <span className="muted">оголошень: {fmtNum(data.total)}</span>}
        </div>
        <ApiError err={err} />
        {coef && coef.length > 0 && (
          <p className="muted small" title="Медіана zł/м² по смугах площі відносно смуги 45–60 м², міряється на своїх даних при кожному перерахунку">
            Поправка на площу: {coef.map(([b, c]) => `${b}: ×${fmtNum(c, 2)}`).join(' · ')}
          </p>
        )}
        <div className="wrap">
          <table className="grid">
            <thead><tr>
              <th>{p.level === 'district' ? 'Дзельниця' : 'Осиедле'}</th>
              {p.level !== 'district' && <th>Дзельниця</th>}
              <Th k="count">Оголош.</Th>
              <Th k="median_sqm" title={rent ? 'Медіана ставки за м² на місяць' : 'Медіана ціни за м²'}>{rent ? 'zł/м²/міс' : 'zł/м²'}</Th>
              <th className="num" title="Квартилі ціни за м²">p25 – p75</th>
              <Th k="median_price">{rent ? 'Ставка' : 'Ціна'}</Th>
              <Th k="median_area">м²</Th>
              <Th k="new_30d" title="Нових за 30 днів">+30д</Th>
              <Th k="removed_30d" title="Знято за 30 днів">−30д</Th>
              <Th k="median_days" title="Медіана днів у продажу">днів</Th>
            </tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={goTo ? 'clickable' : ''} title="Показати ці оголошення в каталозі"
                  onClick={goTo ? () => goTo(rent ? 'rent' : 'catalog', {
                    [p.level === 'district' ? 'district' : 'osiedle']: r.name,
                    rooms: p.rooms ? (p.rooms === '4' ? '4+' : p.rooms) : '', market: p.market, condition: p.condition,
                  }) : undefined}>
                  <td>{biText(lang, r.name, r.name_uk)}</td>
                  {p.level !== 'district' && <td className="muted">{r.district || ''}</td>}
                  <td className="num">{fmtNum(r.count)}</td>
                  <td className="num"><b>{fmtNum(r.median_sqm, rent ? 1 : 0)}</b></td>
                  <td className="num muted">{fmtNum(r.p25_sqm, rent ? 1 : 0)} – {fmtNum(r.p75_sqm, rent ? 1 : 0)}</td>
                  <td className="num">{fmtPln(r.median_price)}</td>
                  <td className="num">{fmtNum(r.median_area)}</td>
                  <td className="num">{fmtNum(r.new_30d)}</td>
                  <td className="num">{fmtNum(r.removed_30d)}</td>
                  <td className="num muted">{fmtNum(r.median_days)}</td>
                </tr>
              ))}
              {data && !rows.length && <tr><td colSpan={10} className="muted" style={{ textAlign: 'center', padding: 20 }}>Даних немає</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <PriceIndex />
      <Trends />
    </>
  )
}
