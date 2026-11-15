# Racing TV sectionals backfill loop (2023-03-01 .. 2026-10-31) -> data\sectionals.sqlite
# Separate from the Sporting Life backfill; never touches racing_history.sqlite (read-only matching only).
# Stop it by creating an empty file: data\sectionals_backfill\STOP
# Start hidden:
#   Start-Process powershell -WindowStyle Hidden -ArgumentList '-ExecutionPolicy','Bypass','-File','"C:\Users\PC Deals\Desktop\Speeds\RUN_SECTIONALS_BACKFILL.ps1"'
Set-Location "C:\Users\PC Deals\Desktop\Speeds"
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force "data\sectionals_backfill" | Out-Null
$log = "data\sectionals_backfill\loop.log"
$stalls = 0
while (-not (Test-Path "data\sectionals_backfill\STOP")) {
  $before = [int](python tools\rtv_sectionals.py --count)
  "$(Get-Date -Format s) START run, progress=$before" | Add-Content $log
  python tools\rtv_sectionals.py --start 2023-03-01 --end 2026-10-31 --delay 3 --max-runtime-minutes 240 *>> "data\sectionals_backfill\collector.log"
  $code = $LASTEXITCODE
  $after = [int](python tools\rtv_sectionals.py --count)
  "$(Get-Date -Format s) END run exit=$code, progress=$after (+$($after-$before))" | Add-Content $log
  if ($code -eq 0) { "$(Get-Date -Format s) range finished" | Add-Content $log; break }
  if ($after -le $before) {
    $stalls++
    "$(Get-Date -Format s) no progress, stall $stalls of 3" | Add-Content $log
    if ($stalls -ge 3) { "$(Get-Date -Format s) STOPPING after 3 runs with no progress" | Add-Content $log; break }
    Start-Sleep -Seconds 900
  } elseif ($code -eq 3) {
    $stalls = 0; "$(Get-Date -Format s) blocked (403/429), cooling off 30 min" | Add-Content $log; Start-Sleep -Seconds 1800
  } else { $stalls = 0; Start-Sleep -Seconds 20 }
}
"$(Get-Date -Format s) loop exited" | Add-Content $log
