# Full 2022-2026 backfill loop. Stop it by creating data\full_backfill\STOP
Set-Location "C:\Users\PC Deals\Desktop\Speeds"
$env:SL_COLLECTION_ENABLED = "true"
$env:PYTHONIOENCODING = "utf-8"
$log = "data\full_backfill\loop.log"
$stalls = 0
while (-not (Test-Path "data\full_backfill\STOP")) {
  $before = [int](python data\full_backfill\count.py)
  "$(Get-Date -Format s) START run, races=$before" | Add-Content $log
  python tools\window_backfill.py --mode collect --months 1 --windows 2 --batches 150 --batch-races 20 --delay 3 --max-runtime-minutes 240 --no-export *>> "data\full_backfill\collector.log"
  $code = $LASTEXITCODE
  $after = [int](python data\full_backfill\count.py)
  "$(Get-Date -Format s) END run exit=$code, races=$after (+$($after-$before))" | Add-Content $log
  if ($after -le $before) { $stalls++; "$(Get-Date -Format s) no progress, stall $stalls of 3" | Add-Content $log; if ($stalls -ge 3) { "$(Get-Date -Format s) STOPPING after 3 runs with no progress" | Add-Content $log; break }; Start-Sleep -Seconds 900 } else { $stalls = 0; Start-Sleep -Seconds 20 }
}
"$(Get-Date -Format s) loop exited" | Add-Content $log
