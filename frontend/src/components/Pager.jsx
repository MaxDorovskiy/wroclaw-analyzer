import React from 'react'
import { fmtNum } from '../api.js'

// Сколько строк на странице. Верхняя граница 200 — столько же в контракте
// (`per_page ≤ 200`): просить больше бесполезно, сервер молча урежет, а
// пользователь решит, что страница потеряла записи.
const SIZES = [25, 50, 100, 200]

// Листалка со счётчиком. Стоит и НАД таблицей, и под ней: вопрос «сколько
// вообще найдено» возникает в первую секунду, ещё наверху.
export default function Pager({ page, perPage, total, onPage, onPerPage, top }) {
  const per = perPage || 50
  const pages = Math.max(1, Math.ceil((total || 0) / per))
  const p = Math.min(Math.max(1, page || 1), pages)
  const from = total ? (p - 1) * per + 1 : 0
  const to = Math.min(total || 0, p * per)

  // Смена размера страницы держит в виду ту же первую строку, а не
  // выбрасывает в начало списка.
  const changeSize = (v) => {
    const first = (p - 1) * per
    onPerPage(v, Math.floor(first / v) + 1)
  }

  return (
    <div className={'pager' + (top ? ' pager-top' : '')}>
      <button className="btn ghost small" disabled={p <= 1} onClick={() => onPage(p - 1)}>←</button>
      <span>стор. {fmtNum(p)} з {fmtNum(pages)}</span>
      <button className="btn ghost small" disabled={p >= pages} onClick={() => onPage(p + 1)}>→</button>
      <span className="pager-count">
        {total ? `показано ${fmtNum(from)}–${fmtNum(to)} з ${fmtNum(total)}` : 'нічого не знайдено'}
      </span>
      {onPerPage ? (
        <span className="pager-size">
          на сторінці:
          {SIZES.map(v => (
            <button key={v} className={'btn' + (v === per ? '' : ' ghost')}
              onClick={() => changeSize(v)}>{v}</button>
          ))}
        </span>
      ) : null}
    </div>
  )
}
