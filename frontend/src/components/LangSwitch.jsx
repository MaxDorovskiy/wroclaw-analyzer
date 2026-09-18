import React from 'react'
import { useLang, LANG_MODES } from '../i18n.js'

// «оригінал (PL) / переклад (UK) / обидва» — в шапке, действует на таблицы,
// карточку и списки осиедле. Выбор запоминается в localStorage (i18n.js).
export default function LangSwitch() {
  const { lang, setLang } = useLang()
  return (
    <span className="lang-switch" title="Мова показу оголошень: оригінал польською, переклад українською або обидва разом">
      {LANG_MODES.map(([id, name]) => (
        <button key={id} type="button" className={lang === id ? 'on' : ''}
          onClick={() => setLang(id)}>{name}</button>
      ))}
    </span>
  )
}
