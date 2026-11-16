@echo off
cd /d "%~dp0"
title FurlongIQ - Racing TV results status
echo.
echo  FurlongIQ  -  Racing TV results status
echo  This does not scrape. It only reports what is already saved.
echo.
python tools\rtv_results.py --status
echo.
echo  Missing dates file: data\rtv_results_backfill\MISSING_DATES.csv
echo  Progress log:       data\rtv_results_backfill\collector.log
echo.
pause
