# v3.2 – unattended daily historical archive (prepared, gated)

The repository already has GitHub's daily schedule. This PR changes the **automatic** run to oldest-first collection and makes the run longer and checkpoint-safe. It does **not** enable source collection by itself.

## Schedule and runtime

- Runs **daily at 03:27 UTC** on private `main` (scheduled runs do not require the owner's computer or manual clicks).
- Runs only when **both** GitHub repository variables are present as strings: `SL_COLLECTION_ENABLED=true` and `SL_SCHEDULE_ENABLED=true`. **Set these only after obtaining permission/licensed access to the intended source.**
- Explicitly sets the **oldest-first** traversal for scheduled runs, so the collection moves through 2022 rather than restarting from 2026.
- Maximum 36 batches × 20 race pages per job, at the existing minimum 6-second delay. **Graceful collector time budget 48 minutes**: finishes the active batch and exits cleanly, leaving ample time for CSV exports and release backup within the 90-minute job timeout.
- Manual `verify` / `collect` dispatches remain supported, and their date order remains selectable. The permission gate for manual live collection is unchanged.
- A new `racing_history.previous.sqlite.gz` Release asset preserves the immediately preceding complete checkpoint before overwriting `racing_history.sqlite.gz`. Both stay in the **private** release. Job artifacts contain QA/CSV reports.

## No manual dispatch necessary after setup

Merge this PR; run `verify` once and inspect tests. Once the relevant Sporting Life source permissions are secured, set `SL_SCHEDULE_ENABLED` to `true` under **Settings → Secrets and variables → Actions → Variables**. If `SL_COLLECTION_ENABLED` is not `true`, set it as appropriate for the granted permission. After that, GitHub schedules the runs on its own. **No recurring button presses.**

Important: Sporting Life's published terms expressly prohibit automated data capture without written permission. This collector does not bypass access controls, retries against denied access, or lift that restriction. If access is unavailable, leave the scheduled variable disabled and seek an authorised data feed.

## Usage and QA

- The latest saved checkpoint at PR creation contained **401 races, 4,059 runner rows**, with incomplete history and unresolved QA warnings.
- At 48 min/day plus setup/export overhead, expected private-repository GitHub Actions usage is roughly 1,500 minutes per 30-day month if each run fills its budget. Confirm actual GitHub plan limits and billing controls; other workflows also consume minutes.
- No process can guarantee full completion unattended. A genuine access-denial, transport error, date-index failure or systemic QA fault still stops collection rather than quietly skipping data. GitHub's run log and failure emails remain the mechanism for escalation.
- Records marked incomplete/unverified never become eligible for speed standards merely because collection progresses.
- Source data never enters Git commits. The runner maintains the private SQLite release plus CSV artifact reports.
- Historical file collection is **not** triggered by this PR, nor by its offline tests.

## QA before merge

`python src/sl_history.py --self-test`

`python -m unittest discover -s tests -p 'test_v30_improvements.py' -v`

`python -m unittest discover -s tests -p 'test_v31_isolated_race_errors.py' -v`

`python -m unittest discover -s tests -p 'test_v32_unattended_schedule.py' -v`

These tests do not make network requests.
