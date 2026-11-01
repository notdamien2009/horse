@echo off
cd /d "%~dp0"
py -m pip install -r src\requirements.txt
if errorlevel 1 (echo Install failed. & pause & exit /b 1)
py src\sl_history.py --self-test
pause
