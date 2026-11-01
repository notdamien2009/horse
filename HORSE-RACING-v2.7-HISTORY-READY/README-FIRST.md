# Horse Racing Speed Figures — Recovery v2.6

## What this package really contains

This release consolidates the user's surviving v2.4 SQLite and corrected CSV exports. The old raw files are not destroyed.

| Year | Races | Horse records | Distinct dates | Complete? |
|---|---:|---:|---:|---|
| 2022 | 3 | 36 | 1 | NO |
| 2023 | 0 | 0 | 0 | NO |
| 2024 | 0 | 0 | 0 | NO |
| 2025 | 0 | 0 | 0 | NO |
| 2026 | 25 | 206 | 1 | NO |
| **Total** | **28** | **242** | **2** | **NO** |

Period tracked: **2022-01-01 to 2026-10-31** (1,765 calendar dates). Every date without records is marked **NOT COLLECTED**, not "no racing". Even the two dates with records are not yet independently confirmed complete.

### Find your data immediately

- **Excel:** `data/exports/horse_results_2022_2026_RECOVERED_PARTIAL.xlsx`
- **Race CSV:** `data/exports/races_all.csv`
- **Runner CSV:** `data/exports/runners_all.csv`
- **Main SQLite database:** `data/racing_history.sqlite`
- **QA list:** `data/exports/qa_issues.csv`
- **Date coverage:** `data/exports/coverage_calendar.csv`
- **Backup of uploaded original SQLite:** `seed/original_racing_history.sqlite`

The original SQLite contained 20 races, 162 runners. Recovery added three repaired 2022 races and five additional 2026 races. It also added 21 older runner records missing from the SQLite for races already present, and 23 runners from the five newly recovered races. All original IDs and available running comments are retained. No source/record conflicts were detected for the overlapping rows that were preserved.

**QA:** All 28 races still have unverified course configuration. There are 11 races where at least one cumulative margin cannot be reconstructed from the saved fields, two races with unconfirmed result status, one amended result with non-contiguous placings, and one race with an apparent starter-count mismatch. **ZERO races are yet approved for standard-time calculation.** Absence of QA errors never proves full field correctness.

## Windows — inspect or regenerate your recovered data

1. Unzip the release somewhere safe, e.g. `Documents\horse-racing-research`.
2. Open the `data\exports` folder to view the Excel or CSV sheets. **No installation is needed just to open them.**
3. To regenerate the CSV reports, double-click `RECHECK_AND_EXPORT.bat` (uses Python's standard library).
4. Keep backups of `data\racing_history.sqlite`, and do not delete `seed` until you have additional backups.

### Import a future batch from a permitted data source

```
py tools\import_pair.py --races "C:\path\races.csv" --runners "C:\path\runners.csv"
```

Expected data fields match `data/exports/races_all.csv` and `runners_all.csv`. The script inserts missing IDs, preserves existing records on conflicts, records conflicting fields in `source_conflicts.csv`, and regenerates QA. It never assumes a date is complete merely because a race was imported.

### Running tests

```
py tests\test_recovery.py
```

Seven recovery tests were run successfully here. They test SQLite integrity, 28 race/242 runner counts, ID uniqueness, legacy statuses, output size, old database preservation and exclusion from standards. Earlier v2.5 parser/controller offline tests also passed on 1 November 2026. Live 2022–2026 collection was **not** completed or retested in this release.

### About the old collection scripts

For reference, the unmodified prior v2.5 collector source and fixtures are under `legacy_collector_v25/`. They are **not** a verified or authorised mass-collection route. Sporting Life's terms expressly prohibit data capture including scraping. Respect access controls; don't run proxy/captcha workarounds or rely on repeated small batches to override terms. The reliable long-term route is a licensed/open historical export or express permission, imported into this database.

## Speed figures — not implemented yet

- Flat reference weight: **9st / 126 lb**
- Hurdles and chases reference: **11st / 154 lb**
- National Hunt Flat reference: undecided, so left blank
- Your legacy `nk = 0.01` remains in data where previously converted
- `legacy_win_time_plus_dist` is **NOT a measured horse finish time**: it adds a margin measured in nominal lengths to seconds. Preserve it for historical comparison, but establish a validated seconds-per-length model before producing new ratings.
- Standard-time methodology: cleaned, going/weight-normalised historical times by exact course, distance, layout and era; evaluate a 40th-percentile baseline out-of-sample.

## GitHub recommendation

The connected `notdamien2009/horse` repository was **empty and public** when inspected. Make it private before using it for a research project. Store version-controlled code and tests there; keep `data/` and the original raw data OUT of ordinary Git. The `.gitignore` excludes them by default. No code was pushed to GitHub as part of this recovery.
