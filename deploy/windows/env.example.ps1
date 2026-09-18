# Скопировать в env.ps1 (он в .gitignore) и заполнить. Читается server.ps1,
# scrape_trigger.ps1 и safe_restart.ps1 — пароль живёт в ОДНОМ месте, чтобы
# триггеры не отвалились молча при его смене (так было в Киеве 15.08.2026).
$env:WRO_WEB_USER = "admin"
$env:WRO_WEB_PASS = "поменяйте-меня"
# База и логи — на большом диске, не в папке проекта
$env:WRO_DATA = "D:\wro-data"
# Порт сервера
$env:WRO_PORT = "8020"
# Расписанием управляет Планировщик Windows, а не внутренний планировщик
$env:DISABLE_SCHEDULER = "1"
