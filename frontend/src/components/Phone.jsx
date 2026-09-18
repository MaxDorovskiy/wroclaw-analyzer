import React, { useEffect, useState } from 'react'
import { copyText } from '../api.js'

// Телефон продавца: ссылка tel: (с телефона звонок в один тап) и кнопка
// «копіювати» (с компьютера номер уходит в мессенджер). stopPropagation —
// компонент стоит в кликабельных строках, и клик по номеру не должен
// открывать каталог продавца.
export default function Phone({ value }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return undefined
    const t = setTimeout(() => setCopied(false), 1500)
    return () => clearTimeout(t)
  }, [copied])
  if (!value) return null
  const digits = String(value).replace(/[^\d+]/g, '')
  return (
    <span className="phone" onClick={e => e.stopPropagation()} style={{ whiteSpace: 'nowrap' }}>
      <a href={'tel:' + digits} className="mono" title="Подзвонити">{value}</a>
      <button type="button" className="btn ghost small" style={{ marginLeft: 6 }}
        title="Скопіювати номер"
        onClick={async () => setCopied(await copyText(String(value)))}>
        {copied ? '✓ скопійовано' : 'копіювати'}
      </button>
    </span>
  )
}
