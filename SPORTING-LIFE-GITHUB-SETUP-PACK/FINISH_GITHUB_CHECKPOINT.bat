@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0FINISH_GITHUB_CHECKPOINT.ps1"
echo.
pause
