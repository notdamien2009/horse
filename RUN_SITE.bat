@echo off
setlocal
cd /d "%~dp0"
title Speeds racing site - press Ctrl+C or close this window to stop
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is required. Install Node.js 22 LTS or newer, then rerun this file.
  pause
  exit /b 1
)
if not exist "node_modules" (
  echo Installing required website packages - first time only...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo Package installation failed. Check your internet connection and npm configuration.
    pause
    exit /b 1
  )
)
echo.
echo Starting Speeds. Open http://localhost:3050 in a browser.
echo Press Ctrl+C to stop the website.
echo.
start "" cmd /c "timeout /t 8 >nul & start http://localhost:3050"
call npm run dev
pause
