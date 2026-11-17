@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ - Sectionals v12 (pace, finishing speed, figure adjustments, backtest)
set PYTHONIOENCODING=utf-8
if not exist data\sectionals_v12 mkdir data\sectionals_v12
echo FurlongIQ Sectionals v12
echo -----------------------------------------------------------------
echo Reads sectionals.sqlite and the speed figures (read-only), builds
echo course/trip section pars, pace labels, finishing speed %%, figure
echo adjustments, then backtests them in the win %% model.
echo Updates the pace table the website uses (data\site_cache.sqlite).
echo Does NOT touch racing_history.sqlite, the Racing TV scraper, .env
echo or the live site. Takes about 5-10 minutes.
echo.
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY (
  where python >nul 2>nul && set PY=python
)
if not defined PY (
  echo Python was not found. Install Python 3, then rerun this file.
  pause
  exit /b 1
)
%PY% -c "import pandas, numpy" >nul 2>nul
if errorlevel 1 (
  echo Installing pandas / numpy...
  %PY% -m pip install --user pandas numpy
)
%PY% -u tools\sectionals_v12.py %*
if errorlevel 1 (
  echo.
  echo Sectionals v12 stopped with an error. Send a screenshot of this window.
  echo The website keeps its previous pace labels.
  pause
  exit /b 1
)
echo.
echo All done. Plain-English summary: data\sectionals_v12\summary.txt
echo To put the new pace labels on the live site, run UPDATE_TODAY.bat
echo (or UPLOAD_TO_SUPABASE.bat) as usual.
pause
