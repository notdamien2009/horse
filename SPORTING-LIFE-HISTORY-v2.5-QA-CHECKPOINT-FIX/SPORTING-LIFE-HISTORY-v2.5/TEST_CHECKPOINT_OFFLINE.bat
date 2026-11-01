@echo off
cd /d "%~dp0"
py test_checkpoint_v25.py
if errorlevel 1 echo TEST FAILED - do not start the backfill
pause
