@echo off
cd /d "%~dp0"
echo [1/3] Parser and Windows SQLite cleanup self-test
py sl_history.py --self-test
if errorlevel 1 (echo FAILED: self-test & py test_checkpoint_v25.py
if errorlevel 1 exit /b 1
pause & exit /b 1)
echo.
echo [2/3] Runner accuracy and all finish statuses
py test_accuracy.py
if errorlevel 1 (echo FAILED: accuracy test & py test_checkpoint_v25.py
if errorlevel 1 exit /b 1
pause & exit /b 1)
echo.
echo [3/3] SQLite resume/export/error-path regression tests
py test_history.py
if errorlevel 1 (echo FAILED: regression test & py test_checkpoint_v25.py
if errorlevel 1 exit /b 1
pause & exit /b 1)
echo.
echo.
echo [4/4] Historical checkpoint and quarantine regression
py test_checkpoint_v25.py
if errorlevel 1 (echo FAILED: checkpoint test & pause & exit /b 1)
echo.
echo ALL TESTS PASSED - database handles released.
pause
