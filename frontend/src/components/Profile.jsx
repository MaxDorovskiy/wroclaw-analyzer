import React, { useState } from 'react'
import { api, errorText } from '../api.js'
import { useFlash } from './Toast.jsx'

// Візитка ріелтора: ім'я, телефон, пошта, агентство. Підставляється в
// PDF-підбірку, яку надсилають клієнту. У кожного логіна своя — у підбірці
// Юлії має бути її телефон, а не власника; чужу візитку сервер не віддає.
export default function Profile({ profile, onSaved, onClose }) {
  const [f, setF] = useState({
    display_name: profile?.display_name || '',
    phone: profile?.phone || '',
    email: profile?.email || '',
    agency: profile?.agency || '',
    about: profile?.about || '',
    pres_lang: profile?.pres_lang || 'uk',
  })
  const [busy, setBusy] = useState(false)
  const [flash, toast] = useFlash()
  const set = (k, v) => setF({ ...f, [k]: v })

  const save = async () => {
    setBusy(true)
    try {
      const d = await api.profileSave(f)
      onSaved && onSaved(d)
      flash('Візитку збережено')
      setTimeout(() => onClose && onClose(), 500)
    } catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy(false) }
  }

  return (
    <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal narrow">
        <button className="close" onClick={onClose} title="Закрити">×</button>
        <h2>Моя візитка</h2>
        <p className="muted">
          Ці контакти підставляються в PDF-підбірку для клієнта. Логін: <b>{profile?.user}</b>.
        </p>
        <div className="form-grid">
          <div>
            <label>Ім'я для клієнта</label>
            <input value={f.display_name} onChange={e => set('display_name', e.target.value)}
              placeholder="Юлія Коваленко" />
          </div>
          <div>
            <label>Телефон</label>
            <input value={f.phone} onChange={e => set('phone', e.target.value)}
              placeholder="+48 600 100 200" />
          </div>
          <div>
            <label>Пошта</label>
            <input value={f.email} onChange={e => set('email', e.target.value)}
              placeholder="yulia@example.com" />
          </div>
          <div>
            <label>Агентство / посада</label>
            <input value={f.agency} onChange={e => set('agency', e.target.value)}
              placeholder="Оренда квартир у Вроцлаві" />
          </div>
          <div>
            <label>Мова презентації за замовчуванням</label>
            <select value={f.pres_lang} onChange={e => set('pres_lang', e.target.value)}>
              <option value="uk">українська</option>
              <option value="pl">польська</option>
            </select>
            <div className="hint">У вікні збирання PDF мову можна змінити для кожної підбірки</div>
          </div>
          <div style={{ gridColumn: 'span 2' }}>
            <label>Рядок під контактами (необов'язково)</label>
            <input value={f.about} onChange={e => set('about', e.target.value)}
              placeholder="Допомагаю з орендою: підбір, перегляди, договір" />
          </div>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" disabled={busy} onClick={save}>
            {busy ? <span className="spin" /> : null}Зберегти
          </button>
          <button className="btn ghost" onClick={onClose}>Закрити</button>
        </div>
        {toast}
      </div>
    </div>
  )
}
