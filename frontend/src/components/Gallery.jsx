import React, { useEffect, useRef, useState } from 'react'

// Фото объявления: одно большое, листается стрелками (кнопки, клавиши ←/→,
// свайп на телефоне), снизу лента миниатюр. Раньше это была полоса
// миниатюр, и каждая открывала фото НОВОЙ вкладкой — просмотреть 20 фото
// значило 20 раз уйти со страницы и вернуться.
export default function Gallery({ images }) {
  const [i, setI] = useState(0)
  const [broken, setBroken] = useState({})
  const stripRef = useRef(null)
  const touchX = useRef(null)
  const n = (images || []).length

  // новое объявление в том же окне карточки — начинаем с первого фото
  useEffect(() => { setI(0); setBroken({}) }, [images])

  const go = (d) => setI(x => (x + d + n) % n)

  // Стрелки работают, пока открыта карточка. Esc ловит сама карточка, здесь
  // его не трогаем. Если фокус в поле ввода (заметка, осиедле) — не мешаем.
  useEffect(() => {
    if (n < 2) return undefined
    const onKey = (e) => {
      const t = e.target.tagName
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT') return
      if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1) }
      if (e.key === 'ArrowRight') { e.preventDefault(); go(1) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [n])

  // активная миниатюра всегда видна в ленте
  useEffect(() => {
    const strip = stripRef.current
    const el = strip && strip.children[i]
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [i])

  if (!n) return null
  const src = images[i]

  return (
    <div className="gallery">
      <div className="gal-main"
        onTouchStart={e => { touchX.current = e.changedTouches[0].clientX }}
        onTouchEnd={e => {
          const dx = e.changedTouches[0].clientX - (touchX.current ?? 0)
          if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1)
        }}>
        {broken[i]
          ? <div className="gal-broken">Фото недоступне на джерелі</div>
          : <img src={src} alt="" onError={() => setBroken(b => ({ ...b, [i]: true }))} />}
        {n > 1 && (
          <>
            <button type="button" className="gal-nav prev" onClick={() => go(-1)} title="Попереднє фото (←)">‹</button>
            <button type="button" className="gal-nav next" onClick={() => go(1)} title="Наступне фото (→)">›</button>
          </>
        )}
        <span className="gal-count">{i + 1} / {n}</span>
      </div>
      {n > 1 && (
        <div className="gal-strip" ref={stripRef}>
          {images.map((s, k) => (
            <img key={k} src={s} loading="lazy" alt=""
              className={k === i ? 'on' : ''} onClick={() => setI(k)} />
          ))}
        </div>
      )}
    </div>
  )
}
