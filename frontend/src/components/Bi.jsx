import React from 'react'
import { useLang, pickBi } from '../i18n.js'

// Двуязычная строка: заголовок, название осиедле, значение характеристики.
// Режим показа общий на весь интерфейс (переключатель в шапке), поэтому
// компонент берёт его из контекста, а не из пропсов. В режиме «обидва» —
// перевод, а под ним оригинал мелким серым; перевода нет — оригинал с
// пометкой, чтобы непереведённое было видно и попадало в очередь перевода.
export default function Bi({ pl, uk, strong = false, sub = true }) {
  const { lang } = useLang()
  const p = pickBi(lang, pl, uk)
  if (!p.main) return <span className="muted">—</span>
  return (
    <span className="bi">
      {strong ? <b className="bi-main">{p.main}</b> : <span className="bi-main">{p.main}</span>}
      {p.untranslated && (
        <span className="badge gray bi-flag" title="Перекладу ще немає — показано оригінал">
          не перекладено
        </span>
      )}
      {sub && p.sub && <span className="bi-sub">{p.sub}</span>}
    </span>
  )
}
