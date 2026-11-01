@echo off
REM Safe compatibility launcher: NEVER re-import old seed or reset current collection.
cd /d "%~dp0"
call EXPORT_MY_DATA.bat
