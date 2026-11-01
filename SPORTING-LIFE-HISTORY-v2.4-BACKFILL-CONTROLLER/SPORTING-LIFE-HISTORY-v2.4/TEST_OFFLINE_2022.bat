@echo off
cd /d "%~dp0"
py sl_history.py --html-dir demo_pages --date 2022-10-21 --max-races 2
pause
