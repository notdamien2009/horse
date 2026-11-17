@echo off
setlocal EnableExtensions DisableDelayedExpansion
title FurlongIQ - Restore Original Racecard and Sectionals

rem Safe reversal of FurlongIQ Race Intelligence V1.
rem Windows Command Prompt only - no PowerShell required.
rem Originals verified against notdamien2009/horse GitHub main.

cls
echo ==============================================================
echo         FURLONGIQ - RESTORE ORIGINAL WEBSITE UI
echo ==============================================================
echo.
echo Restores the original race page and Sectionals component,
echo and removes 3 files that were ADDED by Intelligence V1.
echo This does NOT touch Supabase, speed figures, or GitHub.
echo.

rem Ensure the complete archive has been extracted.
for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
) do (
 if not exist "%~dp0original\%%~F" (
  echo ERROR: Missing rollback original: %%~F
  echo Extract the entire ZIP, then run this BAT from the extracted folder.
  goto :fail
 )
)
for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
 "web\src\components\RaceIntelligence.tsx"
 "web\src\components\RaceIntelligence.module.css"
 "web\src\components\RaceSectionals.module.css"
) do (
 if not exist "%~dp0upgrade-checks\%%~F" (
  echo ERROR: Missing upgrade fingerprint file: %%~F
  goto :fail
 )
)

set "ProjectRoot=%~1"
if not defined ProjectRoot set /p "ProjectRoot=Paste your HORSE project folder path and press Enter: "
if not defined ProjectRoot (
 echo ERROR: No project path was provided.
 goto :fail
)
set "ProjectRoot=%ProjectRoot:"=%"
for %%I in ("%ProjectRoot%") do set "ProjectRoot=%%~fI"

rem Check exact project structure before making any changes.
for %%F in (
 "package.json"
 "web\src\lib\racing.ts"
 "web\src\components\RaceCard.tsx"
 "web\src\components\RaceSectionals.tsx"
 "web\src\app\race\[id]\page.tsx"
) do (
 if not exist "%ProjectRoot%\%%~F" (
  echo ERROR: Cannot find %%~F in this project folder.
  echo No files have been changed.
  goto :fail
 )
)

echo.
echo Project located: %ProjectRoot%
echo Verifying that files match Intelligence V1 or GitHub originals...
echo.

rem Protect any subsequent independent edits. Only alter the exact
rem V1 upgrade contents (or originals that have already been restored).
for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
) do (
 fc /B "%ProjectRoot%\%%~F" "%~dp0upgrade-checks\%%~F" >nul 2>&1
 if errorlevel 1 (
  fc /B "%ProjectRoot%\%%~F" "%~dp0original\%%~F" >nul 2>&1
  if errorlevel 1 (
   echo ERROR: %%~F has changed since the V1 upgrade.
   echo Rollback aborted to protect your later edits.
   echo No files have been changed.
   goto :fail
  )
 )
)
for %%F in (
 "web\src\components\RaceIntelligence.tsx"
 "web\src\components\RaceIntelligence.module.css"
 "web\src\components\RaceSectionals.module.css"
) do (
 if exist "%ProjectRoot%\%%~F" (
  fc /B "%ProjectRoot%\%%~F" "%~dp0upgrade-checks\%%~F" >nul 2>&1
  if errorlevel 1 (
   echo ERROR: %%~F has changed since the V1 upgrade.
   echo Rollback aborted to protect your later edits.
   echo No files have been changed.
   goto :fail
  )
 )
)

rem Create a NEW safety backup outside the repository, before editing.
for %%I in ("%ProjectRoot%\..") do set "BackupParent=%%~fI"
set "BackupBase=%BackupParent%\FURLONGIQ-ROLLBACK-SAFETY-BACKUP-V1"
set "BackupRoot=%BackupBase%"
set /a Suffix=2
:chooseBackup
if exist "%BackupRoot%" (
 set "BackupRoot=%BackupBase%-%Suffix%"
 set /a Suffix+=1
 goto :chooseBackup
)
mkdir "%BackupRoot%" >nul 2>&1
if errorlevel 1 (
 echo ERROR: Unable to create the safety backup folder.
 echo No files have been changed.
 goto :fail
)

for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
 "web\src\components\RaceIntelligence.tsx"
 "web\src\components\RaceIntelligence.module.css"
 "web\src\components\RaceSectionals.module.css"
) do (
 if exist "%ProjectRoot%\%%~F" (
  for %%D in ("%BackupRoot%\%%~F") do if not exist "%%~dpD" mkdir "%%~dpD" >nul 2>&1
  copy /Y "%ProjectRoot%\%%~F" "%BackupRoot%\%%~F" >nul
  if errorlevel 1 (
   echo ERROR: Could not back up %%~F
   echo No project files have been changed.
   goto :fail
  )
 )
)

echo Backup safely stored OUTSIDE your project:
echo %BackupRoot%
echo.
echo Restoring original files...

for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
) do (
 copy /Y "%~dp0original\%%~F" "%ProjectRoot%\%%~F" >nul
 if errorlevel 1 (
  echo ERROR: Could not restore %%~F
  goto :undoPartial
 )
 echo Restored: %%~F
)

for %%F in (
 "web\src\components\RaceIntelligence.tsx"
 "web\src\components\RaceIntelligence.module.css"
 "web\src\components\RaceSectionals.module.css"
) do (
 if exist "%ProjectRoot%\%%~F" (
  del /F /Q "%ProjectRoot%\%%~F" >nul 2>&1
  if exist "%ProjectRoot%\%%~F" (
   echo ERROR: Could not remove %%~F
   goto :undoPartial
  )
  echo Removed: %%~F
 ) else (
  echo Already removed: %%~F
 )
)

echo.
echo ==============================================================
echo          RESTORE COMPLETED - ORIGINAL UI RESTORED
 echo ==============================================================
echo.
echo Your 2 original GitHub files are back; 3 V1 additions removed.
echo No Supabase or GitHub changes were made.
echo Safety backup: %BackupRoot%
echo.
echo Now restart the FurlongIQ website and check racecards/Sectionals.
echo.
pause
exit /b 0

:undoPartial
echo.
echo An operation failed. Attempting to undo partial rollback...
for %%F in (
 "web\src\app\race\[id]\page.tsx"
 "web\src\components\RaceSectionals.tsx"
 "web\src\components\RaceIntelligence.tsx"
 "web\src\components\RaceIntelligence.module.css"
 "web\src\components\RaceSectionals.module.css"
) do (
 if exist "%BackupRoot%\%%~F" (
  copy /Y "%BackupRoot%\%%~F" "%ProjectRoot%\%%~F" >nul
 ) else (
  if exist "%ProjectRoot%\%%~F" del /F /Q "%ProjectRoot%\%%~F" >nul 2>&1
 )
)
echo Please inspect the project. Safety backup: %BackupRoot%
goto :fail

:fail
echo.
echo Restore stopped. Read the message above.
pause
exit /b 1
