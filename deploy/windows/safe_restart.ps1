# Перезапуск сервера, который ОТКАЖЕТСЯ работать во время прогона.
# В Киеве 18 из 25 упавших прогонов — это перезапуск ради выкатки.
#   .\safe_restart.ps1          # откажется, если идёт прогон
#   .\safe_restart.ps1 -Wait    # подождёт свободного окна (проверка каждые 5 мин)
param([switch]$Wait)
. (Join-Path $PSScriptRoot "env.ps1")
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
$pair = "{0}:{1}" -f $env:WRO_WEB_USER, $env:WRO_WEB_PASS
$headers = @{ Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair)) }
while ($true) {
    try {
        $s = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/summary" -Headers $headers -TimeoutSec 20
    } catch {
        Write-Host "сервер не отвечает ($($_.Exception.Message)) — перезапускаю"
        $s = $null
    }
    if ($s -and $s.scrape_running) {
        if (-not $Wait) { Write-Host "ИДЁТ ПРОГОН — перезапуск отменён. Дождитесь окончания или запустите с -Wait"; exit 1 }
        Write-Host "идёт прогон, жду 5 мин..."; Start-Sleep -Seconds 300; continue
    }
    break
}
$pidFile = Join-Path $env:WRO_DATA "server.pid"
if (Test-Path $pidFile) {
    $srvPid = Get-Content $pidFile
    Write-Host "останавливаю uvicorn (PID $srvPid); server.ps1 поднимет его заново"
    Stop-Process -Id $srvPid -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "server.pid не найден — перезапускаю задачу планировщика"
    Stop-ScheduledTask -TaskName "WroAnalyzer-Server" -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName "WroAnalyzer-Server"
}
Start-Sleep -Seconds 8
try { Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 20 | Out-Null; Write-Host "сервер снова отвечает" }
catch { Write-Host "сервер пока не отвечает: $($_.Exception.Message)" }
