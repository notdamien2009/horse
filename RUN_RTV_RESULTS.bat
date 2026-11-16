@echo off
cd /d "%~dp0"
title FurlongIQ - Racing TV results backfill
echo.
echo  FurlongIQ  -  Racing TV results backfill
echo  Adds results (including in-running comments) into data\racing_history.sqlite
echo  Default range: 2023-12-01 to yesterday. Already-saved races are skipped.
echo  A backup of the database is made before the first write.
echo  To stop safely: create the file data\rtv_results_backfill\STOP  (or close this window after the current race).
echo  To resume: run this file again.
echo.
python tools\rtv_results.py --delay 3
echo.
echo  Finished (or stopped). You can close this window.
pause
