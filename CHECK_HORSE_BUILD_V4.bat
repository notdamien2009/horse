@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist "web\package.json" (
  echo ERROR: Put this BAT file in the main horse project folder, alongside package.json and the web folder.
  pause
  exit /b 1
)
set "INFO=%CD%\HORSE_BUILD_ENV.txt"
set "BUILDLOG=%CD%\HORSE_WEBPACK_BUILD.log"
set "DEBUGLOG=%CD%\HORSE_DEBUG_BUILD.log"
echo ===========================================
echo    HORSE SECTIONALS V4 - BUILD DIAGNOSTIC
echo ===========================================
echo Does not edit source code, install packages, or push to GitHub.
echo Only the generated web\.next build cache is removed.
echo.
(
  echo Horse build diagnostic
  echo Run date: %DATE% %TIME%
  echo Project: %CD%
  echo.
  echo Node:
  node -v
  echo.
  echo npm:
  npm -v
  echo.
  echo Root dependency tree:
  npm ls next react react-dom --all
  echo.
  echo Web dependency tree:
  npm --prefix web ls next react react-dom --all
) > "%INFO%" 2>&1
if exist "web\.next" (
  echo Clearing the generated web\.next folder...
  rmdir /s /q "web\.next"
  if exist "web\.next" (
    echo ERROR: Could not clear web\.next. Stop any running Next.js development server and retry.
    pause
    exit /b 2
  )
)
echo.
echo Testing a normal production build with the supported Webpack backend...
echo Output: %BUILDLOG%
call npm run build -- --webpack > "%BUILDLOG%" 2>&1
if not errorlevel 1 goto success
echo.
echo Webpack production build FAILED too. Gathering a more detailed prerender trace.
echo Output: %DEBUGLOG%
call npm run build -- --debug-prerender > "%DEBUGLOG%" 2>&1
echo.
echo Please send these three files for analysis:
echo   HORSE_BUILD_ENV.txt
echo   HORSE_WEBPACK_BUILD.log
echo   HORSE_DEBUG_BUILD.log
echo.
echo Do not deploy a debug-prerender build.
pause
exit /b 1
:success
echo.
echo WEBPACK PRODUCTION BUILD PASSED.
echo The source changes compile and prerender with Webpack, while your earlier Turbopack build failed.
echo This suggests a bundler or build-path issue; it does NOT prove the chart is visually or functionally correct.
echo Next: test the chart on localhost before changing any deployment scripts.
echo Please send HORSE_BUILD_ENV.txt and the last lines of HORSE_WEBPACK_BUILD.log if you want a permanent build change.
pause
exit /b 0
