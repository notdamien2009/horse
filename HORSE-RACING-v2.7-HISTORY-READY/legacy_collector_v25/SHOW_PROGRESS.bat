@echo off
cd /d "%~dp0"
py backfill_controller.py --mode check
pause
