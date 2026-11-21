@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ - rebuild market stats
echo Rebuilding FurlongIQ market stats (counts, movers, trainer and horse profiles)...
python tools\build_market_stats.py
if errorlevel 1 (echo Build failed - is Python with pandas and pyarrow installed? & pause & exit /b 1)
echo.
echo Done. web\src\lib\market-stats.json updated. Restart the site (PREVIEW_FURLONGIQ.bat) to see it.
pause