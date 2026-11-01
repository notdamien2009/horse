@echo off
cd /d "%~dp0"
echo PILOT: dates 2022-01-01 to 2026-10-21, 3 batches max.
echo Only use where you have permission to collect and store this data.
choice /M "Continue with authorised pilot"
if errorlevel 2 exit /b 0
py backfill_controller.py --mode pilot --start 2022-01-01 --end 2026-10-21 --batches 3 --batch-races 20 --delay 6
pause
