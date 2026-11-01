# Horse racing data — GitHub Actions setup

This branch prepares a **private-only** collection workflow. It does not contain or publish any racing results. No live collection has been started.

## Repository safety
1. Make `notdamien2009/horse` **private** under GitHub Settings → General → Danger Zone → Change repository visibility.
2. Merge the workflow PR after review.
3. Add the tested collector source from the supplied project ZIP to the repository (`src/`, `tools/`, `src/requirements.txt`).
4. Add a baseline `seed/racing_history.sqlite` **only after the repository is private**, preferably the latest live SQLite from the PC (currently ahead of the older recovered checkpoint). Do not upload the SQLite `-wal`/`-shm` sidecars.
5. GitHub Actions → *Sporting Life private archive* → *Run workflow* → **verify**. Confirm the database is recognised and QA exports were produced.
6. Live collection is disabled unless repository variable `SL_COLLECTION_ENABLED` equals `true` and the operation is `collect`. Only enable after obtaining the necessary source permission.

## Reliability principles
- Input provider: Sporting Life only. Kaggle and ATR are not ingested.
- The existing collector must recognise original results, non-finishers and full comments; `nk=0.01` is preserved as the user's historic conversion.
- Fixed `--batch-races` is only a per-run workload bound, **not a cap on the total archive**. Continue across runs using SQLite state.
- Latest database is restored from a PRIVATE prerelease asset on subsequent runs. The seed is used only before the first checkpoint.
- Workflow jobs stop on access errors or serious QA failures, never attempt access-control workarounds.
- Race-level verification is separate from capture; no record with unresolved critical QA should be accepted for speed standards.
- Keep the latest PC SQLite as the canonical source until the first successful GitHub checkpoint is compared against it.
- Schedule: daily 03:27 UTC (subject to GitHub scheduling and usage limits), initially gated.
- Review each run's `sportinglife-results-...` artifact: race CSV, runner CSV, missing date report, review races and log.

## Current situation
- Local PC screenshot: 88 races, 831 horse rows, 3 indexed dates and 9 critical QA flags. This newer local database has NOT been transferred to GitHub.
- Recovered offline checkpoint: 28 races and 242 horse rows.
- The GitHub repository was public when this branch was created. **Do not publish either database while public.**
- Neither the workflow nor the complete 2022–2026 collection has yet been run on GitHub.
