# Sporting Life historical collector v2.3 — correct field ordering + QA

This release fixes the accuracy-check failures found in the **21 October 2022** live CSV exports.

## What was actually wrong

- The exported `runners_all.csv` was sorted by **horse ID**, not official finishing position. The validator added margins in that arbitrary order. All 55 previously reported errors were **false positives from the validator ordering**, not evidence of 55 corrupt ratings. The original cumulative numbers already matched when rows were correctly sorted.
- Some jockey fields absorbed the first words of running comments (`Mid-division...`, `Not always fluent...`) owing to a text-boundary heuristic. The parser now prioritises race-comment openings; the existing CSV can be repaired from saved `runner_text_raw` without guessing a horse or margin.
- Missing/unsupported fields stay blank and are reported, not invented. `course_configuration` and `declared_runners` are **not available with sufficient certainty** in these exports. Jumps nonfinishers (F/B/PU/UR) and NRs are kept with no artificial finishing times.

## How to update without losing your data

1. Keep and back up your original `data/racing_history.sqlite` and current CSVs.
2. Extract v2.3 to a new folder; copy your `data` folder to v2.3.
3. Run `RUN_ALL_OFFLINE_TESTS.bat`, followed by `RUN_QA_AFTER_EXPORT.bat`.
4. New exports sort finishers 1st, 2nd, 3rd, ... then F/PU/B etc, then NR. Validation sorts internally independently of CSV order.
5. To repair **existing CSV exports** without changing SQLite, copy `races_all.csv` and `runners_all.csv` into the v2.3 root and run `REPAIR_EXISTING_CSVS.bat`. They go into `corrected_exports/` so your originals remain untouched.
6. Updating comments inside a prior SQLite database requires re-importing repaired CSVs or re-parsing the corresponding source pages. Export-only preserves original database records; it cannot magically modify those stored values.

## Margin policy

- `nk` = **0.01**, by user's original conversion.
- Cumulative margin from preceding **finishers** (sorted positions) = `WinDist`.
- `legacy_win_time_plus_dist` = winning seconds + cumulative WinDist. This is the original **rating convention**, not a measured time for every horse.
- F/B/PU/UR/NR get no numeric adjusted finishing time. Any margin symbol without an explicit mapping remains unknown.

## Verification and limits

- Offline fixtures, CSV data and SQLite export are tested locally. No live race-page retrival is claimed here.
- Source HTML is not bundled. Some raw jockey/comment boundaries remain heuristic without HTML. `runner_text_raw` is preserved for review.
- Unknown course configuration (e.g. track layouts) prevents certification for new standard times.
- Sporting Life terms restrict bulk automated data collection. No access-control bypasses, login circumvention or challenge evasion in this package.

### One-click safe correction of already stored comments

`REPAIR_MY_SAVED_DATABASE.bat` creates a dated SQLite backup, repairs proven
truncated comments using `runner_text_raw` (no network requests), re-exports
races and runners in official finishing order and runs the independent QA.
It does **not** fill unavailable course configurations or unsupported beaten
margin abbreviations with invented numbers. It does not re-download results.
Keep the backup alongside your database until you have manually checked the
updated records.
