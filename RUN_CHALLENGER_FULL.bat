@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ Challenger V1 - full research run
set PYTHONIOENCODING=utf-8
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
echo Full history can use substantial RAM. Research-only: no live or Supabase changes.
%PY% tools\challenger_figures.py --root . --train-end 2025-12-31
if errorlevel 1 (
 echo Challenger stopped. Check error details above.
 pause
 exit /b 1
)
echo Research outputs are in data\challenger_v1\
pause
