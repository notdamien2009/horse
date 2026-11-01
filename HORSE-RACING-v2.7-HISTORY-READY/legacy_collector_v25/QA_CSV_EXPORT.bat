@echo off
cd /d "%~dp0"
py sl_history.py --export-only
if errorlevel 1 goto fail
py validate_export.py --folder data\exports
if errorlevel 1 goto fail
echo Complete: CSV validator reported no internal data contradictions.
pause
exit /b 0
:fail
echo Review data\exports\v22_accuracy_audit.json for details.
pause
exit /b 1
