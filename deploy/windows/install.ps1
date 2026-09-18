# Установка на Windows 11: venv, зависимости, сборка фронтенда, задачи
# Планировщика, правило брандмауэра. Запускать из PowerShell от имени
# администратора (для задач и брандмауэра):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   .\deploy\windows\install.ps1
param([switch]$NoTasks)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $Root
if (-not (Test-Path (Join-Path $PSScriptRoot "env.ps1"))) {
    Copy-Item (Join-Path $PSScriptRoot "env.example.ps1") (Join-Path $PSScriptRoot "env.ps1")
    Write-Host "Создан deploy\windows\env.ps1 — впишите пароль и путь к данным, затем запустите скрипт снова" -ForegroundColor Yellow
    exit 1
}
. (Join-Path $PSScriptRoot "env.ps1")
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
if ($NoTasks) { exit 0 }
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
$ps = "powershell.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
# Параметр нельзя называть $args: это автоматическая переменная PowerShell, и
# значение в неё не привязывается (проверено на 5.1: приходит пустой массив) —
# все четыре задачи создавались без «-File ...» и запускали пустой powershell.exe.
function Register($name, $taskArgs, $trigger) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $ps -Argument ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass " + $taskArgs)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -User $user -RunLevel Highest | Out-Null
    Write-Host "задача $name создана"
}
# Сервер: при входе в систему, без ограничения по времени, перезапуск при сбое
Register "WroAnalyzer-Server" ("-File `"" + (Join-Path $PSScriptRoot "server.ps1") + "`"") (New-ScheduledTaskTrigger -AtLogOn -User $user)
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
