import React, { useState } from 'react'
import { api, saveBlob, errorText } from '../api.js'
import { useFlash } from './Toast.jsx'

// Панель внизу екрана, поки щось вибрано галочками, і вікно збирання PDF.
// Підбірка — це те, що ріелтор надсилає клієнту: тому мова на вибір
// (клієнту-українцю переклад, клієнту-поляку оригінал з площадки) і контакти
// в файлі — ТОГО, ХТО надсилає, а не продавця оголошення.
export default function SelectionBar({ ids, onClear, profile, onEditProfile }) {
  const [open, setOpen] = useState(false)
  const [lang, setLang] = useState(null)      // null — ще не чіпали, беремо з візитки
  const [title, setTitle] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [flash, toast] = useFlash()
  const n = ids.length
  if (!n) return toast

  const effLang = lang || profile?.pres_lang || 'uk'
  const noContacts = !profile?.phone && !profile?.email

  const make = async () => {
    setBusy(true)
    try {
      const { blob, filename } = await api.presentation({
        ids, lang: effLang, title: title.trim() || undefined, comment: comment.trim() || undefined,
      })
      saveBlob(blob, filename)
      flash(`PDF зібрано: ${n} об'єкт(ів)`)
      setOpen(false)
    } catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy(false) }
  }

  return (
    <>
      <div className="selbar">
        <b>Вибрано: {n}</b>
        <span className="muted small">галочки в таблиці</span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => setOpen(true)}>Презентація PDF</button>
        <button className="btn ghost" onClick={onClear}>Скинути вибір</button>
      </div>

      {open && (
        <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) setOpen(false) }}>
          <div className="modal narrow">
            <button className="close" onClick={() => setOpen(false)} title="Закрити">×</button>
            <h2>Презентація для клієнта</h2>
            <p className="muted">{n} об'єкт(ів). У файлі будуть фото, параметри, опис і ваші контакти.</p>

            <div className="form-grid">
              <div>
                <label>Мова презентації</label>
                <select value={effLang} onChange={e => setLang(e.target.value)}>
                  <option value="uk">українська (переклад)</option>
                  <option value="pl">польська (оригінал з площадки)</option>
                </select>
                <div className="hint">
                  {effLang === 'uk'
                    ? 'Те, що ще не перекладено, перекладемо просто зараз — на кожне таке оголошення кілька секунд.'
                    : 'Беремо тексти як на площадці — для клієнта-поляка, переклад не потрібен.'}
                </div>
              </div>
              <div>
                <label>Заголовок (необов'язково)</label>
                <input value={title} onChange={e => setTitle(e.target.value)}
                  placeholder={effLang === 'uk' ? 'Підбірка квартир' : 'Wybrane mieszkania'} />
              </div>
              <div style={{ gridColumn: 'span 2' }}>
                <label>Коментар клієнту (необов'язково)</label>
                <textarea rows={2} value={comment} onChange={e => setComment(e.target.value)}
                  placeholder="Пані Олено, ось три варіанти біля Placu Grunwaldzkiego…" />
              </div>
            </div>

            <div className="panel" style={{ marginTop: 12 }}>
              <b>Контакти у файлі</b>
              <div className="muted small" style={{ marginTop: 4 }}>
                {profile?.display_name || profile?.user}
                {profile?.agency ? ` · ${profile.agency}` : ''}
                {profile?.phone ? ` · ${profile.phone}` : ''}
                {profile?.email ? ` · ${profile.email}` : ''}
              </div>
              {noContacts && (
                <div className="hint" style={{ marginTop: 6 }}>
                  Телефон і пошту ще не заповнено — клієнт не зрозуміє, кому дзвонити.{' '}
                  <a onClick={() => { setOpen(false); onEditProfile && onEditProfile() }}
                    style={{ cursor: 'pointer' }}>Заповнити візитку →</a>
                </div>
              )}
            </div>

            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" disabled={busy} onClick={make}>
                {busy ? <span className="spin" /> : null}{busy ? 'Збираю PDF…' : 'Завантажити PDF'}
              </button>
              <button className="btn ghost" onClick={() => setOpen(false)}>Скасувати</button>
              <span className="muted small">
                Фото тягнуться з площадок{effLang === 'uk' ? ', неперекладене перекладається' : ''} —
                зазвичай кілька секунд.
              </span>
            </div>
          </div>
        </div>
      )}
      {toast}
    </>
  )
}
