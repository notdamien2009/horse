@echo off
cd /d "%~dp0"
py sl_history.py --export-only
pause
