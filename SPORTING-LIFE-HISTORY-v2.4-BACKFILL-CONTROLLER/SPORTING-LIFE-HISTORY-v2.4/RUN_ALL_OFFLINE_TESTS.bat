@echo off
cd /d "%~dp0"
echo [1/3] Parser and Windows SQLite cleanup self-test
py sl_history.py --self-test
if errorlevel 1 (echo FAILED: self-test & pause & exit /b 1)
echo.
echo [2/3] Runner accuracy and all finish statuses
py test_accuracy.py
if errorlevel 1 (echo FAILED: accuracy test & pause & exit /b 1)
echo.
echo [3/3] SQLite resume/export/error-path regression tests
py test_history.py
if errorlevel 1 (echo FAILED: regression test & pause & exit /b 1)
echo.
echo ALL TESTS PASSED - database handles released.
pause
