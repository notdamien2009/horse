@echo off
py sl_history.py --export-only
if errorlevel 1 (echo EXPORT FAILED & pause & exit /b 1)
py validate_export.py --folder data\exports
pause
