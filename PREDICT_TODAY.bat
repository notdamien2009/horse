@echo off
title Predicted today — FurlongIQ
cd /d "%~dp0"
if not exist data\predict_today mkdir data\predict_today
echo Training the 'predicted today' speed-figure model and scoring today's cards.
echo This uses only information known before each race (recent form, trend, class,
echo trip, going). Official ratings are left out of the card rating on purpose.
echo.
echo First run takes a couple of minutes. The window stays open when it finishes.
echo.
where py >nul 2>&1 && (
  py -3 tools\predict_today.py %*
) || (
  python tools\predict_today.py %*
)
echo.
echo Scoring form-only win probabilities for today's cards...
where py >nul 2>&1 && (
  py -3 tools\win_pct.py --score-only %*
) || (
  python tools\win_pct.py --score-only %*
)
echo.
echo Finished. Full write-up: data\predict_today\summary.txt
echo Win %% write-up: data\predict_today\win_pct_summary.txt
echo Restart the site with RUN_SITE.bat to see the new ranking.
pause
