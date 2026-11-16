@echo off
setlocal
cd /d "%~dp0"
title Upload FurlongIQ data to horse Supabase
if not exist ".env" (
  echo.
  echo Missing .env in the Speeds folder.
  echo Copy .env.example to .env and paste your horse Supabase URL and service role key.
  echo The service role key is in Supabase: Project Settings - API - service_role ^(secret^).
  echo Do not put that key in Vercel or in git.
  echo.
  pause
  exit /b 1
)
where python >nul 2>nul
if not errorlevel 1 (
  python tools\upload_to_supabase.py
  goto :done
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 tools\upload_to_supabase.py
  goto :done
)
echo Python was not found. Install Python 3, then rerun this file.
pause
exit /b 1
:done
if errorlevel 1 (
  echo.
  echo Upload failed.
  pause
  exit /b 1
)
echo.
pause
