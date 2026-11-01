@echo off
if not exist races_all.csv (echo Put races_all.csv and runners_all.csv in this folder. & pause & exit /b 1)
if not exist runners_all.csv (echo Missing runners_all.csv & pause & exit /b 1)
py repair_csv_exports.py --races races_all.csv --runners runners_all.csv --output corrected_exports
pause
