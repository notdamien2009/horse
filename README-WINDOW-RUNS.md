# Sporting Life historical archive — date-window controller

These files are an **add-on** to the existing `notdamien2009/horse` private repository, not a new collector or replacement database.

## Install (do not delete or overwrite the existing collector)

Copy into the repo:

- `tools/window_backfill.py`
- `tests/test_window_backfill.py`
- `.github/workflows/sportinglife-window.yml`

Keep `src/sl_history.py`, `src/backfill_controller.py`, `tools/sl_checkpoint.py`, the existing `.github/workflows/sportinglife.yml`, and the saved SQLite database/release intact. Do not commit scraped horse data.

## Recommended: use GitHub Actions

Open the repository's **Actions → Sporting Life windowed archive (manual) → Run workflow**. Choose:

- **operation = verify** first, for a safe checkpoint and coverage check (no collection).
- **window_months = 1** initially (or `3` for a quarterly block).
- **windows_per_run = 1** and **batch_count = 12** for a bounded run.
- Only use **operation = collect** after written Sporting Life source permission is secured and repository variable `SL_COLLECTION_ENABLED=true` is set. The website's published terms prohibit unlicensed screen scraping/data capture.

Repeat the same Run workflow action. Each launch selects the **oldest period not yet indexed** according to SQLite. If the batch limit stops partway through a month, the next run resumes that month. Once its daily indexes and queued race pages are processed, the next run advances to the next window. One known isolated race parse error will remain visibly quarantined; it will not prevent indexing later months. Source/transport failures or structural mismatches stop the run.

The new workflow uses the **same GitHub concurrency group and private Release checkpoint** as the old workflow, with rollback asset preservation. It is **manual only** and does not change the existing daily schedule.

## Local Windows PowerShell commands

Run in the root of a cloned repo containing the restored `data/racing_history.sqlite` checkpoint:

```powershell
python tools/window_backfill.py --mode status --months 1
python -m unittest discover -s tests -p test_window_backfill.py -v
```

For *permitted* live collection only, after written source permission and setting the repository-equivalent environment gate:

```powershell
$env:SL_COLLECTION_ENABLED = 'true'
python tools/window_backfill.py --mode collect --months 1 --windows 1 --batches 12 --batch-races 20 --delay 6
```

For three-month runs:

```powershell
python tools/window_backfill.py --mode collect --months 3 --windows 1 --batches 12 --batch-races 20 --delay 6
```

Never run the two workflows concurrently outside the GitHub Actions group. On a local checkout, checkpoint SQLite backups and restore remain the owner's responsibility.

## Files generated

- `data/backfill_logs/window_status.csv` — all month/quarter windows and progress.
- `data/backfill_logs/window_status.json` — machine-readable coverage details.
- `data/backfill_logs/windows/YYYYMMDD_YYYYMMDD/` — underlying controller's QA and log files.
- `data/exports/windows/YYYYMMDD_YYYYMMDD/races.csv` — all saved race metadata for the selected window.
- `data/exports/windows/YYYYMMDD_YYYYMMDD/runners.csv` — all saved runners, status, finishing position, retained data fields and original identifiers.
- `data/exports/windows/YYYYMMDD_YYYYMMDD/coverage.json` — matching unverified coverage status and QA counts.

The existing full-database export files and original source IDs remain supported.

### Coverage labels

- `not_started` — no local evidence yet.
- `in_progress` — some dates or race pages remain pending.
- `indexed_audit_required` — all window days indexed, queued pages processed, **not** independently verified complete.
- `indexed_with_qa_holds` — days indexed but one or more known incomplete race parses held for manual repair. **Never** label the period verified complete.
- `blocked_review_required` — source or transport failure, date-index error, missing runner records, or mismatch; investigate before proceeding.

Monthly or quarterly batching changes *how work is scheduled*, not proof that all real-world fixtures were found. Independently check against Sporting Life's official meeting/result list where access is authorised.

## Verification performed

The package's offline unit tests exercise date boundaries, quarter/leap-year ranges, SQLite resuming, missing runners, index/queue mismatches, isolated parse holds, access errors, source-gated live mode, CSV outputs, and missing checkpoint protections. No live request to Sporting Life or user's private saved SQLite release was run during package creation.
