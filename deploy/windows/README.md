# Установка на Windows 11 (ПК с большим диском и Ollama)

1. Поставить: [Git for Windows](https://git-scm.com/download/win), [Python 3.11+](https://www.python.org/downloads/windows/) (галочка «Add to PATH»), [Node.js LTS](https://nodejs.org/) (для сборки интерфейса), Ollama (если ещё нет).
2. Клонировать репозиторий, например в `C:\dev\flatfy-analyzer`, перейти в `wroclaw-analyzer`.
3. `deploy\windows\env.example.ps1` → скопировать в `env.ps1`, вписать пароль и путь к данным на большом диске (`D:\wro-data`).
4. PowerShell от администратора:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   cd C:\dev\flatfy-analyzer\wroclaw-analyzer
   .\deploy\windows\install.ps1
   ```
   Скрипт создаёт `.venv`, ставит зависимости и Chromium для Playwright, собирает фронтенд, регистрирует задачи Планировщика (`WroAnalyzer-Server`, `WroAnalyzer-Scrape-Sale-11`, `-17`, `WroAnalyzer-Scrape-Rent`), открывает порт 8020 в брандмауэре для домашней сети и запускает сервер.
5. Проверить источники **до первого прогона**: `.\.venv\Scripts\python.exe scripts\probe_sources.py` (сырые ответы лягут в `%WRO_DATA%\probe`).
6. Открыть `http://localhost:8020` (с Mac — `http://<имя-ПК>:8020`), логин `admin`, пароль из `env.ps1`. В «Налаштуваннях» указать модель Ollama для перевода.
7. Первый прогон — кнопкой в разделе «Прогони» или `.\deploy\windows\scrape_trigger.ps1 -Kind sale -MaxJitterMin 0`.

Перезапуск после выкатки — только `.\deploy\windows\safe_restart.ps1` (откажется во время прогона; `-Wait` подождёт окна). Логи: `%WRO_DATA%\server.log` (ротация 20 МБ × 3), `trigger.log`, `uvicorn.err.log`.

Задача сервера стартует при входе пользователя в систему: ПК не должен выходить из учётной записи (сон — нормально, задачи «AllowStartIfOnBatteries»). Если нужен старт без входа — в свойствах задачи поставить «Выполнять вне зависимости от регистрации пользователя» и ввести пароль Windows.
