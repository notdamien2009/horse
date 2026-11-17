@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ Challenger V1 - bounded research run
set PYTHONIOENCODING=utf-8
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
echo FurlongIQ challenger pilot. NO existing V4/V12 file, website or database will be changed.
%PY% tools\challenger_figures.py --root . --train-end 2025-12-31 --max-rtv-races 10000
if errorlevel 1 (
 echo Challenger stopped. Check source data and error details above.
 pause
 exit /b 1
)
echo Research outputs are in data\challenger_v1\
pause
