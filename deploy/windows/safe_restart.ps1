# Перезапуск сервера, который ОТКАЖЕТСЯ работать во время прогона.
# В Киеве 18 из 25 упавших прогонов — это перезапуск ради выкатки.
#   .\safe_restart.ps1          # откажется, если идёт прогон
#   .\safe_restart.ps1 -Wait    # подождёт свободного окна (проверка каждые 5 мин)
#
# Сервер под задачей Планировщика запущен С ПРАВАМИ АДМИНИСТРАТОРА, и обычный
# Stop-Process на него отвечает «Access is denied». 18.09.2026 скрипт этот отказ
# проглатывал (-ErrorAction SilentlyContinue), health отвечал СТАРЫЙ процесс, и
# скрипт рапортовал «сервер снова отвечает» — выкатка молча не доезжала.
# Теперь: сначала останавливаем задачу целиком (это гасит и дочерний uvicorn,
# который держит порт), а успех проверяем по времени старта из /api/health.
param([switch]$Wait)
. (Join-Path $PSScriptRoot "env.ps1")
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
$pair = "{0}:{1}" -f $env:WRO_WEB_USER, $env:WRO_WEB_PASS
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
$task = "WroAnalyzer-Server"

function Health() {
    try { return Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 20 } catch { return $null }
}

# Молчание сервера — НЕ доказательство, что он умер. Пока идёт прогон, сводка
# по 21 тыс. строк ждёт писателя SQLite и может не ответить за 20 с. 26.09.2026 скрипт
# принял это за «сервер не отвечает — перезапускаю» и оборвал продажу №27 на 9369
# объявлениях из 11 300 — ровно то, ради чего этот скрипт и написан.
# Второе мнение — по базе: строка running со свежей отметкой жизни.
function ScrapeAliveByDb() {
    $py = Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe"
    $checker = Join-Path $PSScriptRoot "..\..\scripts\scrape_alive.py"
    if (-not (Test-Path $py) -or -not (Test-Path $checker)) { return $null }
    $out = & $py $checker 2>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) { Write-Host "  по базе: $out"; return $true }
    if ($code -eq 1) { return $false }
    Write-Host "  по базе определить не удалось: $out" -ForegroundColor Yellow
    return $null
}

while ($true) {
    try {
        $s = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/summary" -Headers $headers -TimeoutSec 20
    } catch {
        Write-Host "сводка не ответила ($($_.Exception.Message)) — смотрю в базу, не идёт ли прогон"
        $s = $null
    }
    $running = if ($s) { [bool]$s.scrape_running } else { ScrapeAliveByDb }
    if ($null -eq $running) {
        # ни HTTP, ни база не ответили — лучше не трогать, чем оборвать прогон
        Write-Host "НЕ ПОНЯТНО, ИДЁТ ЛИ ПРОГОН (ни HTTP, ни база). Перезапуск отменён." -ForegroundColor Red
        Write-Host "Проверьте раздел «Прогони» и повторите." -ForegroundColor Yellow
        exit 1
    }
    if ($running) {
        if (-not $s) { Write-Host "сервер не отвечает по HTTP, НО прогон жив — не трогаю" }
        if (-not $Wait) { Write-Host "ИДЁТ ПРОГОН — перезапуск отменён. Дождитесь окончания или запустите с -Wait"; exit 1 }
        Write-Host "идёт прогон, жду 5 мин..."; Start-Sleep -Seconds 300; continue
    }
    break
}

# Время старта ДО перезапуска: по нему потом видно, сменился ли процесс.
# Старый сервер (до этой правки) времени не отдаёт — тогда сверяем по pid.
$before = Health
$beforeMark = if ($before) { "$($before.started_at)|$($before.pid)" } else { $null }

$stopped = $false
if (Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue) {
    try {
        Stop-ScheduledTask -TaskName $task -ErrorAction Stop
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName $task -ErrorAction Stop
        Write-Host "задача $task перезапущена"
        $stopped = $true
    } catch {
        Write-Host "задачу $task не удалось перезапустить: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
if (-not $stopped) {
    # сервер поднят вручную (server.ps1 без Планировщика) — гасим uvicorn по pid,
    # надзиратель поднимет его заново
    $pidFile = Join-Path $env:WRO_DATA "server.pid"
    if (Test-Path $pidFile) {
        $srvPid = Get-Content $pidFile
        Write-Host "останавливаю uvicorn (PID $srvPid); server.ps1 поднимет его заново"
        try { Stop-Process -Id $srvPid -Force -ErrorAction Stop }
        catch { Write-Host "не удалось остановить PID $srvPid : $($_.Exception.Message)" -ForegroundColor Yellow }
    } else {
        Write-Host "ни задачи Планировщика, ни server.pid — перезапускать нечего" -ForegroundColor Yellow
    }
}

# ждём, пока поднимется НОВЫЙ процесс (до 60 с)
$after = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    $after = Health
    if ($after -and (-not $beforeMark -or "$($after.started_at)|$($after.pid)" -ne $beforeMark)) { break }
}
if (-not $after) {
    Write-Host "СЕРВЕР НЕ ПОДНЯЛСЯ за 60 с. Смотрите $env:WRO_DATA\uvicorn.err.log" -ForegroundColor Red
    exit 1
}
if ($beforeMark -and "$($after.started_at)|$($after.pid)" -eq $beforeMark) {
    Write-Host "СЕРВЕР НЕ ПЕРЕЗАПУСТИЛСЯ: отвечает тот же процесс (pid $($after.pid)), выкатка НЕ доехала." -ForegroundColor Red
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "Причина почти наверняка в правах: задача сервера работает от администратора. Запустите PowerShell от имени администратора и повторите." -ForegroundColor Yellow
    }
    exit 1
}
Write-Host "сервер перезапущен (pid $($after.pid), старт $($after.started_at))"
