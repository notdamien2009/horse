@echo off
setlocal EnableExtensions
REM Extract the HORSE-SECTIONALS-V4 folder into the horse project root, then run this file.
set "PACKAGE=%~dp0"
set "PROJECT=%~dp0.."
if exist "%PROJECT%\web\src\components\RaceSectionals.tsx" goto gotproject
cls
echo HORSE SECTIONALS V4 - LOCAL INSTALLER
echo.
echo Enter the full Windows path to the horse website folder that contains web\ and package.json.
echo Example: C:\Users\YourName\Desktop\horse
set /p "PROJECT=Horse project path: "
:gotproject
if not exist "%PROJECT%\web\src\components\RaceSectionals.tsx" (
  echo ERROR: Could not find existing RaceSectionals.tsx in %PROJECT%
  echo No files have been changed.
  pause
  exit /b 1
)
if not exist "%PACKAGE%web\src\components\SectionalPaceChart.tsx" (
  echo ERROR: Source files missing from downloaded ZIP.
  pause
  exit /b 1
)
set "TARGET=%PROJECT%\web\src\components"
if not exist "%PACKAGE%backup" mkdir "%PACKAGE%backup"
copy /Y "%TARGET%\RaceSectionals.tsx" "%PACKAGE%backup\RaceSectionals.tsx" >nul
if errorlevel 1 goto fail
copy /Y "%PACKAGE%web\src\components\RaceSectionals.tsx" "%TARGET%\RaceSectionals.tsx" >nul
if errorlevel 1 goto fail
copy /Y "%PACKAGE%web\src\components\SectionalPaceChart.tsx" "%TARGET%\SectionalPaceChart.tsx" >nul
if errorlevel 1 goto fail
copy /Y "%PACKAGE%web\src\components\SectionalPaceChart.module.css" "%TARGET%\SectionalPaceChart.module.css" >nul
if errorlevel 1 goto fail
echo.
echo Installed THREE source files. Existing RaceSectionals.tsx backed up to:
echo   %PACKAGE%backup\RaceSectionals.tsx
echo.
echo Now run these commands in your horse project root:
echo   npm run typecheck
echo   npm run build
echo   npm run dev
echo.
echo Do NOT push to GitHub until the build and live-data chart checks pass.
pause
exit /b 0
:fail
echo.
echo ERROR: A file copy failed. Restore RaceSectionals.tsx from %PACKAGE%backup if necessary.
pause
exit /b 1
