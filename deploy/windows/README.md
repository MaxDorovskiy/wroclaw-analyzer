# Установка на Windows 11 (ПК с большим диском и Ollama)

1. Поставить: [Git for Windows](https://git-scm.com/download/win), [Python 3.11+](https://www.python.org/downloads/windows/) (галочка «Add to PATH»), [Node.js LTS](https://nodejs.org/) (для сборки интерфейса), Ollama (если ещё нет). Проверено 18.09.2026 на Python 3.14 и Node 24.
2. Клонировать репозиторий, например в `C:\dev\wroclaw-analyzer`.
3. `deploy\windows\env.example.ps1` → скопировать в `env.ps1` (он в `.gitignore`), вписать пароли и путь к данным (`WRO_DATA`) — на диске, который всегда подключён и где есть место.
4. PowerShell **от администратора** (задачи Планировщика с `RunLevel Highest` и правило брандмауэра иначе не создать):
   ```powershell
   cd C:\dev\wroclaw-analyzer
   powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1
   ```
   (или один раз `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, затем `.\deploy\windows\install.ps1`).
   Скрипт создаёт `.venv`, ставит зависимости и Chromium для Playwright, собирает фронтенд, регистрирует задачи Планировщика (`WroAnalyzer-Server`, `WroAnalyzer-Scrape-Sale-11`, `-17`, `WroAnalyzer-Scrape-Rent`), открывает порт 8020 в брандмауэре для домашней сети и запускает сервер.
   Без прав администратора: `install.ps1 -NoTasks` — всё, кроме задач и брандмауэра; сервер тогда поднимается руками: `powershell -ExecutionPolicy Bypass -File .\deploy\windows\server.ps1` (с `$env:WRO_HOST = "127.0.0.1"` в `env.ps1` — только для этого ПК).
5. Проверить источники **до первого прогона**: `.\.venv\Scripts\python.exe scripts\probe_sources.py` и то же с `--kind rent` (сырые ответы лягут в `%WRO_DATA%\probe`).
6. Открыть `http://localhost:8020` (с Mac — `http://<имя-ПК>:8020`), логин `admin`, пароль из `env.ps1`. В «Налаштуваннях» указать модель Ollama для перевода.
7. Первый прогон — кнопкой в разделе «Прогони» или `.\deploy\windows\scrape_trigger.ps1 -Kind sale -MaxJitterMin 0`.

Перезапуск после выкатки — только `.\deploy\windows\safe_restart.ps1` (откажется во время прогона; `-Wait` подождёт окна). Логи: `%WRO_DATA%\server.log` (ротация 20 МБ × 3), `trigger.log`, `uvicorn.err.log`, `server-restarts.log` (с кодом выхода uvicorn).

Задача сервера стартует при входе пользователя в систему: ПК не должен выходить из учётной записи (сон — нормально, задачи «AllowStartIfOnBatteries»). Если нужен старт без входа — в свойствах задачи поставить «Выполнять вне зависимости от регистрации пользователя» и ввести пароль Windows.

## Грабли Windows, на которые уже наступили (18.09.2026)

- **`.ps1` с кириллицей — только UTF-8 с BOM.** Windows PowerShell 5.1 читает файл без BOM в ANSI (cp1251), и байты 0x93/0x94 из UTF-8 («ф», «Д», тире «—») превращаются в «умные кавычки», которые парсер считает ограничителями строк: `install.ps1`, `safe_restart.ps1` и `scrape_trigger.ps1` не разбирались вообще. Редактор на Mac BOM молча срезает — за этим следит `tests/test_live_fixtures.py::test_windows_scripts_are_readable_by_powershell51`.
- **Параметр функции нельзя называть `$args`** — это автоматическая переменная, значение в неё не привязывается: задачи Планировщика создавались бы без `-File ...`.
- **Вывод Python в файл/конвейер — cp1251**, в ней нет «ł» и «²»: `print()` заголовка объявления ронял скрипт. В скриптах — `app.console.utf8_stdio()`, у сервера — `PYTHONUTF8=1` в `server.ps1`.
- `Start-Process -PassThru`: без обращения к `$p.Handle` код выхода после `WaitForExit()` пуст.
- `Get-Content f | Set-Content f` — «файл занят»; читать в скобках: `(Get-Content f) | Set-Content f`.
