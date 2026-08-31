# Run every fetcher once, in dependency order. Each one is idempotent.
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
foreach ($m in @("calendar_skeleton", "ff_sync", "fred_actuals", "prices_daily", "reminders")) {
    Write-Host "=== fetchers.$m ==="
    & $py -m "fetchers.$m"
}
