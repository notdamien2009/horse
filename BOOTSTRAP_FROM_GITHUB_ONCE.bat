@echo off
setlocal
cd /d "%~dp0"
if exist "data\racing_history.sqlite" (
  echo Local database already exists. Refusing to overwrite it.
  echo To preserve local progress, do NOT use this tool to merge two archives.
  goto :end
)
if not exist "tools\sl_checkpoint.py" (
  echo Missing tools\sl_checkpoint.py. Use the latest GitHub project main branch.
  goto :end
)
where gh >nul 2>&1
if errorlevel 1 (
  echo GitHub CLI not installed or not on PATH.
  goto :end
)
mkdir "data" >nul 2>&1
echo Downloading the private GitHub checkpoint ...
gh release download sl-database-checkpoint -R notdamien2009/horse -p racing_history.sqlite.gz -D data --clobber
if errorlevel 1 (
 echo Download failed. Run: gh auth login
 goto :end
)
py -3 tools\sl_checkpoint.py restore data\racing_history.sqlite data\racing_history.sqlite.gz
if errorlevel 1 echo Restore failed. Check gh authentication and Python setup.
:end
pause
