@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ - Build master (speed figures v4 + sectionals)
set PYTHONIOENCODING=utf-8
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY ( echo Python not found. & pause & exit /b 1 )
echo.
echo Step 1/2  Speed figures v4 (Racing TV exact distances, 3-way times).
echo           Writes data\speed_v4. speed_v3 and the live site are NOT changed.
echo           About 10-15 minutes.
%PY% -u tools\speedfig_v4.py %*
if errorlevel 1 ( echo. & echo Stopped with an error on speed figures v4 - send a screenshot. & pause & exit /b 1 )
echo.
echo Step 2/2  Sectionals (pars on exact yards, section and full-race figures).
echo           Uses v4 figures and going allowances. About 10-20 minutes.
echo           Backtest is skipped here; run SECTIONALS_V12.bat if you want it.
%PY% -u tools\sectionals_v12.py --no-backtest
if errorlevel 1 ( echo. & echo Stopped with an error on sectionals - send a screenshot. & pause & exit /b 1 )
echo.
echo Done.
echo   Speed figures: data\speed_v4\summary.txt
echo   Sectionals:    data\sectionals_v12\summary.txt
pause
