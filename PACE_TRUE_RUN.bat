@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ - race pace / true-run labels
echo Building race pace / true-run labels into data\site_cache.sqlite
echo (reads sectionals.sqlite and the figure cache read-only; never writes to the scrapers)
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3, then rerun this file.
  pause
  exit /b 1
)
python -u tools\pace_true_run.py --force
if errorlevel 1 (
  echo.
  echo Pace build failed. The site will still run; past runs just will not have pace badges until this succeeds.
  pause
  exit /b 1
)
echo.
echo Done. Restart the site with RUN_SITE.bat to see pace labels on the form.
echo Then run UPLOAD_TO_SUPABASE.bat if you want the live site updated.
pause
