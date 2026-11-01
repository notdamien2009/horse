@echo off
cd /d "%~dp0"
echo HISTORICAL ARCHIVE: 1 January 2022 to 21 October 2026.
echo WARNING: The site's published terms restrict automated extraction.
echo Use this launcher only if you have appropriate permission.
echo Ensure the pilot and manual comparisons passed before continuing.
choice /M "Proceed with authorised historical collection"
if errorlevel 2 exit /b 0
py backfill_controller.py --mode full --start 2022-01-01 --end 2026-10-21 --batches 10000 --batch-races 20 --delay 6
if errorlevel 1 echo Collection paused or stopped - see data\backfill_logs\run.log
pause
