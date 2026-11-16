@echo off
title Trade / lay prediction
cd /d "%~dp0"
if not exist data\predict mkdir data\predict
echo Running trade / lay models at 5m, 2m and 1m before the off
echo (form-only, price-only, and price + form; BSP is a reference only).
echo This may take several minutes. The window stays open when it finishes.
echo.
where py >nul 2>&1 && (
  py -3 tools\trade_below2.py %*
) || (
  python tools\trade_below2.py %*
)
echo.
echo Finished. Full write-up: data\predict\summary.txt
pause
