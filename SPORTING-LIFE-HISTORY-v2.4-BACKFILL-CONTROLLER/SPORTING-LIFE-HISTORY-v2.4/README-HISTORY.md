# Sporting Life historical backfill controller — v2.4

Period: **1 January 2022 through 21 October 2026**, inclusive. Today's racing (22 October 2026) is omitted to avoid unfinished races. It can be added after official results settle.

## What to run

1. Keep a backup of `data/racing_history.sqlite` from v2.3. Extract this ZIP to a **new folder** and copy your existing `data/` directory into it before starting.
2. Run `INSTALL.bat` and `RUN_ALL_OFFLINE_TESTS.bat`.
3. Run `PILOT_BACKFILL.bat` for up to 3 bounded one-day batches and **manually verify a Flat, a hurdles and a chase race** against source records. The pilot stops if newly parsed races receive QA-review or critical flags.
4. Only after those checks pass, and only with authorised access, run `FULL_HISTORY_BACKFILL.bat`. It works through the date range in bounded sequential batches without requiring an individual click for every page. It stops on site access restrictions, failures, critical QA findings, missing forward progress or Ctrl+C.
5. To check state, use `SHOW_PROGRESS.bat`; to export consolidated CSVs, run `EXPORT_RESULTS.bat` after a safe checkpoint.

## Critical safeguards

- No CAPTCHA, blocking or access-control bypass. HTTP 401/403/429 or a challenge aborts the run; do not automatically retry around restrictions. Sporting Life's published terms restrict scraping and data capture.
- The collection is **restartable** using race IDs in SQLite. Restarting does not re-fetch successfully parsed races by default.
- Logs at `data/backfill_logs/run.log` and `progress.csv` provide a record of what actually happened.
- If a source page contains incomplete data, the database can preserve the race under QA review. **Do not use QA-review or unverified course layouts for standard-time calculations**.
- A day with no recognised results is reported as an error, not silently accepted as an empty race day; genuinely race-free dates require checking.
- CSV auto-export is disabled during repeated batches to reduce processing time. Use `EXPORT_RESULTS.bat` when ready.
- One launcher can process many batches, but it can take a long time on the user's computer and requires the process to stay running. No ongoing collection is occurring in ChatGPT.

## Known outstanding issues

- v2.3's live accuracy across dates and courses is not yet comprehensively verified; the pilot is required.
- Distances, runner counts, altered results, non-finishers, comments and symbolic margins need continued cross-checks. Margins such as `sh` and `hd` remain unknown rather than assigned invented numeric values. `nk = 0.01` per original convention.
- `course_configuration` is unverified. **Do not build standard times from these exports yet.**
- A completed date index doesn't guarantee every fixture was listed by the source; independent racecard or fixture coverage comparison remains necessary.

`BACKFILL_2022_TO_2026.bat` is a compatibility alias to the new full controller. It no longer runs a single 25-race batch and stops.
