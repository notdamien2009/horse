HORSE SECTIONALS V4 — REPOSITORY-SPECIFIC DROP-IN (17 Nov 2026)
Source: notdamien2009/horse, main commit 8b7d8173c9e122bf9f625c10e53f8e564e87c0b1

Correct location: HORSE WEBSITE REPO ROOT / web / src / components.
This is NOT the root 'src' folder or the Python 'site' folder.

Includes three files:
web/src/components/RaceSectionals.tsx           (replaces existing)
web/src/components/SectionalPaceChart.tsx        (new)
web/src/components/SectionalPaceChart.module.css (new)

Install:
1. Make sure your local horse repo is up to date and contains web/src/components/RaceSectionals.tsx.
2. Extract the ZIP anywhere: it contains a HORSE-SECTIONALS-V4 folder. Do not copy it directly into src.
3. Run INSTALL_SECTIONALS_V4.bat from inside that folder.
   If the folder is not inside the horse repository root, it will ask for the location.
   The installer backs up the original RaceSectionals.tsx before replacing it.
4. Open Command Prompt at the ROOT. Run: npm run typecheck
5. Run: npm run build
6. Visit http://localhost:3050/race/949447/sectionals with npm run dev.
7. Compare genuine last-run and averaged sector readings with the original table.
8. Once verified, stage ONLY the three components and push using your normal Git workflow.

Changes:
- Shape-preserving curved sectional lines (not interpolated performance readings)
- 'Best rated run' vs 'Strongest close' vs 'Biggest late lift' with independent rankings
- Select up to 3 horses; the rest are ghosted; finishing zoom and section inspection
- Search, keyboard operation, mobile finish-first scrolling
- Previous race header and table preserved; original figures/FSP/pace labeling supplied by site

SAFETY:
- No Supabase write, migrations, collector or ranking-model changes.
- Missing checkpoint data are null (never zero). Histories with fewer than 2 measured runs have no averaged trend.
- This is a display of HISTORICAL race runs for horses in today's racecard, not a head-to-head trace of one race.
- Par data reflect what the existing site supplies. Adjusted figs aren't recalculated.
- Always confirm source per race and check different course/distance before using pace rankings to bet.
- No push/deployment performed by ChatGPT.
