FURLONGIQ: RESTORE ORIGINAL USER INTERFACE (17 NOVEMBER 2026)
============================================================

This package REVERSES the FurlongIQ Race Intelligence V1 drop-in.
It does NOT install a new UI.

1. Extract ALL contents of this ZIP into a folder OUTSIDE your horse project.
2. Double-click RESTORE_ORIGINAL_FURLONGIQ.bat.
3. Paste the full path to the HORSE project root (the folder containing package.json and web), then press Enter.
   Example: C:\Users\YourName\Desktop\horse
4. The BAT checks that you are pointing to the correct project and that the current files match the V1 upgrade.
5. It creates a NEW safety backup beside your HORSE folder before making changes.
6. It restores 2 original files and deletes 3 newly added upgrade-only files.
7. Restart your Next.js website and test the racecard and Sectionals tabs.

IMPORTANT: Double-click the BAT (Command Prompt); no PowerShell is used.

EXACT FILES RESTORED TO ORIGINAL GITHUB VERSION
------------------------------------------------
web\src\app\race\[id]\page.tsx
web\src\components\RaceSectionals.tsx

EXACT V1-ONLY FILES REMOVED
---------------------------
web\src\components\RaceIntelligence.tsx
web\src\components\RaceIntelligence.module.css
web\src\components\RaceSectionals.module.css

NOT CHANGED
-----------
web\src\components\RaceCard.tsx
web\src\components\SectionalPaceChart.tsx
web\src\lib\racing.ts
All Supabase tables, stored speed figures, data and prediction models.
Your GitHub repository, branches, commits and Vercel deployment.

SAFETY
------
- The installer refuses to overwrite independently edited files. If you changed one of the five UI files after applying V1, it stops and tells you which one.
- The installer uses Windows built-in 'fc /B' to compare exact file contents before making changes.
- Before edits, it saves copies of all five current files that exist in a NEW backup folder beside your horse project, named FURLONGIQ-ROLLBACK-SAFETY-BACKUP-V1 (or a numbered variation).
- The backup is deliberately OUTSIDE your horse project to avoid TypeScript/Next.js compiling backup .tsx files.
- If a file operation fails midway, the installer attempts to restore the files from this safety backup.
- Running it again is safe when the originals are already restored and the three additions are gone.

SOURCE VERIFICATION
-------------------
Original files were retrieved from the GitHub repository notdamien2009/horse, default branch main, on 17 November 2026.
Exact Git blob SHA1 checks:
  page.tsx             dcadec11041b858b46606f917422faa491920671
  RaceSectionals.tsx   7e4df4372cc17f8c3a4393d2e69f3b714b8db6f0

If your project was modified after the V1 install, use the backup and manual comparison instead of forcing a restore.
