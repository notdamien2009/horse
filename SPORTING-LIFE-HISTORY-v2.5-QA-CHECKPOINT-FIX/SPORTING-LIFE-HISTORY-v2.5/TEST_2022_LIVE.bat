@echo off
cd /d "%~dp0"
echo Sporting Life prohibits automated data capture in its terms.
echo Use live collection only if you have permission for it.
choice /M "Proceed with authorised one-day test"
if errorlevel 2 exit /b 0
py sl_history.py --live --date 2022-10-21 --max-days 1 --max-races 3
pause
