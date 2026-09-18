import React, { useEffect, useState } from 'react'
import { api, fmtNum, fmtDateTime } from '../api.js'
import { T, describeQuery, actionsWord } from '../i18n.js'
import ApiError from '../components/ApiError.jsx'

const DAYS = [[7, '7 днів'], [14, '14 днів'], [30, '30 днів']]

// Об'єкт дії: картка — посилання на неї; пошук/експорт — розшифрований
// запит; решта — шлях як є (у підказці завжди сирий шлях із запитом).
function Target({ r, onOpen }) {
  const raw = (r.path || '') + (r.query ? '?' + r.query : '')
  if (r.listing_id) {
    return (
      <span title={raw}>
        <a onClick={() => onOpen(r.listing_id)} style={{ cursor: 'pointer' }}>
          {r.listing?.title || `#${r.listing_id}`}
        </a>
        {r.listing?.osiedle && <span className="muted"> · {r.listing.osiedle}</span>}
      </span>
    )
  }
  if (r.action === 'search' || r.action === 'export' || r.action === 'contacts') {
    const text = describeQuery(r.query, r.path)
    return <span title={raw}>{text || <span className="mono muted">{raw || '—'}</span>}</span>
  }
  return <span className="mono muted">{raw || '—'}</span>
}

// Журнал дій користувачів — лише для адміністратора: сервер відповідає 403
// іншим, а App цю сторінку viewer'у й не показує.
export default function Journal({ onOpen, me }) {
  const [f, setF] = useState({ user: '', days: 14, action: '', limit: 300 })
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true); setErr(null)
    api.activity(f).then(setData)
      .catch(e => { setErr(e); setData({ rows: [], per_user: {} }) })
      .finally(() => setLoading(false))
  }, [f])

  const set = (k, v) => setF({ ...f, [k]: v })
  const perUser = data?.per_user || {}
  // список користувачів — з /api/me (він повний), плюс ті, хто є в журналі
  const users = Array.from(new Set([...(me?.users || []), ...Object.keys(perUser)]))
  const rows = data?.rows || []

  return (
    <>
      <div className="filters">
        <select value={f.user} onChange={e => set('user', e.target.value)}>
          <option value="">користувач: усі</option>
          {users.map(u => <option key={u} value={u}>{u}</option>)}
        </select>
        <select value={f.days} onChange={e => set('days', +e.target.value)}>
          {DAYS.map(([d, l]) => <option key={d} value={d}>{l}</option>)}
        </select>
        <select value={f.action} onChange={e => set('action', e.target.value)}>
          <option value="">дія: усі</option>
          {Object.entries(T.action).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="muted small">за {data?.days ?? f.days} дн:</span>
        {Object.entries(perUser).sort((a, b) => b[1] - a[1]).map(([u, n]) => (
          <button key={u} type="button" className={'chip' + (f.user === u ? ' on' : '')}
            title="Показати лише цього користувача"
            onClick={() => set('user', f.user === u ? '' : u)}>
            {u} — {fmtNum(n)} {actionsWord(n)}
          </button>
        ))}
      </div>
      <div className="panel">
        <h3>{loading ? <span className="spin" /> : null}Журнал дій: {fmtNum(rows.length)}</h3>
        <ApiError err={err} />
        <div className="wrap" style={{ opacity: loading ? 0.45 : 1, transition: 'opacity .15s' }}>
          <table className="grid">
            <thead><tr><th>Час</th><th>Користувач</th><th>Дія</th><th>Об'єкт</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(r.at)}</td>
                  <td><b>{r.user}</b></td>
                  <td style={{ whiteSpace: 'nowrap' }}>{r.action_uk || T.action[r.action] || r.action}</td>
                  <td><Target r={r} onOpen={onOpen} /></td>
                </tr>
              ))}
              {data && !rows.length && (
                <tr><td colSpan={4} className="muted" style={{ textAlign: 'center', padding: 20 }}>Дій за цей період немає</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
