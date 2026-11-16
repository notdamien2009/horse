@echo off
title Form-only win %% — FurlongIQ
cd /d "%~dp0"
if not exist data\predict_today mkdir data\predict_today
echo Training the form-only win-probability model and scoring today's cards.
echo No prices are used as inputs. Probabilities sum to 100%% in each race.
echo.
echo First run takes a few minutes. The window stays open when it finishes.
echo.
where py >nul 2>&1 && (
  py -3 tools\win_pct.py %*
) || (
  python tools\win_pct.py %*
)
echo.
echo Finished. Full write-up: data\predict_today\win_pct_summary.txt
echo Restart the site with RUN_SITE.bat to see win %% and fair odds.
pause
