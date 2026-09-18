import React, { useEffect, useMemo, useRef, useState } from 'react'

// Раскрывающийся список с автодополнением и множественным выбором.
// value — строка выбранных значений через запятую (так их ждёт API:
// `district`, `osiedle`, `condition` — «через запятую»). options: [{value, label, hint?}].
export default function MultiSelect({ value, onChange, options, placeholder, width = 200 }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const rootRef = useRef(null)
  const inputRef = useRef(null)

  const selected = (value || '').split(',').filter(Boolean)

  useEffect(() => {
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (options || [])
      .filter(o => !selected.includes(o.value))
      .filter(o => !needle || o.label.toLowerCase().includes(needle)
        || String(o.value).toLowerCase().includes(needle))
      .slice(0, 60)
  }, [options, q, value])

  const commit = (vals) => onChange(vals.join(','))
  const add = (v) => { commit([...selected, v]); setQ(''); setHi(0); inputRef.current?.focus() }
  const remove = (v) => commit(selected.filter(x => x !== v))
  const label = (v) => (options || []).find(o => o.value === v)?.label || v

  const onKey = (e) => {
    if (e.key === 'ArrowDown') { setOpen(true); setHi(h => Math.min(h + 1, filtered.length - 1)); e.preventDefault() }
    else if (e.key === 'ArrowUp') { setHi(h => Math.max(h - 1, 0)); e.preventDefault() }
    else if (e.key === 'Enter') { if (open && filtered[hi]) { add(filtered[hi].value); e.preventDefault() } }
    else if (e.key === 'Escape') setOpen(false)
    else if (e.key === 'Backspace' && !q && selected.length) remove(selected[selected.length - 1])
  }

  return (
    <div className={'ms' + (open ? ' open' : '')} ref={rootRef} style={{ minWidth: width }}
      onClick={() => { setOpen(true); inputRef.current?.focus() }}>
      {selected.map(v => (
        <span className="ms-chip" key={v}>
          {label(v)}
          <button type="button" className="ms-x" title="Прибрати"
            onClick={(e) => { e.stopPropagation(); remove(v) }}>×</button>
        </span>
      ))}
      <input ref={inputRef} value={q}
        placeholder={selected.length ? '' : placeholder}
        onChange={e => { setQ(e.target.value); setOpen(true); setHi(0) }}
        onFocus={() => setOpen(true)} onKeyDown={onKey} />
      {open && filtered.length > 0 && (
        <div className="ms-drop">
          {filtered.map((o, i) => (
            <div key={o.value} className={'ms-opt' + (i === hi ? ' hi' : '')}
              onMouseEnter={() => setHi(i)}
              onMouseDown={(e) => { e.preventDefault(); add(o.value) }}>
              <span>{o.label}</span>
              {o.hint != null && <span className="hint" title="активних оголошень">{o.hint}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
