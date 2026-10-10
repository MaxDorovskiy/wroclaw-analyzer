import React, { useEffect, useState } from 'react'
import { api, fmtDateTime, errorText } from '../api.js'
import ApiError from '../components/ApiError.jsx'
import { useFlash } from '../components/Toast.jsx'

// «Питання до мене» — те же вопросы, что в чате, под теми же номерами.
// Смысл раздела: не держать решения в переписке, где они теряются. Владелец
// видит, что висит, и отвечает здесь; я перед следующим отчётом читаю ответы.

const BADGE = {
  open: 'warn', answered: 'deal', deferred: 'gray', done: 'gray',
}

function Question({ q, onAnswer, onStatus, busy }) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const waiting = q.status === 'open'
  return (
    <div className="panel" style={{ marginBottom: 'var(--s3)' }}>
      <div className="row" style={{ alignItems: 'baseline', marginBottom: 'var(--s2)' }}>
        <b style={{ fontSize: 15 }}>№{q.num}</b>
        {q.topic && <span className="badge gray">{q.topic}</span>}
        <span className={'badge ' + (BADGE[q.status] || 'gray')}>{q.status_uk}</span>
        <span className="spacer" />
        <span className="muted small">запитано {q.asked_at}</span>
      </div>

      <div style={{ fontWeight: 600, marginBottom: 4 }}>{q.text}</div>
      {q.why && <p className="hint" style={{ marginTop: 0 }}>{q.why}</p>}

      {q.answer && (
        <div className="kv" style={{ marginBottom: q.result ? 6 : 0 }}>
          <div><span className="k">Ваша відповідь: </span>{q.answer}
            <span className="muted small">
              {' · '}{q.answered_via || 'чат'}
              {q.answered_at ? ', ' + fmtDateTime(q.answered_at, { year: undefined }) : ''}
            </span>
          </div>
        </div>
      )}
      {q.result && <p className="muted small" style={{ margin: 0 }}>Підсумок: {q.result}</p>}

      {q.status !== 'done' && (
        <div className="row" style={{ marginTop: 'var(--s2)' }}>
          {!open && (
            <button className="btn" disabled={busy} onClick={() => setOpen(true)}>
              {q.answer ? 'Змінити відповідь' : 'Відповісти'}
            </button>
          )}
          {waiting && !open && (
            <button className="btn ghost" disabled={busy}
              title="Не зараз — приберу з тих, що чекають, але питання залишиться видимим"
              onClick={() => onStatus(q.num, 'deferred')}>Відкласти</button>
          )}
          {q.status === 'deferred' && !open && (
            <button className="btn ghost" disabled={busy}
              onClick={() => onStatus(q.num, 'open')}>Повернути в роботу</button>
          )}
        </div>
      )}

      {open && (
        <div style={{ marginTop: 'var(--s2)' }}>
          <label htmlFor={'ans' + q.num}>Відповідь</label>
          <textarea id={'ans' + q.num} rows={2} value={text} autoFocus
            onChange={e => setText(e.target.value)}
            placeholder="Коротко: «так», «ні», «пізніше», або що саме зробити" />
          <div className="row" style={{ marginTop: 6 }}>
            <button className="btn" disabled={busy || !text.trim()}
              onClick={() => onAnswer(q.num, text).then(ok => { if (ok) { setOpen(false); setText('') } })}>
              Зберегти
            </button>
            <button className="btn ghost" disabled={busy}
              onClick={() => { setOpen(false); setText('') }}>Скасувати</button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Questions({ me }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [flash, toast] = useFlash()

  const load = () => api.questions().then(d => { setData(d); setErr(null) }).catch(setErr)
  useEffect(() => { load() }, [])

  const onAnswer = async (num, text) => {
    setBusy(true)
    try {
      await api.questionAnswer(num, text)
      flash(`Відповідь на №${num} збережено`)
      await load()
      return true
    } catch (e) { flash('❌ ' + errorText(e)); return false }
    finally { setBusy(false) }
  }

  const onStatus = async (num, status) => {
    setBusy(true)
    try {
      await api.questionStatus(num, status)
      await load()
    } catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy(false) }
  }

  // Раздел — переписка владельца со мной; у роли «перегляд» его нет и в меню
  if (me && me.role === 'viewer') {
    return <div className="empty"><div className="big">Розділ лише для адміністратора</div></div>
  }

  const items = data?.items || []
  const waiting = items.filter(q => q.status === 'open')
  const rest = items.filter(q => q.status !== 'open')

  return (
    <>
      <div className="page-head">
        <h2>Питання до мене</h2>
        <p>
          Те саме, що я питаю в чаті, і під тими самими номерами — можна відповісти тут
          або написати «№{waiting[0]?.num ?? 5} — так» у чаті. Перед кожним звітом я читаю
          відповіді, що зʼявилися тут.
        </p>
      </div>

      <ApiError err={err} prefix="Питання не завантажено" />

      {!data && !err && <div className="skeleton sk-row" />}

      {data && !items.length && (
        <div className="empty"><div className="big">Питань немає</div>
          Нічого не чекає на ваше рішення.
        </div>
      )}

      {waiting.length > 0 && (
        <p className="muted small">Чекають на відповідь: {waiting.length}</p>
      )}
      {items.map(q => (
        <Question key={q.num} q={q} onAnswer={onAnswer} onStatus={onStatus} busy={busy} />
      ))}
      {rest.length > 0 && waiting.length === 0 && (
        <p className="muted small">Нічого не чекає на відповідь — нижче історія рішень.</p>
      )}
      {toast}
    </>
  )
}
