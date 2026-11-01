@echo off
cd /d "%~dp0"
py tools\export_live.py
if errorlevel 1 (echo Export failed. & pause & exit /b 1)
py tools\progress_report.py
start "" "%~dp0data\exports"
pause
