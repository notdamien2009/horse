@echo off
setlocal
cd /d "%~dp0"
echo This imports publicly readable pages only when you have permission to collect them.
echo Stops for access restrictions, errors and substantial QA problems. No access-control bypass.
echo Existing data/racing_history.sqlite is preserved and resumable.
choice /M "Start authorized collection, 2022-01-01 to 2026-10-31"
if errorlevel 2 exit /b 0
py tools\backup_db.py
if errorlevel 1 (echo Backup failed - stopped. & pause & exit /b 1)
py src\backfill_controller.py --mode full --start 2022-01-01 --end 2026-10-31 --batches 10000 --batch-races 20 --delay 6 --database data/racing_history.sqlite
set CODE=%errorlevel%
echo.
echo Data collection exited with code %CODE%. Now exporting everything saved so far.
py tools\export_live.py
py tools\progress_report.py
start "" "%~dp0data\exports"
pause
