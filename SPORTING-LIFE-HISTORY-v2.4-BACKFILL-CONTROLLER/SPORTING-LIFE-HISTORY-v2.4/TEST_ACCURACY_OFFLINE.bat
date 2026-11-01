@echo off
cd /d "%~dp0"
py sl_history.py --self-test
if errorlevel 1 goto fail
py test_accuracy.py
if errorlevel 1 goto fail
py test_history.py
if errorlevel 1 goto fail
echo.
echo PASS: All offline accuracy, database and resume tests.
pause
exit /b 0
:fail
echo Offline QA failed. Send the full Command Prompt output.
pause
exit /b 1
