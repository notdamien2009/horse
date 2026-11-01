# HORSE RACING — v2.7 DATA COLLECTION AND REVIEW

**Read this before running.** This contains the user's recovered 28 races/242 runner records as of the prior v2.6 recovery. It does not claim to contain the complete 2022–2026 archive. No new historical results were downloaded during packaging.

## View the data right now
1. Open `data/exports/races_all.csv` and `data/exports/runners_all.csv` in Excel. Those CSV files refresh when you use `EXPORT_MY_DATA.bat`. The included `RECOVERED_SNAPSHOT_28_RACES.xlsx` is a **fixed old snapshot**, not a live workbook.
2. Double-click `CHECK_MY_DATA.bat` to see exact saved counts and uncollected days.
3. Double-click `EXPORT_MY_DATA.bat` to regenerate the CSVs from the CURRENT SQLite without resetting your database. The old `RECHECK_AND_EXPORT.bat` filename is now a safe shortcut to `EXPORT_MY_DATA.bat`: it does not rebuild or reset the database.

## Historical collection
1. Run `INSTALL.bat` once to install `requests`/`beautifulsoup4` and check parser.
2. If you have permission to collect the racing pages, run `RUN_HISTORY_COLLECTION.bat`. It automatically creates a timestamped database backup, uses the current `data/racing_history.sqlite`, processes history 2022-01-01 through 2026-10-31, and saves checkpoints after each race.
3. It does **not** bypass website access restrictions, CAPTCHA, authentication, or traffic controls. It stops on access errors and widespread QA failures. If a source no longer provides access, use a permitted bulk export instead.
4. After every stop, the launcher exports the saved data, the daily date-by-date coverage report, and the race QA list. Restarting the launcher resumes rather than duplicating completed race IDs.
5. A date with saved races is **not** proof all races on that day were collected. `history_coverage_2022_2026.csv` identifies missing local dates and warns that saved dates need cross-checking.

## Files
- `data/racing_history.sqlite`: canonical database
- `data/backups`: auto-created verified backups
- `data/exports/races_all.csv`: race metadata/winning times
- `data/exports/runners_all.csv`: runner weights/comments/margins/statuses
- `data/exports/history_coverage_2022_2026.csv`: all calendar dates
- `data/exports/review_races.csv`: individual flagged races
- `data/backfill_logs/run.log`: crawler error messages and checkpoints

## Preserving your speed calculation methodology
The user's legacy `nk=0.01` and finishing-order cumulative margins are preserved; `winning_time + margin` is a historic scoring convention **not an observed time in seconds**. No standard-time models are generated until racecourse configuration and winning-time QA are complete.

## Important limits
The recovered sample is tiny compared with a five-year archive. This environment has no direct Python Internet access to run bulk site collection. A working source is not proof of permission to copy all historical data. Sporting Life's published terms restrict automated collection; do not override access controls or keep retrying a denied source.
