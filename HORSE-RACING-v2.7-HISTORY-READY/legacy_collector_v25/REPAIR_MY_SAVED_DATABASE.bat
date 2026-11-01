@echo off
cd /d "%~dp0"
echo BACK UP your data folder before continuing. A dated SQLite backup will also be created.
py upgrade_saved_database.py
if errorlevel 1 (echo Repair failed; original and backup should remain. & pause & exit /b 1)
py validate_export.py --folder data\exports
pause
