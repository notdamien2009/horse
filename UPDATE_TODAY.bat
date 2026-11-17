@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ - update today's card
set PY=python
where python >nul 2>nul || set PY=py -3
if not exist ".env" (
  echo Missing .env in the Speeds folder - the upload needs it.
  pause
  exit /b 1
)
echo [1/3] Fetching today's race cards...
%PY% tools\sl_cards.py
if errorlevel 1 goto :fail
echo.
echo [2/3] Scoring figures, Predicted today, pace and win %%...
node web\scripts\prepare-figures.mjs
if errorlevel 1 goto :fail
echo.
echo [3/3] Uploading to the live site...
%PY% tools\upload_to_supabase.py
if errorlevel 1 goto :fail
echo.
echo All done - refresh FurlongIQ.
pause
exit /b 0
:fail
echo.
echo Update stopped - a step failed. Send a screenshot of this window.
pause
exit /b 1
