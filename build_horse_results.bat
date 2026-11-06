@echo off
setlocal
cd /d "%~dp0"
if not exist "data\racing_history.sqlite" (
  echo ERROR: Cannot find data\racing_history.sqlite
  echo Put this package inside your Speeds folder next to the data folder.
  pause
  exit /b 2
)
python tools\sporting_life_to_html.py --database "data\racing_history.sqlite" --output "data\horse_results.html" %*
if errorlevel 1 (
  echo Conversion failed. See the error above.
  pause
  exit /b 1
)
start "" "data\horse_results.html"
echo Your HTML report is open in the browser. Run this file again to refresh with new data.
exit /b 0
