# v3.3: optional 30-minute scheduled collector

This change adds a **fully opt-in**, frequent schedule. It does not automatically enable it or start new source requests. **Only run live data collection with Sporting Life permission**; Sporting Life's public terms prohibit automated data capture/scraping.

## What changes
- GitHub Actions cron: **17 and 47 minutes past every UTC hour** (48 opportunities per day). GitHub's schedule is best effort and can be delayed or dropped at high load.
- **18-minute collection budget** on half-hour runs, checked between batches. The current 6-second minimum between requests is unchanged. A single batch may carry the job slightly beyond 18 minutes, and setup/export/checkpoint also take time.
- Current **daily** 03:27 UTC schedule remains the fallback and keeps its 48-minute collection budget. When half-hour mode is enabled, the daily mode is **disabled**, so it doesn't create an extra overlapping batch.
- Existing `concurrency: cancel-in-progress: false` remains, preventing simultaneous runs overwriting the same private SQLite release.
- All QA, source checks, private-only gate and two-checkpoint rollback protection are preserved.
- Manual `verify` and `collect` remain available.

## Explicit activation
1. Review and merge this PR on the PRIVATE repository.
2. Run manual `verify` and confirm all offline regressions and checkpoint export.
3. Check GitHub **Settings > Billing and licensing > Budgets and alerts** for the account; set a firm Actions budget/spending limit before opting into the higher frequency.
4. **Only with permitted source access**, set repository Actions variables to exactly:
   - `SL_COLLECTION_ENABLED=true`
   - `SL_HALFHOURLY_ENABLED=true`
   - `SL_SCHEDULE_ENABLED=true` can remain, but the daily fallback will not execute while half-hour mode is enabled.
5. To go back to the current daily schedule, set `SL_HALFHOURLY_ENABLED=false`. To suspend all scheduled collection, set both schedule variables to false.

## Cost / time warning
- Maximum potential ≈48 runs/day × roughly 18–25 minutes/job = **864–1,200 Actions minutes per day**, or around **26,000–36,000 minutes per 30-day month**. This is an indicative upper-usage scenario, not a promise about race capture.
- GitHub Free currently lists **2,000 Actions minutes/month** for eligible private repositories, with plan-dependent included usage; beyond that, there may be charges or jobs may not start. Your exact account's available minutes and payment settings aren't visible through the GitHub connector.
- Increasing schedule frequency is **not** permission to raise the request rate, evade rate limiting, bypass CAPTCHA/access controls or mass-scrape an unlicensed website. Contact Sporting Life for authorised export/data feed if high-throughput backfill is needed.

## Verification
`python src/sl_history.py --self-test`
`python -m unittest discover -s tests -p 'test_v30_improvements.py' -v`
`python -m unittest discover -s tests -p 'test_v31_isolated_race_errors.py' -v`
`python -m unittest discover -s tests -p 'test_v32_unattended_schedule.py' -v`
`python -m unittest discover -s tests -p 'test_v33_half_hour_schedule.py' -v`

These are offline unit tests. No live source collection is triggered by this PR.
