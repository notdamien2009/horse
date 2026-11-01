@echo off
cd /d "%~dp0"
echo This refreshes the first three queued races on 21 October 2022 in THIS folder's SQLite database.
echo Copy the existing data folder from your v2.1 installation first if you want to repair those records.
echo.
echo It requires authorised website access and makes no attempt to bypass access controls.
choice /m "Run limited 2022 reparse"
if errorlevel 2 exit /b 0
py sl_history.py --date 2022-10-21 --max-days 1 --max-races 3 --reparse --live --database "data\racing_history.sqlite" --output-dir "data\exports"
if errorlevel 1 echo Review error details; existing database preserved.
py sl_history.py --export-only
py validate_export.py --folder data\exports
pause
