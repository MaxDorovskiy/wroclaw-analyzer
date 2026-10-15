import React from 'react'
import Catalog from './Catalog.jsx'

// Готовые выборки «Вигідних». Знижка считается против медианы пула похожих
// (docs/ARCHITECTURE.md §6), дохідність — валовая, от ставок оренди поруч.
// «Нові за добу зі знижкою»: only_deals=1 (порог сервера deal_threshold_pct)
// + first_seen_days=1 — этого параметра в docs/API.md нет, имя предположено.
// thin_base=exclude — без «тонкой базы» (6-9 похожих): карточка сама помечает
// такую скидку серым как ненадёжную; в каталоге с сортировкой по скидке они есть.
export const PRESETS = [
  ['d10', 'Знижка ≥ 10%', { discount_min: 10, thin_base: 'exclude', sort: 'discount', order: 'desc' }],
  ['d15', 'Знижка ≥ 15%', { discount_min: 15, thin_base: 'exclude', sort: 'discount', order: 'desc' }],
  ['new24', 'Нові за добу зі знижкою', { only_deals: 1, thin_base: 'exclude', first_seen_days: 1, sort: 'first_seen', order: 'desc' }],
  ['y6', 'Дохідність ≥ 6%', { yield_min: 6, sort: 'yield', order: 'desc' }],
]

export default function Deals({ onOpen, urlParams, onParams, geo, sel, onSel }) {
  const current = PRESETS.find(p => p[0] === urlParams?.preset) || PRESETS[0]
  const [key, , params] = current
  return (
    <>
      <div className="presets">
        {PRESETS.map(([k, name]) => (
          <button key={k} type="button" className={'chip' + (k === key ? ' on' : '')}
            onClick={() => onParams({ preset: k })}>{name}</button>
        ))}
      </div>
      {/* key — чтобы каталог перемонтировался и взял новый пресет: свои
          фильтры он держит в состоянии и от пропсов уже не зависит */}
      <Catalog key={key} onOpen={onOpen} preset={params} geo={geo} sel={sel} onSel={onSel}
        urlParams={urlParams} onParams={p => onParams({ ...p, preset: key })} />
    </>
  )
}
