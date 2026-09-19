import React, { useEffect, useState } from 'react'
import { api, fmtNum, fmtPln, fmtUsd, fmtEur, fmtDate, fmtDateTime, errorText } from '../api.js'
import { useLang, tr, T, dealTitle, yieldTitle, roomsLabel, floorText, FLOOR_HINT, biText } from '../i18n.js'
import Bi from './Bi.jsx'
import Gallery from './Gallery.jsx'
import Phone from './Phone.jsx'
import ApiError from './ApiError.jsx'
import { useFlash } from './Toast.jsx'

const val = (v) => v == null || v === '' ? '—' : typeof v === 'boolean' ? (v ? 'так' : 'ні') : String(v)

// Заголовок и описание: два столбца PL | UK, чтобы перевод сверялся глазом
// с оригиналом, или один — по переключателю в шапке.
function TextCols({ l }) {
  const { lang } = useLang()
  const hasUk = !!(l.title_uk || l.description_uk)
  const colPl = (
    <div key="pl">
      <span className="col-tag">PL · оригінал</span>
      <div style={{ marginBottom: 6 }}><b>{l.title_pl || '—'}</b></div>
      <div className="desc">{l.description_pl || <span className="muted">опису немає</span>}</div>
    </div>
  )
  const colUk = (
    <div key="uk">
      <span className="col-tag">UK · переклад</span>
      {hasUk ? (
        <>
          <div style={{ marginBottom: 6 }}>
            <b>{l.title_uk || <span className="muted">заголовок не перекладено</span>}</b>
          </div>
          <div className="desc">
            {l.description_uk || <span className="muted">опис ще в черзі — натисніть «Перекласти зараз»</span>}
          </div>
        </>
      ) : (
        <div className="muted">Перекладу ще немає: натисніть «Перекласти зараз» або дочекайтесь черги</div>
      )}
    </div>
  )
  if (lang === 'pl') return <div className="two-col single">{colPl}</div>
  if (lang === 'uk') return <div className="two-col single">{hasUk ? colUk : [colUk, colPl]}</div>
  return <div className="two-col">{colPl}{colUk}</div>
}

