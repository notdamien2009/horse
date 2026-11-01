@echo off
cd /d "%~dp0"
py tools\progress_report.py
if errorlevel 1 (echo Progress report failed. & pause & exit /b 1)
start "" "%~dp0data\exports"
pause
