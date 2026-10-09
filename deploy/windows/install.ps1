# Установка на Windows 11: venv, зависимости, сборка фронтенда, задачи
# Планировщика, правило брандмауэра. Запускать из PowerShell от имени
# администратора (для задач и брандмауэра):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   .\deploy\windows\install.ps1
# -NoTasks   — только зависимости и сборка, задачи не трогать
# -TasksOnly — только задачи и брандмауэр: переставлять работающие зависимости
#              ради правки расписания — лишний риск
param([switch]$NoTasks, [switch]$TasksOnly)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
if (-not (Test-Path (Join-Path $PSScriptRoot "env.ps1"))) {
    Copy-Item (Join-Path $PSScriptRoot "env.example.ps1") (Join-Path $PSScriptRoot "env.ps1")
    Write-Host "Создан deploy\windows\env.ps1 — впишите пароль и путь к данным, затем запустите скрипт снова" -ForegroundColor Yellow
    exit 1
}
. (Join-Path $PSScriptRoot "env.ps1")
if (-not $TasksOnly) {
if (-not (Test-Path ".venv")) { py -3 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
if (Get-Command npm -ErrorAction SilentlyContinue) {
    Push-Location frontend; npm install; npm run build; Pop-Location
} else {
    Write-Host "npm не найден — поставьте Node.js LTS и выполните: cd frontend; npm install; npm run build" -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force -Path $env:WRO_DATA | Out-Null
}
if ($NoTasks) { exit 0 }
# Права проверяем ДО того, как остановить сервер: Register-ScheduledTask без
# администратора падает с Access is denied, и 09.10.2026 скрипт успел погасить
# сайт и на этом остановиться — сайт лежал, пока его не подняли руками.
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($me)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "НУЖНЫ ПРАВА АДМИНИСТРАТОРА: задачи Планировщика и правило брандмауэра иначе не создать." -ForegroundColor Red
    Write-Host "Сервер НЕ тронут. Запустите PowerShell от имени администратора и повторите." -ForegroundColor Yellow
    exit 1
}
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
# Сервер уже может работать: поднят вручную (server.ps1 без Планировщика — так прошла
# первая установка 18.09.2026) или остался от прошлой установки: Unregister-ScheduledTask
# запущенный экземпляр не останавливает. Порт был бы занят, и новая задача крутилась бы в
# перезапусках uvicorn. Прогон при этом рвать нельзя — сначала спрашиваем сам сервер.
$pair = "{0}:{1}" -f $env:WRO_WEB_USER, $env:WRO_WEB_PASS
$hdr = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
$busy = $false
try { $busy = [bool](Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/summary" -Headers $hdr -TimeoutSec 20).scrape_running }
catch {
    # Молчание — не доказательство, что прогона нет: сводка под нагрузкой не укладывается
    # в 20 с (26.09.2026 самая долгая — 45 с). Спрашиваем базу, как в safe_restart.ps1.
    $checker = Join-Path $Root "scripts\scrape_alive.py"
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    if ((Test-Path $checker) -and (Test-Path $py)) {
        & $py $checker | Out-Null
        if ($LASTEXITCODE -eq 0) { $busy = $true }
    }
}
if ($busy) {
    Write-Host "ИДЁТ ПРОГОН — задачи не переустанавливаю, чтобы его не оборвать. Дождитесь окончания («Прогони») и запустите скрипт снова." -ForegroundColor Yellow
    exit 1
}
Stop-ScheduledTask -TaskName "WroAnalyzer-Server" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*server.ps1*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
$pidFile = Join-Path $env:WRO_DATA "server.pid"
if (Test-Path $pidFile) { Stop-Process -Id (Get-Content $pidFile) -Force -ErrorAction SilentlyContinue }
$ps = "powershell.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
# Параметр нельзя называть $args: это автоматическая переменная PowerShell, и
# значение в неё не привязывается (проверено на 5.1: приходит пустой массив) —
# все четыре задачи создавались без «-File ...» и запускали пустой powershell.exe.
# -StartWhenAvailable: пропущенный запуск (ПК спал или был выключен в 02:30)
# выполняется при ближайшей возможности, а не теряется до завтра.
function Register($name, $taskArgs, $triggers) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $ps -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass " + $taskArgs)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable
    # LogonType S4U: задача идёт от имени владельца, но БЕЗ его входа в систему
    # и без хранения пароля. При Interactive (было до 09.10.2026) ни сервер, ни
    # прогоны не запускались, пока владелец не сядет за компьютер.
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
    Write-Host "задача $name создана"
}
# Сервер — ДВА события: запуск Windows и вход в систему.
# Только «при входе» не годится: после перезагрузки на обновления или после
# сбоя питания сайт не поднимался, пока владелец не сядет за компьютер,
# и прогоны в эти дни просто не случались (09.10.2026).
$serverTriggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn -User $user)
)
Register "WroAnalyzer-Server" ("-File `"" + (Join-Path $PSScriptRoot "server.ps1") + "`"") $serverTriggers
# Прогоны: продажа 11:00 и 17:00, аренда 02:30 (местное время = Киев; окна не
# пересекаются с киевской системой, если она на том же IP)
Register "WroAnalyzer-Scrape-Sale-11" ("-File `"" + (Join-Path $PSScriptRoot "scrape_trigger.ps1") + "`" -Kind sale") (New-ScheduledTaskTrigger -Daily -At 11:00)
Register "WroAnalyzer-Scrape-Sale-17" ("-File `"" + (Join-Path $PSScriptRoot "scrape_trigger.ps1") + "`" -Kind sale") (New-ScheduledTaskTrigger -Daily -At 17:00)
Register "WroAnalyzer-Scrape-Rent" ("-File `"" + (Join-Path $PSScriptRoot "scrape_trigger.ps1") + "`" -Kind rent") (New-ScheduledTaskTrigger -Daily -At 02:30)
# Доступ с других машин домашней сети (Mac, телефон)
if (-not (Get-NetFirewallRule -DisplayName "Wroclaw Analyzer $port" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Wroclaw Analyzer $port" -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow -Profile Private | Out-Null
    Write-Host "правило брандмауэра для порта $port добавлено (профиль «Частная сеть»)"
}
Start-ScheduledTask -TaskName "WroAnalyzer-Server"
Write-Host "Готово. Сервер: http://localhost:$port  (логин admin, пароль из env.ps1). Проверка источников: .\.venv\Scripts\python.exe scripts\probe_sources.py"
