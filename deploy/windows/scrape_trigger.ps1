# Запуск прогона по расписанию: POST /api/scrape с паролем из env.ps1.
# Случайная задержка 0-20 мин, чтобы старт не приходился ровно на час.
# Аренда при 409 (идёт продажа / пауза) повторяет попытку каждые 15 минут,
# до 6 раз — так же, как rent_trigger.sh в Киеве.
param([ValidateSet("sale", "rent")] [string]$Kind = "sale", [int]$MaxJitterMin = 20)
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "env.ps1")
$port = if ($env:WRO_PORT) { $env:WRO_PORT } else { "8020" }
$log = Join-Path $env:WRO_DATA "trigger.log"
# UTF-8 явно: по умолчанию PowerShell 5.1 пишет в ANSI (cp1251), а server.log
# рядом — в UTF-8; один просмотрщик не открыл бы оба без кракозябр
function Log($m) { Add-Content -Path $log -Encoding UTF8 -Value ("{0} [{1}] {2}" -f (Get-Date -Format s), $Kind, $m) }
# обрезка лога: при 5 МБ оставить последние 5000 строк. Скобки обязательны:
# без них Set-Content открывает файл, пока Get-Content его ещё читает («файл занят»)
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) { (Get-Content $log -Tail 5000 -Encoding UTF8) | Set-Content $log -Encoding UTF8 }
# -MaxJitterMin 0 (ручной запуск «прямо сейчас»): Get-Random с Minimum = Maximum
# падает с ошибкой, и в Start-Sleep уходил $null
$jitter = if ($MaxJitterMin -gt 0) { Get-Random -Minimum 0 -Maximum ($MaxJitterMin * 60) } else { 0 }
Log "жду $jitter с"
Start-Sleep -Seconds $jitter
$pair = "{0}:{1}" -f $env:WRO_WEB_USER, $env:WRO_WEB_PASS
$auth = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))
$headers = @{ Authorization = "Basic $auth" }
$attempts = if ($Kind -eq "rent") { 6 } else { 1 }
for ($i = 1; $i -le $attempts; $i++) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$port/api/scrape?kind=$Kind" -Headers $headers -TimeoutSec 30
        Log ("запущен: " + $r.Content)
        exit 0
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 401) { Log "ТРЕБУЕТСЯ ВХОД: пароль в env.ps1 не совпадает с сервером"; exit 2 }
        if ($code -eq 409 -and $i -lt $attempts) { Log "409 (идёт прогон или пауза), повтор через 15 мин"; Start-Sleep -Seconds 900; continue }
        Log ("не запущен: код $code " + $_.Exception.Message)
        exit 1
    }
}
