import React, { useEffect, useState } from 'react'
import { api, fmtNum, fmtDateTime, fmtAgo, errorText } from '../api.js'
import { tr } from '../i18n.js'
import ApiError from '../components/ApiError.jsx'
import { useFlash } from '../components/Toast.jsx'

const STATUS_ICON = { running: '⏳', done: '✅', failed: '❌', stopped: '⏸' }

export default function Runs({ summary }) {
  const [runs, setRuns] = useState(null)
  const [err, setErr] = useState(null)
  const [ts, setTs] = useState(null)
  const [unknown, setUnknown] = useState([])
  const [jobs, setJobs] = useState(null)
  const [hours, setHours] = useState(12)
  const [limit, setLimit] = useState(200)
  const [busy, setBusy] = useState('')
  const [flash, toast] = useFlash()

  const load = () => {
    api.runs(50).then(r => { setRuns(Array.isArray(r) ? r : (r.items || [])); setErr(null) }).catch(setErr)
    api.translateStatus().then(setTs).catch(() => setTs(null))
    api.unknownValues().then(r => setUnknown(Array.isArray(r) ? r : [])).catch(() => {})
    api.jobs().then(setJobs).catch(() => setJobs(null))
  }
  // Прогон идёт час; без автообновления таблица стоит с тем же «running»,
  // а потом оказывается, что он давно упал.
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t) }, [])

  const run = async (name, fn, okMsg) => {
    setBusy(name)
    try { const r = await fn(); flash(typeof okMsg === 'function' ? okMsg(r) : okMsg); load() }
    catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy('') }
  }

  const running = summary?.scrape_running || (runs || []).some(r => r.status === 'running')
  const paused = summary?.paused_until

  return (
    <>
      <div className="panel">
        <h3>Прогони</h3>
        <div className="row" style={{ marginBottom: 10 }}>
          <button className="btn" disabled={!!busy || running} title="Otodom + OLX, продаж; ~1 година"
            onClick={() => run('sale', () => api.scrape('sale', 'all'), r => `Запущено прогін продажу #${r.run_id ?? ''}`)}>▶ Запустити продаж</button>
          <button className="btn" disabled={!!busy || running} title="Otodom + OLX, оренда; ~30 хвилин"
            onClick={() => run('rent', () => api.scrape('rent', 'all'), r => `Запущено прогін оренди #${r.run_id ?? ''}`)}>▶ Запустити оренду</button>
          <button className="btn danger" disabled={!!busy || !running}
            onClick={() => run('stop', api.scrapeStop, 'Зупиняємо — прогін згорнеться за півхвилини')}>■ Зупинити</button>
          <span style={{ width: 16 }} />
          <label className="chk">пауза на
            <input type="number" min={0} style={{ width: 64 }} value={hours} onChange={e => setHours(+e.target.value)} />
            год (0 — до скасування)
          </label>
          <button className="btn ghost" disabled={!!busy}
            title="Згортає поточний прогін і не дає стартувати плановим. Не забудьте зняти — у шапці для цього червона плашка"
            onClick={() => run('pause', () => api.scrapePause(hours), 'Пауза поставлена')}>⏸ Пауза</button>
          {paused && <button className="btn" disabled={!!busy}
            onClick={() => run('resume', api.scrapeResume, 'Паузу знято')}>▶ Зняти паузу</button>}
          <span style={{ width: 16 }} />
          <button className="btn ghost" disabled={!!busy} title="Дублі → вигідність → дохідність, у фоні"
            onClick={() => run('recompute', api.recompute, 'Перерахунок запущено у фоні')}>↻ Перерахувати</button>
        </div>
        <p className="muted small">
          {running ? <span><span className="spin" />іде прогін…</span> : 'прогін не йде'}
          {paused ? <span className="badge drop" style={{ marginLeft: 10 }}>
            ⏸ пауза {fmtDateTime(paused) === '—' ? 'до скасування' : 'до ' + fmtDateTime(paused)}
          </span> : null}
          {jobs && <span style={{ marginLeft: 10 }}>
            · планувальник: {jobs.scheduler_running ? 'увімкнено' : (jobs.disabled_by_env ? 'вимкнено (розкладом керує система)' : 'вимкнено')}
            {(jobs.jobs || []).length ? ' · ' + jobs.jobs.map(j => `${j.id} → ${fmtDateTime(j.next_run)}`).join(', ') : ''}
          </span>}
        </p>
        <ApiError err={err} />
        <div className="wrap">
          <table className="grid">
            <thead><tr>
              <th>#</th><th>Вид</th><th>Джерело</th><th>Статус</th><th>Початок</th><th>Кінець</th>
              <th title="Остання відмітка життя">Живий</th>
              <th className="num">Стор.</th><th className="num">Бачили</th><th className="num">Нових</th>
              <th className="num">Оновл.</th><th className="num">Знято</th><th className="num">Помилок</th><th>Повідомлення</th>
            </tr></thead>
            <tbody>
              {(runs || []).map(r => (
                <tr key={r.id}>
                  <td className="muted">{r.id}</td>
                  <td>{tr('runKind', r.kind)}</td>
                  <td>{r.source === 'all' ? 'усі' : tr('source', r.source)}</td>
                  <td title={r.status}>{STATUS_ICON[r.status] || ''} {tr('runStatus', r.status)}</td>
                  <td className="muted">{fmtDateTime(r.started_at)}</td>
                  <td className="muted">{r.finished_at ? fmtDateTime(r.finished_at) : '—'}</td>
                  <td className="muted">{r.status === 'running' ? fmtAgo(r.last_beat) : ''}</td>
                  <td className="num">{fmtNum(r.pages)}</td>
                  <td className="num">{fmtNum(r.seen)}</td>
                  <td className="num">{fmtNum(r.new)}</td>
                  <td className="num">{fmtNum(r.updated)}</td>
                  <td className="num">{fmtNum(r.removed)}</td>
                  <td className="num">{r.errors ? <span className="badge drop">{fmtNum(r.errors)}</span> : '0'}</td>
                  <td className="small muted" style={{ maxWidth: 320 }}>{r.message || ''}</td>
                </tr>
              ))}
              {runs && !runs.length && <tr><td colSpan={14} className="muted" style={{ textAlign: 'center', padding: 20 }}>Прогонів ще не було</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <h3>Переклад</h3>
        {ts ? (
          <div className="cards" style={{ marginBottom: 12 }}>
            <div className="card"><div className="label">Провайдер</div><div className="value" style={{ fontSize: 16 }}>{tr('provider', ts.provider)}</div><div className="sub">{ts.model || ''}</div></div>
            <div className="card"><div className="label">У черзі: заголовки</div><div className="value">{fmtNum(ts.pending_titles)}</div></div>
            <div className="card"><div className="label">У черзі: описи</div><div className="value">{fmtNum(ts.pending_descriptions)}</div></div>
            <div className="card"><div className="label">Перекладено</div><div className="value">{fmtNum(ts.done_total)}</div><div className="sub">сьогодні: {fmtNum(ts.done_today)}</div></div>
          </div>
        ) : <p className="muted">Статус перекладу недоступний</p>}
        {ts?.last_error && <div className="error-box"><b>Остання помилка перекладу:</b> {ts.last_error}</div>}
        <div className="row">
          <label className="chk">не більше
            <input type="number" min={1} style={{ width: 80 }} value={limit} onChange={e => setLimit(+e.target.value)} /> шт.
          </label>
          <button className="btn" disabled={!!busy || ts?.running}
            onClick={() => run('translate', () => api.translateRun(limit), 'Переклад черги запущено у фоні')}>
            {ts?.running ? <span><span className="spin" />перекладаємо…</span> : 'Перекласти чергу'}
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>Незнайомі значення (немає у словнику)</h3>
        <p className="muted small">Значення структурних полів, які показуються польською з поміткою, — словник i18n.py треба поповнити.</p>
        {unknown.length ? (
          <table className="grid" style={{ maxWidth: 640 }}>
            <thead><tr><th>Поле</th><th>Значення (PL)</th><th className="num">Оголошень</th></tr></thead>
            <tbody>{unknown.map((u, i) => (
              <tr key={i}><td className="mono">{u.field}</td><td>{u.value_pl}</td><td className="num">{fmtNum(u.count)}</td></tr>
            ))}</tbody>
          </table>
        ) : <p className="muted">Усе знайоме</p>}
      </div>
      {toast}
    </>
  )
}
