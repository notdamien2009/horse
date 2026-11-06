@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>&1
if not errorlevel 1 (
    start "Sporting Life Local Collector" /B pyw -3 "%~dp0local_history_runner.py" --loop
    echo Background launcher submitted. See data\local_runner\background.log and CHECK_STATUS.bat.
    goto :done
)
where pythonw >nul 2>&1
if not errorlevel 1 (
    start "Sporting Life Local Collector" /B pythonw "%~dp0local_history_runner.py" --loop
    echo Background launcher submitted. See data\local_runner\background.log and CHECK_STATUS.bat.
    goto :done
)
echo Python GUI launcher not found. Install Python 3.12 and enable Windows Python launcher.
:done
pause
