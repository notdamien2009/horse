# Sporting Life historical collection improvements (v3.0)

This branch contains **code only**, no scraped racing records. Uses Sporting Life as the **only results source**. ATR sectional data remains a separate project; Kaggle is not used.

## Changes

- **Accurate provenance:** missing `surface` is set to broad `All-Weather` only for Flat races with going `Standard`, `Standard to Slow` or `Standard to Fast`; records also receive `surface_inferred_from_going`. This does **not** identify Tapeta/Polytrack, confirm the racecourse configuration, or approve standards.
- **Existing database repair:** `python tools/repair_surface.py --database data/racing_history.sqlite --apply`. Idempotent, transactional; first repair creates `racing_history.before_surface_repair.sqlite` locally. The private cloud workflow runs this after loading its prior checkpoint.
- **QA breakdown:** `python tools/qa_diagnostics.py --database data/racing_history.sqlite --output-dir data/exports` writes `qa_diagnostics.json` and `qa_flags_by_track.csv`. It keeps distinct structural errors separate from all standards-only caveats. The workflow uploads these with the usual race and runner CSVs.
- **Historical order:** `--date-order newest|oldest` accepted by the collector and backfill controller. Latest-first remains the backwards-compatible default. In GitHub Actions, choose the new `date_order` option when manually running.
- **Bounded throughput:** 12 batches of at most 20 race pages, using the existing 6-second between-request delay. This limits *work per job*, not the size of the archive. The 90-minute job limit, existing stop-on-access-denial, and source-permission guard remain.
- **Regression CI:** `collector-tests.yml` checks the parser and new behaviours on pull requests without opening the website.

## Tested against saved data

As of GitHub Run #2: 209 race rows, 2,132 runner rows. Original flags included 27 `missing_surface` cases, 112 races with unconverted symbolic margins, and 209 `course_configuration_unverified` flags. The repair matched exactly 27 safely inferable cases; a second pass changed zero records. All 209 remained **unapproved for standards**. Local parser self-tests plus 12 unit tests passed. The new GitHub workflow has not yet been run.

## Important QA limitations

- `nk=0.01` remains the user's original legacy convention. `hd`, `sh`, `nse`, etc. are still preserved as unconverted text because equivalent values have **not** been approved. No fabricated elapsed clock times are introduced.
- Course configuration, changing track surfaces and full runner validation remain separate QA tasks.
- Race result pages may lack races on genuinely empty calendar dates; the collector must not silently claim a date with no links as complete. Investigate a zero-link date or index error rather than skipping unknown results.
- Downloading all of 2022–2026 will require multiple successful runs and source access compatible with site conditions. No access-control bypass is included.

## How to use

After PR approval and merging, run **Sporting Life private archive** in `verify` mode once. Confirm the new QA artifact files and that the stored race count stays at least 209. Then continue authorised `collect` runs as appropriate. Preserve local backups and review the QA flag summary after each run. GitHub's private Release checkpoint is the shared cloud state.
