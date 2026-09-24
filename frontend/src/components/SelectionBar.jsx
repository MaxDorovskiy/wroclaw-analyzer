import React, { useState } from 'react'
import { api, saveBlob, errorText } from '../api.js'
import { useFlash } from './Toast.jsx'
import { useModal } from './modal.js'

// Панель внизу екрана, поки щось вибрано галочками, і вікно збирання PDF.
// Підбірка — це те, що ріелтор надсилає клієнту: тому мова на вибір
// (клієнту-українцю переклад, клієнту-поляку оригінал з площадки) і контакти
// в файлі — ТОГО, ХТО надсилає, а не продавця оголошення.

// Вынесено отдельным компонентом, а не веткой `{open && ...}`: окну нужны
// свои хуки (Esc, ловушка фокуса), а хук нельзя звать под условием.
function PresDialog({ ids, profile, onClose, onEditProfile, flash }) {
  const [lang, setLang] = useState(null)      // null — ще не чіпали, беремо з візитки
  const [title, setTitle] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const modal = useModal(onClose)
  const n = ids.length
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
      onClose()
    } catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy(false) }
  }

  return (
    <div className="overlay" {...modal.overlay}>
      <div className="modal narrow" ref={modal.ref} role="dialog" aria-modal="true" aria-labelledby="pres-h" tabIndex={-1}>
        <button className="close" onClick={modal.close} title="Закрити (Esc)" aria-label="Закрити">×</button>
        <h2 id="pres-h">Презентація для клієнта</h2>
        <p className="muted">{n} об'єкт(ів). У файлі будуть фото, параметри, опис і ваші контакти.</p>

        <div className="form-grid">
          <div>
            <label htmlFor="pres-lang">Мова презентації</label>
            <select id="pres-lang" value={effLang} onChange={e => setLang(e.target.value)}>
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
            <label htmlFor="pres-title">Заголовок (необов'язково)</label>
            <input id="pres-title" value={title} onChange={e => setTitle(e.target.value)}
              placeholder={effLang === 'uk' ? 'Підбірка квартир' : 'Wybrane mieszkania'} />
          </div>
          <div style={{ gridColumn: 'span 2' }}>
            <label htmlFor="pres-note">Коментар клієнту (необов'язково)</label>
            <textarea id="pres-note" rows={2} value={comment} onChange={e => setComment(e.target.value)}
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
              <button type="button" className="linkbtn"
                onClick={() => { onClose(); onEditProfile && onEditProfile() }}>Заповнити візитку →</button>
            </div>
          )}
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={busy} onClick={make}>
            {busy ? <span className="spin" /> : null}{busy ? 'Збираю PDF…' : 'Завантажити PDF'}
          </button>
          <button className="btn ghost" onClick={onClose}>Скасувати</button>
          <span className="muted small">
            Фото тягнуться з площадок{effLang === 'uk' ? ', неперекладене перекладається' : ''} —
            зазвичай кілька секунд.
          </span>
        </div>
      </div>
    </div>
  )
}

export default function SelectionBar({ ids, onClear, profile, onEditProfile }) {
  const [open, setOpen] = useState(false)
  const [flash, toast] = useFlash()
  const n = ids.length
  if (!n) return toast

  return (
    <>
      <div className="selbar" role="region" aria-label="Вибрані оголошення">
        <b>Вибрано: {n}</b>
        <span className="muted small">галочки в таблиці</span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => setOpen(true)}>Презентація PDF</button>
        <button className="btn ghost" onClick={onClear}>Скинути вибір</button>
      </div>

      {open && (
        <PresDialog ids={ids} profile={profile} flash={flash}
          onClose={() => setOpen(false)} onEditProfile={onEditProfile} />
      )}
      {toast}
    </>
  )
}
