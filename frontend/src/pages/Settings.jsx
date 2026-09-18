import React, { useEffect, useState } from 'react'
import { api, SECRET_MASK, errorText } from '../api.js'
import { T } from '../i18n.js'
import ApiError from '../components/ApiError.jsx'
import { useFlash } from '../components/Toast.jsx'

// Известные ключи с подписями. Всё, что сервер прислал сверх этого, показываем
// текстовыми полями в конце: новая настройка на сервере не должна ждать
// правки фронтенда. Новый ключ сохранится только если он внесён в SAFE_KEYS
// на сервере — иначе поле молча ничего не сделает (об этом предупреждаем).
const SECTIONS = [
  ['Переклад', [
    { key: 'translate_enabled', label: 'Автопереклад після прогону', type: 'select', options: T.onOff, hint: 'черга перекладається окремим потоком після кожного прогону; кнопки «Перекласти чергу» і «Перекласти» в картці працюють завжди' },
    { key: 'translate_provider', label: 'Провайдер перекладу', type: 'select', options: T.provider },
    { key: 'translate_ollama_url', label: 'Ollama: адреса', hint: 'наприклад http://127.0.0.1:11434' },
    { key: 'translate_ollama_model', label: 'Ollama: модель' },
    { key: 'translate_ollama_num_ctx', label: 'Ollama: вікно контексту', type: 'number', hint: 'якщо цю саму модель уже тримає в памʼяті інша система — поставте її значення (колонка CONTEXT в «ollama ps»), інакше модель перезавантажується на кожен запит (15–25 с)' },
    { key: 'translate_anthropic_model', label: 'Anthropic: модель' },
    { key: 'translate_anthropic_key', label: 'Anthropic: ключ API', secret: true },
    { key: 'translate_google_key', label: 'Google Translate: ключ', secret: true },
    { key: 'translate_deepl_key', label: 'DeepL: ключ', secret: true },
    { key: 'translate_daily_cap', label: 'Описів на добу, не більше', type: 'number', hint: 'заголовки перекладаються всі, описи — з лімітом' },
  ]],
  ['Аналітика', [
    { key: 'deal_threshold_pct', label: 'Поріг вигідності, %', type: 'number', hint: 'від якої знижки оголошення вважається вигідним (only_deals)' },
    { key: 'renovation_cost_sqm_pln', label: 'Оздоблення, zł/м²', type: 'number', hint: 'додається до ціни у вкладення для «стан від забудовника» і «під ремонт»' },
  ]],
  ['Джерела', [
    { key: 'olx_category_sale', label: 'OLX: категорія продажу' },
    { key: 'olx_category_rent', label: 'OLX: категорія оренди' },
    { key: 'olx_city_id', label: 'OLX: id міста' },
    { key: 'fetch_mode', label: 'Спосіб завантаження', type: 'select', options: T.fetchMode },
    { key: 'requests_per_minute', label: 'Запитів на хвилину', type: 'number', hint: 'не більше 15 — інакше бан за сплеск з домашнього IP' },
  ]],
  ['Інше', [
    { key: 'public_url', label: 'Публічна адреса', hint: 'для посилань у повідомленнях' },
  ]],
]
const KNOWN = new Set(SECTIONS.flatMap(([, f]) => f.map(x => x.key)))

export default function Settings() {
  const [s, setS] = useState(null)
  const [orig, setOrig] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [flash, toast] = useFlash()

  useEffect(() => {
    api.settings().then(d => { setS(d); setOrig(d); setErr(null) }).catch(setErr)
  }, [])

  const set = (k, v) => setS({ ...s, [k]: v })

  const save = async () => {
    setBusy(true)
    try {
      // Секреты с заглушкой обратно не шлём — иначе ключ на сервере затёрся
      // бы точками. Нетронутые поля тоже не шлём: меньше шума в журнале.
      const body = {}
      for (const [k, v] of Object.entries(s)) {
        if (v === SECRET_MASK) continue
        if (orig && orig[k] === v) continue
        body[k] = v
      }
      if (!Object.keys(body).length) { flash('Нічого не змінилося'); return }
      const r = await api.settingsSave(body)
      const saved = r.saved || []
      const rejected = Object.keys(body).filter(k => !saved.includes(k))
      flash(rejected.length
        ? `Збережено ${saved.length}; сервер не прийняв: ${rejected.join(', ')} (немає в SAFE_KEYS)`
        : `Збережено: ${saved.length}`)
      const fresh = await api.settings()
      setS(fresh); setOrig(fresh)
    } catch (e) { flash('❌ ' + errorText(e)) }
    finally { setBusy(false) }
  }

  const field = (f) => {
    const v = s[f.key] ?? ''
    if (f.type === 'select') {
      return (
        <select value={v} onChange={e => set(f.key, e.target.value)}>
          {!(f.options[v]) && <option value={v}>{v || '—'}</option>}
          {Object.entries(f.options).map(([k, name]) => <option key={k} value={k}>{name}</option>)}
        </select>
      )
    }
    const secret = f.secret || v === SECRET_MASK
    return (
      <input type={secret ? 'password' : (f.type || 'text')} value={v}
        placeholder={v === SECRET_MASK ? 'не змінювати' : (secret ? 'не задано' : '')}
        onFocus={secret && v === SECRET_MASK ? () => set(f.key, '') : undefined}
        onChange={e => set(f.key, f.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)} />
    )
  }

  if (err) return <ApiError err={err} prefix="Налаштування не завантажено" />
  if (!s) return <p className="muted"><span className="spin" />Завантаження…</p>
  const extra = Object.keys(s).filter(k => !KNOWN.has(k)).sort()

  return (
    <>
      {SECTIONS.map(([title, fields]) => (
        <div className="panel" key={title}>
          <h3>{title}</h3>
          <div className="form-grid">
            {fields.map(f => (
              <div key={f.key}>
                <label title={f.key}>{f.label}</label>
                {field(f)}
                {f.hint && <div className="hint">{f.hint}</div>}
              </div>
            ))}
          </div>
        </div>
      ))}
      {extra.length > 0 && (
        <div className="panel">
          <h3>Інші ключі</h3>
          <p className="muted small">Прийшли з сервера, підпису для них ще немає. Збережуться, лише якщо ключ є в SAFE_KEYS.</p>
          <div className="form-grid">
            {extra.map(k => (
              <div key={k}>
                <label className="mono">{k}</label>
                {field({ key: k })}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="row">
        <button className="btn" disabled={busy} onClick={save}>{busy ? <span className="spin" /> : null}Зберегти</button>
        <span className="muted small">Секрети показані як {SECRET_MASK}: щоб замінити — клацніть у поле і впишіть новий; порожнє поле з крапками назад не відправляється</span>
      </div>
      {toast}
    </>
  )
}
