import React from 'react'
import Catalog from './Catalog.jsx'

// Дома (решение владельца №12, 03.11.2026): отдельные типы сделки house_sale /
// house_rent. Скидку и доходность для них не считаем — цена дома зависит от
// участка и типа застройки, и сравнивать её с квартирами за м² нельзя.
// Режим живёт в адресе (#/houses?mode=rent), каталог перемонтируется по ключу:
// свои фильтры он держит в состоянии.
const MODES = [['sale', 'Продаж'], ['rent', 'Оренда']]

export default function Houses({ onOpen, urlParams, onParams, geo, sel, onSel }) {
  const mode = urlParams?.mode === 'rent' ? 'rent' : 'sale'
  const rent = mode === 'rent'
  return (
    <>
      <div className="presets">
        {MODES.map(([k, name]) => (
          <button key={k} type="button" className={'chip' + (k === mode ? ' on' : '')}
            onClick={() => onParams({ mode: k })}>{name}</button>
        ))}
        <span className="muted" style={{ alignSelf: 'center' }}>
          Площа — будинку; ділянка — у картці. Знижку до ринку для будинків не рахуємо.
        </span>
      </div>
      <Catalog key={mode} offerType={rent ? 'house_rent' : 'house_sale'} rent={rent} scores={false}
        onOpen={onOpen} geo={geo} sel={sel} onSel={onSel}
        urlParams={urlParams} onParams={p => onParams({ ...p, mode })} />
    </>
  )
}