// Характеристики: подпись и значение — обе двуязычные
function Chars({ rows }) {
  const { lang } = useLang()
  if (!rows || !rows.length) return <p className="muted">Характеристик немає</p>
  if (lang === 'both') {
    return (
      <table className="chars">
        <thead><tr><th colSpan={2}>PL · оригінал</th><th colSpan={2}>UK · переклад</th></tr></thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={c.key || i}>
              <td className="k">{val(c.label_pl)}</td><td>{val(c.value_pl)}</td>
              <td className="k">{val(c.label_uk || c.label_pl)}</td>
              <td>{c.value_uk != null && c.value_uk !== '' ? val(c.value_uk) : <span className="muted">{val(c.value_pl)}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  const pl = lang === 'pl'
  return (
    <table className="chars">
      <tbody>
        {rows.map((c, i) => (
          <tr key={c.key || i}>
            <td className="k">{val(pl ? c.label_pl : (c.label_uk || c.label_pl))}</td>
            <td>{val(pl ? c.value_pl : (c.value_uk ?? c.value_pl))}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Откуда взялась знижка: рівень пулу, його розмір, медіана та перебір кроків
// тим самим кодом, що й розрахунок (backend analytics.explain).
function DealExplain({ l }) {
  const e = l.deal_explain
  if (!e) return <p className="muted">Знижку не пораховано: замало схожих квартир або оголошення зняте</p>
  return (
    <div className="explain">
      <p>
        {l.discount_pct != null && (
          <span className={'badge ' + (l.discount_pct >= 3 && !l.deal_thin_base ? 'deal' : 'gray')}
            title={dealTitle(l)} style={{ marginRight: 8 }}>
            {l.discount_pct >= 0 ? '−' : '+'}{fmtNum(Math.abs(l.discount_pct), 1)}%
          </span>
        )}
        рівень <b>{tr('level', e.level)}</b>{e.key ? <span className="muted"> ({e.key})</span> : ''},
        пул <b>{fmtNum(e.pool_size)}</b>, медіана <b>{fmtNum(e.median_sqm)} zł/м²</b>
        {e.area_coef != null && <>, поправка на площу ×{fmtNum(e.area_coef, 3)}</>}
        {e.price_sqm_adj != null && <>, ціна з поправкою {fmtNum(e.price_sqm_adj)} zł/м²</>}
        {l.deal_thin_base ? <span className="badge warn" style={{ marginLeft: 8 }}>база тонка</span> : null}
      </p>
      {e.steps && e.steps.length > 0 && (
        <table>
          <thead><tr><th>рівень</th><th>ключ</th><th className="num">n</th><th></th></tr></thead>
          <tbody>
            {e.steps.map((s, i) => (
              <tr key={i} className={s.ok ? 'hit' : ''}>
                <td>{tr('level', s.level)}</td>
                <td className="muted">{s.key || ''}</td>
                <td className="num">{fmtNum(s.n)}</td>
                <td>{s.ok ? '✓ вистачило' : 'замало'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RentExplain({ l }) {
  const e = l.rent_explain
  if (!e) return <p className="muted">Дохідність не пораховано: поруч немає оголошень оренди</p>
  return (
    <div className="explain">
      <p>
        {l.yield_pct != null && (
          <span className={'badge ' + (l.yield_pct >= 6 ? 'deal' : 'gray')} title={yieldTitle(l)}
            style={{ marginRight: 8 }}>{fmtNum(l.yield_pct, 1)}% річних</span>
        )}
        ставка за медіаною по <b>{tr('level', e.level)}</b> ({fmtNum(e.count)} оголош.):
        {' '}<b>{fmtNum(e.median_sqm, 1)} zł/м²/міс</b> → очікувана оренда <b>{fmtPln(e.expected_rent)}/міс</b>
      </p>
      <p className="muted">
        вкладення {fmtPln(e.investment_pln)}
        {e.renovation_cost_pln > 0 ? ` = ціна + оздоблення ${fmtPln(e.renovation_cost_pln)}` : ''};
        валова: ставка × 12 / вкладення, без податку, простою та czynsz
      </p>
    </div>
  )
}

export default function Card({ id, onClose, onOpen, geo, goTo }) {
  const { lang } = useLang()
  const [l, setL] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState('')
  const [form, setForm] = useState({ osiedle: '', condition: '', note: '' })
  const [flash, toast] = useFlash()

  const load = () => {
    setErr(null)
    api.listing(id).then(d => {
      setL(d)
      setForm({ osiedle: d.osiedle || '', condition: d.condition || '', note: d.note || '' })
    }).catch(setErr)
  }
  useEffect(() => { setL(null); load() }, [id])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = async (name, fn, okMsg) => {
    setBusy(name)
    try { await fn(); if (okMsg) flash(okMsg) }
    catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy('') }
  }

  const translateNow = () => run('translate', async () => {
    const r = await api.translate(id)
    setL(x => ({ ...x, title_uk: r.title_uk, description_uk: r.description_uk, translated: true }))
    flash(`Перекладено (${r.provider || '?'}${r.cached ? ', з кешу' : ''})`)
  })

  const toggleFav = () => run('fav', async () => {
    const r = await api.favorite(id)
    setL(x => ({ ...x, is_favorite: r.is_favorite }))
  })

  // «інша квартира»: размещение уходит из группы дублей. Барьера, который
  // не ошибается, не существует (docs/ARCHITECTURE.md §4) — кнопка есть с
  // первого дня.
  const detach = (dupId) => run('detach', async () => {
    await api.detach(dupId)
    load()
  }, 'Розміщення від\'єднано від групи')

  // Ручные правки шлём только те, что изменились: правка, равная авто-значению,
  // всё равно легла бы в user_actions и перекрыла бы автомат навсегда.
  const dirty = l && (
    (form.osiedle || '') !== (l.osiedle || '')
    || (form.condition || '') !== (l.condition || '')
    || (form.note || '') !== (l.note || ''))
  const saveManual = () => run('manual', async () => {
    const patch = {}
    if ((form.osiedle || '') !== (l.osiedle || '')) patch.osiedle = form.osiedle || null
    if ((form.condition || '') !== (l.condition || '')) patch.condition = form.condition || null
    if ((form.note || '') !== (l.note || '')) patch.note = form.note || null
    const d = await api.manual(id, patch)
    setL(d)
    setForm({ osiedle: d.osiedle || '', condition: d.condition || '', note: d.note || '' })
  }, 'Збережено')

  const osiedla = (geo?.districts || []).flatMap(d => (d.osiedla || []).map(o => ({
    name: o.name, label: biText(lang, o.name, o.name_uk) + ` — ${biText(lang, d.name, d.name_uk)}`,
  })))
  const isRent = l?.offer_type === 'rent'
  const sellerTab = isRent ? 'rent' : 'catalog'

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal">
        <button className="close" onClick={onClose} title="Закрити (Esc)">×</button>
        {err && <ApiError err={err} prefix="Картку не завантажено" />}
        {!l && !err && <p className="muted"><span className="spin" />Завантаження…</p>}
        {l && (
          <>
            <h2><Bi pl={l.title_pl} uk={l.title_uk} sub={false} /></h2>
            <div className="price-line">
              <span>{fmtPln(l.price_pln)}{isRent ? <span className="sub">/міс</span> : ''}</span>
              {!isRent && <span className="sub" title="За курсом НБП">{fmtUsd(l.price_usd)}{l.price_eur ? ` · ${fmtEur(l.price_eur)}` : ''}</span>}
              <span className="sub">{fmtNum(l.price_per_m2)} zł/м²</span>
              {l.czynsz_pln ? <span className="sub" title="Експлуатаційний платіж — понад ціну/ставку">czynsz {fmtPln(l.czynsz_pln)}/міс</span> : null}
              {l.is_active === false && <span className="badge drop">знято {fmtDate(l.removed_at)}</span>}
            </div>

            <div className="row" style={{ margin: '10px 0' }}>
              <button className={'btn' + (l.is_favorite ? '' : ' ghost')} disabled={busy === 'fav'} onClick={toggleFav}>
                {l.is_favorite ? '★ В обраних' : '☆ До обраних'}
              </button>
              <button className="btn ghost" disabled={busy === 'translate'} onClick={translateNow}
                title="Переклад цієї картки поза чергою, синхронно (до 30 с)">
                {busy === 'translate' ? <span className="spin" /> : null}Перекласти зараз
              </button>
              {l.url && <a className="btn ghost" href={l.url} target="_blank" rel="noreferrer">Відкрити на {tr('source', l.source)} ↗</a>}
              {l.external_url && <a className="btn ghost" href={l.external_url} target="_blank" rel="noreferrer" title="Те саме оголошення на Otodom (OLX дзеркалить)">Дзеркало ↗</a>}
              {l.seller_key && goTo && (
                <button className="btn ghost" onClick={() => goTo(sellerTab, { seller_key: l.seller_key })}>
                  усі оголошення продавця
                </button>
              )}
            </div>

            <div className="kv">
              <div><span className="k">Кімнати: </span>{roomsLabel(l.rooms)}</div>
              <div><span className="k">Площа: </span>{fmtNum(l.area, 1)} м²</div>
              <div title={FLOOR_HINT}><span className="k">Поверх: </span>{floorText(l)} <span className="muted" style={{ cursor: 'help' }}>ⓘ</span></div>
              <div><span className="k">Рік: </span>{val(l.build_year)}</div>
              <div><span className="k">Ринок: </span>{tr('market', l.market)}</div>
              <div><span className="k">Будинок: </span>{l.building_type_uk || val(l.building_type)}</div>
              <div><span className="k">Стан: </span>{l.condition_uk || tr('condition', l.condition)}
                {l.condition_src === 'manual' && <span className="badge gray" style={{ marginLeft: 6 }}>вручну</span>}</div>
              <div><span className="k">Осиедле: </span>{biText(lang, l.osiedle, l.osiedle_uk) || '—'}</div>
              <div><span className="k">Дзельниця: </span>{biText(lang, l.district, l.district_uk) || '—'}</div>
              <div><span className="k">Вулиця: </span>{val(l.street)}</div>
              <div><span className="k">Подано: </span>{fmtDate(l.posted_at)}</div>
              <div><span className="k">У базі з: </span>{fmtDate(l.first_seen)} <span className="muted">({l.days_on_market ?? '—'} дн)</span></div>
              <div><span className="k">Останній перегляд: </span>{fmtDateTime(l.last_seen)}</div>
              <div><span className="k">Розміщень: </span>{l.group_size || 1}{l.dedup_group ? <span className="muted"> · {l.dedup_group}</span> : null}</div>
              {l.lat != null && l.lon != null && (
                <div><span className="k">Мапа: </span>
                  <a href={`https://www.google.com/maps?q=${l.lat},${l.lon}`} target="_blank" rel="noreferrer">{Number(l.lat).toFixed(4)}, {Number(l.lon).toFixed(4)} ↗</a></div>
              )}
            </div>

            <h3>Контакт</h3>
            <div className="kv" style={{ marginTop: 4 }}>
              <div><span className="k">Продавець: </span>{val(l.seller_name)}
                {l.no_commission ? <span className="badge deal" style={{ marginLeft: 6 }}>без комісії</span> : null}</div>
              <div><span className="k">Тип: </span>{l.seller_type_uk || tr('seller', l.seller_type)}</div>
              <div style={{ gridColumn: 'span 2' }}><span className="k">Телефон: </span>
                {l.seller_phone
                  ? <Phone value={l.seller_phone} />
                  : <span className="muted">телефон не віддається без входу на площадку;{' '}
                      {l.url ? <a href={l.url} target="_blank" rel="noreferrer">відкрити на джерелі ↗</a> : 'відкрийте на джерелі'}
                    </span>}
              </div>
              {l.seller_id && <div><span className="k">ID продавця: </span><span className="mono">{l.seller_id}</span></div>}
              {l.seller_key && goTo && (
                <div><a onClick={() => goTo(sellerTab, { seller_key: l.seller_key })} style={{ cursor: 'pointer' }}>усі оголошення продавця →</a></div>
              )}
            </div>

            <Gallery images={l.images} />

            <h3>Опис</h3>
            <TextCols l={l} />

            <h3>Характеристики</h3>
            <Chars rows={l.characteristics} />

            <div className="grid-2">
              <div>
                <h3>Історія цін</h3>
                {(l.price_history || []).length
                  ? <table className="dupes"><tbody>
                      {l.price_history.map((h, i, arr) => {
                        const prev = arr[i - 1]
                        const d = prev && prev.price_pln ? (h.price_pln - prev.price_pln) / prev.price_pln * 100 : null
                        return (
                          <tr key={i}>
                            <td className="muted">{fmtDate(h.seen_at)}</td>
                            <td className="num"><b>{fmtPln(h.price_pln)}</b></td>
                            <td className="num">{d != null ? <span className={d < 0 ? 'badge drop' : 'muted'}>{d < 0 ? '▼' : '▲'} {fmtNum(Math.abs(d), 1)}%</span> : ''}</td>
                          </tr>
                        )
                      })}
                    </tbody></table>
                  : <p className="muted">Ціна не змінювалась</p>}
              </div>
              <div>
                <h3>Розміщення (дублі)</h3>
                {(l.dupes || []).length
                  ? <table className="dupes"><tbody>
                      {l.dupes.map(d => (
                        <tr key={d.id} className={d.id === l.id ? 'self' : ''}>
                          <td>{tr('source', d.source)}</td>
                          <td className="num"><b>{fmtPln(d.price_pln)}</b></td>
                          <td className="muted">{tr('seller', d.seller_type)}</td>
                          <td className="muted">{fmtDate(d.first_seen)}</td>
                          <td>{d.is_active === false ? <span className="badge drop">знято</span> : null}</td>
                          <td style={{ whiteSpace: 'nowrap' }}>
                            {d.id !== l.id && onOpen && <a onClick={() => onOpen(d.id)} style={{ cursor: 'pointer', marginRight: 8 }}>картка</a>}
                            {d.url && <a href={d.url} target="_blank" rel="noreferrer">джерело ↗</a>}
                          </td>
                          <td>
                            <button className="btn ghost small" disabled={busy === 'detach'}
                              title="Це інша квартира, а не дубль — вивести з групи"
                              onClick={() => detach(d.id)}>інша квартира</button>
                          </td>
                        </tr>
                      ))}
                    </tbody></table>
                  : <p className="muted">Інших розміщень не знайдено</p>}
              </div>
            </div>

            {!isRent && (
              <div className="grid-2">
                <div><h3>Чому така знижка</h3><DealExplain l={l} /></div>
                <div><h3>Дохідність від оренди</h3><RentExplain l={l} /></div>
              </div>
            )}

            <h3>Ручні правки</h3>
            <div className="form-grid">
              <div>
                <label>Осиедле (порожнє — як визначив автомат)</label>
                <select value={form.osiedle} onChange={e => setForm({ ...form, osiedle: e.target.value })}>
                  <option value="">— авто —</option>
                  {form.osiedle && !osiedla.some(o => o.name === form.osiedle) && <option value={form.osiedle}>{form.osiedle}</option>}
                  {osiedla.map(o => <option key={o.name} value={o.name}>{o.label}</option>)}
                </select>
              </div>
              <div>
                <label>Стан (корзина порівняння для знижки)</label>
                <select value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })}>
                  <option value="">— авто —</option>
                  {Object.entries(T.condition).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <label>Нотатка</label>
                <textarea value={form.note} onChange={e => setForm({ ...form, note: e.target.value })}
                  placeholder="Що з'ясували по телефону, на що звернути увагу…" />
              </div>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn" disabled={!dirty || busy === 'manual'} onClick={saveManual}>Зберегти правки</button>
              <span className="muted small">Ручна правка сильніша за автомат і не перетирається прогоном</span>
            </div>
          </>
        )}
        {toast}
      </div>
    </div>
  )
}
