import React, { useEffect, useMemo, useState } from 'react'
import { api, fmtNum, fmtDate } from '../api.js'
import { useLang, tr, biText } from '../i18n.js'
import Phone from '../components/Phone.jsx'
import Pager from '../components/Pager.jsx'
import ApiError from '../components/ApiError.jsx'

// Картки контактів: одна строка на продавца/орендодавця с числом размещений
// и телефоном. Сделано для знакомой рієлторки по оренді — ей нужны
// собственники с телефонами, поэтому «лише власники» стоит первым.
const NUMERIC = new Set(['page', 'per_page'])
const SORTS = [
  ['active_total', 'за активними'], ['last_seen', 'за останнім переглядом'],
  ['listings_rent', 'за орендою'], ['listings_sale', 'за продажем'],
]

function fromUrl(p) {
  const out = {}
  for (const [k, v] of Object.entries(p || {})) {
    if (k === 'id') continue
    out[k] = NUMERIC.has(k) ? Number(v) : v
  }
  return out
}

export default function Contacts({ onOpen, urlParams, onParams, geo, goTo }) {
  const { lang } = useLang()
  const [f, setF] = useState({
    offer_type: 'all', seller_type: '', q: '', sort: 'active_total', order: 'desc',
    page: 1, per_page: 50, ...fromUrl(urlParams),
  })
  const [data, setData] = useState({ items: [], total: 0 })
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      api.contacts(f)
        .then(d => { setData(d); setErr(null) })
        .catch(e => { setErr(e); setData({ items: [], total: 0 }) })
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [f])
  useEffect(() => {
    if (!onParams) return undefined
    const t = setTimeout(() => onParams(f), 250)
    return () => clearTimeout(t)
  }, [f])

  // осиедле у контакта приходят польскими именами — переводим по справочнику
  const ukName = useMemo(() => {
    const m = {}
    for (const d of geo?.districts || []) for (const o of d.osiedla || []) m[o.name] = o.name_uk
    return m
  }, [geo])

  const set = (k, v) => setF({ ...f, [k]: v, page: 1 })
  const per = data.per_page || f.per_page || 50
  const pager = (top) => (
    <Pager top={top} page={f.page || 1} perPage={per} total={data.total}
      onPage={n => setF({ ...f, page: n })}
      onPerPage={(v, n) => setF({ ...f, per_page: v, page: n })} />
  )
  // куда вести по клику: у орендодавця — в каталог оренди
  const openSeller = (c) => {
    const tab = f.offer_type === 'rent' || (!c.listings_sale && c.listings_rent) ? 'rent' : 'catalog'
    goTo(tab, { seller_key: c.seller_key })
  }

  return (
    <>
      <div className="filters">
        <label className="chk" title="Тільки власники — без агенцій і забудовників">
          <input type="checkbox" checked={f.seller_type === 'private'}
            onChange={e => set('seller_type', e.target.checked ? 'private' : '')} /> лише власники
        </label>
        <select value={f.seller_type} onChange={e => set('seller_type', e.target.value)}>
          <option value="">тип: усі</option>
          <option value="private">власник</option>
          <option value="agency">агенція</option>
          <option value="developer">забудовник</option>
        </select>
        <span style={{ display: 'flex', gap: 4 }}>
          {[['all', 'усі'], ['sale', 'продаж'], ['rent', 'оренда']].map(([k, v]) => (
            <button key={k} type="button" className={'chip' + (f.offer_type === k ? ' on' : '')}
              onClick={() => set('offer_type', k)}>{v}</button>
          ))}
        </span>
        <input type="text" placeholder="Пошук: ім'я, телефон…" style={{ minWidth: 220 }}
          value={f.q ?? ''} onChange={e => set('q', e.target.value)} />
        <label className="chk">сортування:
          <select value={f.sort} onChange={e => set('sort', e.target.value)}>
            {SORTS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select value={f.order} onChange={e => set('order', e.target.value)}>
            <option value="desc">↓</option><option value="asc">↑</option>
          </select>
        </label>
        <span style={{ flex: 1 }} />
        <a className="btn ghost" href={api.contactsExportUrl(f, 'csv')}>Експорт CSV</a>
        <a className="btn ghost" href={api.contactsExportUrl(f, 'xlsx')}>XLSX</a>
      </div>
      <div className="panel">
        <h3>{loading ? <span className="spin" /> : null}Контактів: {fmtNum(data.total)}</h3>
        <ApiError err={err} />
        {pager(true)}
        <div className="wrap" style={{ opacity: loading ? 0.45 : 1, transition: 'opacity .15s' }}>
          <table className="grid">
            <thead><tr>
              <th>Продавець</th><th>Телефон</th>
              <th className="num">Продаж</th><th className="num">Оренда</th><th className="num">Активних</th>
              <th>Осиедле</th><th className="num">Перший</th><th className="num">Останній</th><th>Приклади</th>
            </tr></thead>
            <tbody>
              {(data.items || []).map(c => (
                <tr key={c.seller_key} className="clickable" title="Усі оголошення цього продавця"
                  onClick={() => openSeller(c)}>
                  <td>
                    <b>{c.seller_name || <span className="muted">без імені</span>}</b>
                    <div className="badges">
                      <span className={'badge ' + (c.seller_type === 'private' ? 'owner' : 'gray')}>
                        {c.seller_type_uk || tr('seller', c.seller_type)}
                      </span>
                      <span className="badge gray">{tr('source', c.source)}</span>
                    </div>
                  </td>
                  <td>{c.seller_phone ? <Phone value={c.seller_phone} /> : <span className="muted small">немає</span>}</td>
                  <td className="num">{fmtNum(c.listings_sale)}</td>
                  <td className="num">{fmtNum(c.listings_rent)}</td>
                  <td className="num"><b>{fmtNum(c.active_total)}</b></td>
                  <td className="small">{(c.osiedla || []).map(n => biText(lang, n, ukName[n])).join(', ') || '—'}</td>
                  <td className="num muted">{fmtDate(c.first_seen)}</td>
                  <td className="num muted">{fmtDate(c.last_seen)}</td>
                  <td>
                    {(c.sample_ids || []).slice(0, 3).map(id => (
                      <a key={id} onClick={e => { e.stopPropagation(); onOpen(id) }}
                        style={{ cursor: 'pointer', marginRight: 6 }} title="Відкрити картку">#{id}</a>
                    ))}
                  </td>
                </tr>
              ))}
              {!(data.items || []).length && loading && [0, 1, 2].map(i => (
                <tr key={'sk' + i}><td colSpan={9}><div className="skeleton sk-row" /></td></tr>
              ))}
              {!(data.items || []).length && !loading && (
                <tr><td colSpan={9}><div className="empty"><div className="big">Нічого не знайдено</div>Спробуйте послабити фільтри.</div></td></tr>
              )}
            </tbody>
          </table>
        </div>
        {pager(false)}
      </div>
    </>
  )
}
