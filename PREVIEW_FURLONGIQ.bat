@echo off
setlocal
cd /d "%~dp0"
title FurlongIQ preview - http://localhost:3050 (Ctrl+C to stop)
if not exist "web\src\lib\market-stats.json" call BUILD_MARKET_STATS.bat
echo Pages: /  /cards  /live  /movers  /profiles  /tools  /guides  /pricing
call RUN_SITE.bat