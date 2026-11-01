@echo off
cd /d "%~dp0"
py sl_history.py --export-only
py validate_export.py --folder data\exports
pause
