# v2.5 — Historical checkpoint repair (22 October 2026)

## Why your screen stopped

The v2.4 controller refused to start because the *existing* SQLite database contained two races with QA-critical flags, race IDs `944565` (Newmarket) and `944574` (Fontwell). It was **not** an HTTP / Sporting Life access refusal. Your screenshot showed **20 saved races, 1 indexed day, 17 pending race pages**.

- 944565 has `not_confirmed_weighed_in` and an old `finish_order_gap_or_duplicate` flag. One cause of the latter was a v2.4 bug: checking input/HTML horse order rather than sorted finishing positions. This is corrected for **new parses**.
- 944574 has `not_confirmed_weighed_in`, unmatched positions and an amended result. It still needs manual review before speed standards.

## v2.5 behaviour

- **Do not discard collected data.** Existing SQLite records remain intact.
- **Do not halt the entire archive for an existing imperfect race.** QA issues are written to `data/backfill_logs/quarantined_races.csv`, with exact race IDs and flags.
- **Never silently promote questionable data.** `standards_input_allowed` stays false for collector data. Quarantined races must be independently checked before computing speed standards.
- **Still stop** if collection fails, access is denied, a challenge appears, the job stops making progress, or the number of critical problems in *new* races indicates a systemic breakdown. Default stop threshold: 5 new critical races in one batch, or at least 30% critical after at least 10 new races. This is a conservative heuristic, not proof of quality.
- Incremental QA register (`backfill_qa_register`) avoids repeatedly scanning every historic race after each 20-race batch. It invalidates automatically if a saved race is updated/reparsed.
- A correct non-ascending source order (e.g. 4,3,5,6,1,2) does not cause a false finishing-position alarm for **new parses**.
- Missing margins, amended results, unknown/weighed-in status, runner mismatches still require review. No invented times, horse identities or winning margins.

## Install while preserving your progress

1. **Close any running collector** and copy the entire old `data` directory to a safe backup folder, especially `data/racing_history.sqlite` (and its `-wal` or `-shm` files if present; copy only with the collector closed).
2. Extract v2.5 to a **new folder**.
3. Copy your previous `data` directory into the new v2.5 folder. Do **not** replace the database with a blank one.
4. Run `RUN_ALL_OFFLINE_TESTS.bat` and check the PASS messages.
5. Run `SHOW_PROGRESS.bat`: it should show the existing archive and quarantine warnings without `STOP: ... existing races have critical QA flags`.
6. With suitable authorised access, run `FULL_HISTORY_BACKFILL.bat` to continue the configured 2022-01-01 to 2026-10-21 range. It picks up pending races; the logged QA issues are not discarded.
7. Monitor `data/backfill_logs/run.log`, `progress_v25.csv`, and `quarantined_races.csv`; do not assume every day is complete without a fixture-coverage audit.

**No live 2022–2026 backfill was performed here.** The new functionality passed only local fixtures and a simulated existing-database test. Whether the website allows further requests can only be established during authorised testing.

## Data accuracy limitation

The existing database has runner statuses and beaten margins, but it is **not yet standard-time-ready**. Course configuration is still unverified; the historical margin convention is `winning_time_seconds + cumulative_beaten_lengths` (not physically measured elapsed seconds); `nk = 0.01` is preserved, while unsupported `nse`/`hd`/`sh` values remain unknown. Source fields for amended results need independent confirmation.

The review CSV is a work queue, not a list of unusable races. Once a source is confirmed, record the approval separately rather than altering the original scraped text or deleting the QA history.
