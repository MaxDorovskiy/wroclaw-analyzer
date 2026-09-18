# Сервер под Планировщиком Windows: перезапускает uvicorn, если тот упал
# (аналог KeepAlive у launchd). PID дочернего процесса — в $WRO_DATA\server.pid,
# по нему safe_restart.ps1 делает мягкий перезапуск.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot "env.ps1")
if (-not $env:WRO_DATA) { $env:WRO_DATA = Join-Path $Root "data" }
New-Item -ItemType Directory -Force -Path $env:WRO_DATA | Out-Null
$py = Join-Path $Root ".venv\Scripts\python.exe"
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
Set-Location $Root
while ($true) {
    $p = Start-Process -FilePath $py -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", $port) `
        -PassThru -NoNewWindow -RedirectStandardOutput (Join-Path $env:WRO_DATA "uvicorn.out.log") -RedirectStandardError (Join-Path $env:WRO_DATA "uvicorn.err.log")
    Set-Content -Path (Join-Path $env:WRO_DATA "server.pid") -Value $p.Id
    $p.WaitForExit()
    Add-Content -Path (Join-Path $env:WRO_DATA "server-restarts.log") -Value ("{0} uvicorn вышел с кодом {1}, перезапуск через 5 с" -f (Get-Date -Format s), $p.ExitCode)
    Start-Sleep -Seconds 5
}
