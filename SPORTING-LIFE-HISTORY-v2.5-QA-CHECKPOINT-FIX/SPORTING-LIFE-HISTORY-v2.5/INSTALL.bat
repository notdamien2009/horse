@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (echo INSTALL FAILED & pause & exit /b 1)
py sl_history.py --self-test
pause
