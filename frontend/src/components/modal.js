import { useEffect, useRef } from 'react'

// Общее поведение всех окон поверх страницы: Esc закрывает, фокус уходит
// внутрь окна и возвращается туда, откуда открыли, Tab не убегает на страницу
// под окном (иначе с клавиатуры невозможно понять, где ты находишься).
// guard — функция: вернуть true, если закрывать сейчас нельзя (есть
// несохранённые правки); тогда закрытие спрашивает подтверждение.
export function useModal(onClose, guard) {
  const ref = useRef(null)
  const back = useRef(null)
  const close = useRef(onClose)
  const grd = useRef(guard)
  close.current = onClose
  grd.current = guard

  useEffect(() => {
    back.current = document.activeElement
    const box = ref.current
    if (box) {
      const first = box.querySelector('input, select, textarea, button, [href], [tabindex]:not([tabindex="-1"])')
      // не тащим фокус на крестик: первым нажатием Enter окно бы закрылось
      if (first && !first.classList.contains('close')) first.focus()
      else box.focus()
    }
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); tryClose() }
      if (e.key !== 'Tab' || !box) return
      const all = [...box.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter(el => el.offsetParent !== null)
      if (!all.length) return
      const [f, l] = [all[0], all[all.length - 1]]
      if (!e.shiftKey && document.activeElement === l) { e.preventDefault(); f.focus() }
      if (e.shiftKey && document.activeElement === f) { e.preventDefault(); l.focus() }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      if (back.current && back.current.focus) back.current.focus()
    }
  }, [])

  const tryClose = () => {
    if (grd.current && grd.current()) {
      if (!window.confirm('Є незбережені правки. Закрити без збереження?')) return
    }
    close.current()
  }

  // props для .overlay: клик мимо окна закрывает — но так же спрашивает
  const overlay = {
    onMouseDown: (e) => { if (e.target === e.currentTarget) tryClose() },
  }
  return { ref, overlay, close: tryClose }
}
