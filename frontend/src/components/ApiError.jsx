import React from 'react'
import { errorText } from '../api.js'

// Ошибка запроса словами. 404 объясняем отдельно: после сборки фронтенда
// новая вкладка появляется сразу, а её ручка — только после перезапуска
// сервера, и в этом окне «Not Found» — не поломка, а ожидание.
export default function ApiError({ err, prefix }) {
  if (!err) return null
  return (
    <div className="error-box">
      <b>{prefix || 'Не вдалося завантажити'}:</b> {errorText(err)}
      {err.status === 404 && err.message && err.message !== 'Not Found' && (
        <span className="muted"> ({err.message})</span>
      )}
    </div>
  )
}
