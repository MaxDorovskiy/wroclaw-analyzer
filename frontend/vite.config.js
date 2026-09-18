import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Куда dev-сервер проксирует API. Боевой сервер Вроцлава слушает 8020, превью
// на копии базы — 8021 (docs/ARCHITECTURE.md §11). Правки положено смотреть на
// копии, поэтому обычный запуск такой:
//   VITE_API=http://127.0.0.1:8021 npm run dev -- --port 5175
const API = process.env.VITE_API || 'http://127.0.0.1:8020'

export default defineConfig({
  plugins: [react()],
  // Относительные пути к ассетам: index.html из frontend/dist должен
  // открываться и с корня сервера, и через file:// — так его проверяет
  // scripts/ui_check.py без сервера, на фикстурах.
  base: './',
  server: {
    port: 5175,
    proxy: { '/api': API },
  },
})
