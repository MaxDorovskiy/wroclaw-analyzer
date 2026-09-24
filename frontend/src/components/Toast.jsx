import React, { useCallback, useEffect, useState } from 'react'

// Короткое уведомление внизу справа: «збережено», «прогін запущено».
// Хук отдаёт функцию flash и сам элемент — страница вставляет его в разметку.
export function useFlash(ms = 3500) {
  const [msg, setMsg] = useState(null)
  useEffect(() => {
    if (!msg) return undefined
    const t = setTimeout(() => setMsg(null), ms)
    return () => clearTimeout(t)
  }, [msg, ms])
  const flash = useCallback((text) => setMsg({ text, at: Date.now() }), [])
  const toast = msg ? <div className="toast" role="status" aria-live="polite">{msg.text}</div> : null
  return [flash, toast]
}
