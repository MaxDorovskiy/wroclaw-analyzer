import React from 'react'
import Catalog from './Catalog.jsx'

// Готовые выборки «Вигідних». Знижка считается против медианы пула похожих
// (docs/ARCHITECTURE.md §6), дохідність — валовая, от ставок оренди поруч.
// «Нові за добу зі знижкою»: only_deals=1 (порог сервера deal_threshold_pct)
// + first_seen_days=1 — этого параметра в docs/API.md нет, имя предположено.
export const PRESETS = [
  ['d10', 'Знижка ≥ 10%', { discount_min: 10, sort: 'discount', order: 'desc' }],
  ['d15', 'Знижка ≥ 15%', { discount_min: 15, sort: 'discount', order: 'desc' }],
  ['new24', 'Нові за добу зі знижкою', { only_deals: 1, first_seen_days: 1, sort: 'first_seen', order: 'desc' }],
  ['y6', 'Дохідність ≥ 6%', { yield_min: 6, sort: 'yield', order: 'desc' }],
]

export default function Deals({ onOpen, urlParams, onParams, geo }) {
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
      <Catalog key={key} onOpen={onOpen} preset={params} geo={geo}
        urlParams={urlParams} onParams={p => onParams({ ...p, preset: key })} />
    </>
  )
}
