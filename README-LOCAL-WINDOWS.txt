SPORTING LIFE LOCAL BACKGROUND COLLECTOR – WINDOWS
===============================================
This ZIP is a local runner for your EXISTING GitHub project. It contains NO new
scraper. It runs src/backfill_controller.py and preserves your existing SQLite
schema, QA checks, source restrictions and resume logic.

Before use
----------
1) Only collect live Sporting Life results with the necessary permission. The
   site's published terms prohibit unauthorised automated data capture. No
   access-control bypass is included. If you have no authorisation, leave
   source_access_authorised set to false and use VERIFY_SETUP only.
2) Disable the GitHub collector while local collection is your master source:
   Set BOTH SL_SCHEDULE_ENABLED and SL_HALFHOURLY_ENABLED to false in GitHub
   Actions repository variables. Running GitHub and Windows against separate
   databases does not synchronise or merge their data; do not overwrite either.
3) Clone your PRIVATE repository's latest main branch to your PC:

      gh repo clone notdamien2009/horse

   or use the GitHub Code -> Download ZIP for the latest main and extract it.
   Use a separate new folder if you already have an old v2.7 local collector.
4) Extract the nine files in this package into the repository's ROOT folder,
   alongside src/, tools/ and data/. DO NOT put them inside src/.
5) Python 3.12 installed with the Windows Python Launcher and dependencies:

      py -3 -m pip install -r src\requirements.txt

6) If data\racing_history.sqlite does not exist, double-click
   BOOTSTRAP_FROM_GITHUB_ONCE.bat. This downloads the latest private SQLite
   release using GitHub CLI. It refuses to overwrite an existing database.
   Check that it contains the newest saved count (401 races in previous run).
7) Double-click VERIFY_SETUP.bat. It checks SQLite integrity and data tables,
   without accessing Sporting Life.

How to run
----------
8) In local_collector_config.json change "source_access_authorised" from
   false to true ONLY IF you have the necessary permission. Keep the defaults
   for a conservative first run.
9) Double-click RUN_ONE_BATCH_TEST.bat (a single batch, up to 20 races).
   Inspect data\local_runner\background.log and CHECK_STATUS.bat.
10) Double-click START_BACKGROUND.bat. It launches a no-console Python worker,
    returning control to Windows. The PC must remain powered on and connected
    to the Internet. The worker repeats one batch at a time, resuming the same
    SQLite, up to 20 races each. It exits on access, transport and serious QA
    errors rather than bypassing them.
11) Double-click CHECK_STATUS.bat anytime to see saved race/runner totals.
12) Double-click STOP_SAFELY.bat to stop AFTER the current bounded batch.

Files and safety
----------------
- data\racing_history.sqlite: only LOCAL database (don't overwrite from cloud).
- data\local_runner\background.log: rolling collector log, including errors.
- data\local_runner\status.json: last reported state and race counts.
- data\local_runner\backups\*.sqlite.gz: up to 8 consistent SQLite snapshots,
  saved at start and about every 30 minutes.
- data\backfill_logs\failed_race_pages.csv: isolated parser failures to repair.
- Uses an OS-managed single-instance lock to avoid two local workers.
- Default request spacing remains 6 seconds, plus 15 seconds between batches.
- This runner is local only. It does NOT upload its results back to GitHub.
- A laptop going to sleep, a Windows restart or closing the Python process will
  stop it; run START_BACKGROUND again after login. Manual startup is deliberate.
- Data may be incomplete/unverified; NO speed standards are calculated.

Important limitation
--------------------
A single race's parser error remains quarantined. Structural QA thresholds,
transport issues, no new-race progress, and access restrictions still stop the
process. This is intentional: it avoids accumulating unreliable data silently.
No website access was used when preparing/testing this package.
