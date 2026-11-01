@echo off
cd /d "%~dp0"
py backfill_controller.py --mode check --start 2022-01-01 --end 2026-10-21
pause
