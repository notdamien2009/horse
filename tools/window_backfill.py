#!/usr/bin/env python3
"""Date-window runner for the existing Sporting Life v3.2 research archive.

Install as tools/window_backfill.py in the private notdamien2009/horse repo.
Reuses src/backfill_controller.py and the existing SQLite checkpoint; DOES NOT
implement a new scraper, bypass access restrictions, or make network requests
when used in status mode. Live collection needs written source permission.

Run one month at a time:
  python tools/window_backfill.py --mode status --months 1
  SL_COLLECTION_ENABLED=true python tools/window_backfill.py --mode collect --months 1 --batches 12

For 3-month windows, use --months 3. Repeat the same collect command; already
indexed windows are skipped and unfinished windows resume from SQLite.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass, asdict
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEXED_STATUSES = frozenset({'indexed_audit_required', 'indexed_with_qa_holds'})
ISOLATED_ERRORS = frozenset({
    'Race extraction incomplete, check page and recorded details',
    'PARSE_INCOMPLETE: Race extraction incomplete, check page and recorded details',
})


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    @property
    def key(self) -> str:
        return f'{self.start:%Y%m%d}_{self.end:%Y%m%d}'

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def add_months(first: date, n: int) -> date:
    month_index = (first.year * 12 + first.month - 1) + n
    return date(month_index // 12, month_index % 12 + 1, 1)


def windows(start: date, end: date, months: int):
    if start > end or months not in (1, 3):
        raise ValueError('Invalid date range or months; choose 1 or 3.')
    current = start
    while current <= end:
        next_start = add_months(date(current.year, current.month, 1), months)
        window_end = min(end, next_start - timedelta(days=1))
        yield Window(current, window_end)
        current = window_end + timedelta(days=1)


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return (ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def connection(db: Path):
    if not db.is_file():
        raise FileNotFoundError(f'No existing database at {db}. Restore your previous checkpoint first.')
    con = sqlite3.connect(f'{db.as_uri()}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con


def window_stats(con: sqlite3.Connection, w: Window) -> dict:
    start, end = w.start.isoformat(), w.end.isoformat()
    days = con.execute('''
        SELECT index_state, COUNT(*) AS n, COALESCE(SUM(discovered), 0) AS discovered
        FROM days WHERE race_date BETWEEN ? AND ? GROUP BY index_state
    ''', (start, end)).fetchall()
    index_by_state = {r['index_state']: r['n'] for r in days}
    indexed = index_by_state.get('indexed', 0)
    indexed_errors = index_by_state.get('error', 0)
    unexpected_day_state = sum(v for k, v in index_by_state.items() if k not in ('indexed', 'error'))
    discovered = sum(r['discovered'] for r in days if r['index_state'] == 'indexed')

    qs = con.execute('''SELECT status, last_error, COUNT(*) AS n
        FROM race_queue WHERE race_date BETWEEN ? AND ?
        GROUP BY status, last_error''', (start, end)).fetchall()
    pending = parsed_queue = isolated = blocking = unexpected_queue = 0
    for r in qs:
        status, count = r['status'], r['n']
        if status == 'pending': pending += count
        elif status == 'parsed': parsed_queue += count
        elif status == 'error':
            if (r['last_error'] or '') in ISOLATED_ERRORS:
                isolated += count
            else:
                blocking += count
        else: unexpected_queue += count
    total_queued = pending + parsed_queue + isolated + blocking + unexpected_queue
    mismatched_days = con.execute('''
        SELECT COUNT(*) FROM (
          SELECT d.race_date
          FROM days AS d LEFT JOIN race_queue AS q ON q.race_date = d.race_date
          WHERE d.race_date BETWEEN ? AND ? AND d.index_state = 'indexed'
          GROUP BY d.race_date, d.discovered
          HAVING d.discovered = 0 OR d.discovered != COUNT(q.race_id)
        )
    ''', (start, end)).fetchone()[0]
    missing_parsed_races = con.execute('''
        SELECT COUNT(*) FROM race_queue AS q
        LEFT JOIN races AS r ON r.race_id = q.race_id
        WHERE q.race_date BETWEEN ? AND ? AND q.status='parsed'
          AND (r.race_id IS NULL OR r.race_date != q.race_date)
    ''', (start, end)).fetchone()[0]
    races_without_runners = con.execute('''
        SELECT COUNT(*) FROM races AS r
        WHERE r.race_date BETWEEN ? AND ?
          AND NOT EXISTS (SELECT 1 FROM runners AS rr WHERE rr.race_id = r.race_id)
    ''', (start, end)).fetchone()[0]
    saved_races = con.execute('SELECT count(*) FROM races WHERE race_date BETWEEN ? AND ?', (start, end)).fetchone()[0]
    saved_runners = con.execute('''SELECT count(*) FROM runners AS rr JOIN races AS r ON r.race_id = rr.race_id
        WHERE r.race_date BETWEEN ? AND ?''', (start, end)).fetchone()[0]
    qa_reviews = con.execute('''SELECT COUNT(*) FROM races WHERE race_date BETWEEN ? AND ?
        AND (json_extract(data, '$.qa_status') IN ('review', 'imported_unverified'))''',
        (start, end)).fetchone()[0]

    # Distinguish indexed/discovered from independently verified historical coverage.
    if (indexed_errors or blocking or mismatched_days or unexpected_day_state
            or unexpected_queue or missing_parsed_races or races_without_runners):
        status = 'blocked_review_required'
    elif indexed == w.days and pending == 0:
        status = 'indexed_with_qa_holds' if isolated else 'indexed_audit_required'
    elif indexed or saved_races or total_queued:
        status = 'in_progress'
    else:
        status = 'not_started'
    return {
        'start': start, 'end': end, 'status': status,
        'calendar_days': w.days, 'indexed_days': indexed,
        'unindexed_days': w.days - indexed - indexed_errors - unexpected_day_state,
        'index_errors': indexed_errors, 'discovered_on_indexed_days': discovered,
        'queue_total': total_queued, 'queue_parsed': parsed_queue,
        'pending_race_pages': pending, 'isolated_parse_holds': isolated,
        'blocking_race_errors': blocking, 'unrecognised_queue_statuses': unexpected_queue,
        'mismatched_index_days': mismatched_days,
        'missing_parsed_races': missing_parsed_races,
        'races_without_runners': races_without_runners,
        'saved_races': saved_races, 'saved_runners': saved_runners,
        'races_flagged_for_qa_review': qa_reviews,
        'verified_complete': False,
    }


def collect_stats(db: Path, all_windows: list[Window]) -> list[dict]:
    with closing(connection(db)) as con:
        return [window_stats(con, w) for w in all_windows]


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(content, encoding='utf-8')
    os.replace(temp, path)


def write_manifest(db: Path, logs: Path, all_windows: list[Window]) -> list[dict]:
    rows = collect_stats(db, all_windows)
    details = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'sportinglife',
        'database': str(db),
        'disclaimer': 'Indexed dates are NOT independently verified as complete. QA holds remain unresolved.',
        'windows': rows,
    }
    atomic_text(logs / 'window_status.json', json.dumps(details, indent=2, ensure_ascii=False))
    columns = list(rows[0]) if rows else []
    logs.mkdir(parents=True, exist_ok=True)
    tmp = logs / 'window_status.csv.tmp'
    with tmp.open('w', encoding='utf-8-sig', newline='') as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, logs / 'window_status.csv')
    return rows


def _runner_sort(item: dict):
    status = item.get('status')
    if status == 'finished':
        try: pos = int(float(item.get('position')))
        except (TypeError, ValueError): pos = 10**7
        return (0, pos, str(item.get('horse') or '').casefold())
    return (2 if status == 'non_runner' else 1, 0, str(item.get('horse') or '').casefold())


def _write_csv(path: Path, rows: list[dict], first_fields: tuple[str, ...]):
    fields = list(dict.fromkeys([*first_fields, *(k for row in rows for k in row)]))
    with path.open('w', encoding='utf-8-sig', newline='') as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


def export_window(db: Path, exports: Path, w: Window, stats: dict) -> Path:
    out = exports / 'windows' / w.key
    out.mkdir(parents=True, exist_ok=True)
    start, end = w.start.isoformat(), w.end.isoformat()
    with closing(connection(db)) as con:
        races = []
        for item in con.execute('SELECT race_id, race_date, data FROM races WHERE race_date BETWEEN ? AND ? ORDER BY race_date,race_id', (start, end)):
            race = json.loads(item['data'])
            race.setdefault('race_id', item['race_id'])
            race.setdefault('race_date', item['race_date'])
            races.append(race)
        runners = []
        for item in con.execute('''SELECT r.race_id, r.race_date, h.data
            FROM runners AS h JOIN races AS r ON r.race_id=h.race_id
            WHERE r.race_date BETWEEN ? AND ? ORDER BY r.race_date,r.race_id''', (start, end)):
            horse = json.loads(item['data'])
            horse.setdefault('race_id', item['race_id'])
            horse.setdefault('race_date', item['race_date'])
            runners.append(horse)
    runners.sort(key=lambda r: (r['race_date'], str(r['race_id']), _runner_sort(r)))
    _write_csv(out / 'races.csv', races, ('race_date', 'race_id', 'source'))
    _write_csv(out / 'runners.csv', runners,
               ('race_date', 'race_id', 'horse_id', 'horse', 'position', 'status', 'source'))
    atomic_text(out / 'coverage.json', json.dumps(stats, indent=2))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument('--mode', choices=('status', 'collect'), default='status')
    p.add_argument('--months', type=int, choices=(1, 3), default=1)
    p.add_argument('--start', default='2022-01-01', help='Inclusive earliest date')
    p.add_argument('--end', default='2026-10-31', help='Inclusive latest date')
    p.add_argument('--windows', type=int, default=1, help='Maximum windows to advance per invocation')
    p.add_argument('--batches', type=int, default=12, help='Collector batches per selected window')
    p.add_argument('--batch-races', type=int, default=20)
    p.add_argument('--delay', type=float, default=6.0)
    p.add_argument('--max-runtime-minutes', type=float, default=40.0)
    p.add_argument('--database', default='data/racing_history.sqlite')
    p.add_argument('--logs', default='data/backfill_logs')
    p.add_argument('--exports', default='data/exports')
    p.add_argument('--offline-dir', default=None, help='Import already held, authorised HTML instead of live source')
    p.add_argument('--no-export', action='store_true')
    args = p.parse_args(argv)
    try:
        begin, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
        all_windows = list(windows(begin, end, args.months))
    except ValueError as exc:
        p.error(str(exc))
    if args.windows < 1 or args.batches < 1 or not 1 <= args.batch_races <= 250 or args.delay < 3 or args.max_runtime_minutes < 0:
        p.error('Use positive windows/batches, 1..250 batch-races, at least 3s delay, and nonnegative runtime')
    db, logs, exports = (repo_path(args.database), repo_path(args.logs), repo_path(args.exports))
    if not db.is_file():
        print(f'STOP: Existing SQLite checkpoint not found: {db}', file=sys.stderr)
        return 4
    try:
        current = write_manifest(db, logs, all_windows)
    except sqlite3.Error as exc:
        print(f'STOP: Cannot inspect existing SQLite schema: {exc}', file=sys.stderr)
        return 4
    totals = {'indexed_audit_required': 0, 'indexed_with_qa_holds': 0,
              'blocked_review_required': 0, 'in_progress': 0, 'not_started': 0}
    for item in current: totals[item['status']] += 1
    print(f'Windows: {len(current)}  |  Month size: {args.months}  |  Status counts: {totals}')
    print(f'Manifest: {logs / "window_status.csv"}')
    next_window_index = next((i for i, r in enumerate(current) if r['status'] not in INDEXED_STATUSES), None)
    if next_window_index is None:
        print('All windows indexed or held for QA. Independent source/fixture verification remains required.')
        return 0
    print('Next:', json.dumps(current[next_window_index], indent=2))
    if args.mode == 'status':
        return 0
    if args.offline_dir is None and os.environ.get('SL_COLLECTION_ENABLED') != 'true':
        print('STOP: Live collection disabled. Obtain written Sporting Life permission before setting SL_COLLECTION_ENABLED=true.', file=sys.stderr)
        return 4
    controller = ROOT / 'src' / 'backfill_controller.py'
    if not controller.is_file():
        print(f'STOP: Existing collector is missing: {controller}', file=sys.stderr)
        return 4

    attempted = 0
    while attempted < args.windows:
        current = write_manifest(db, logs, all_windows)
        todo = next((i for i, r in enumerate(current) if r['status'] not in INDEXED_STATUSES), None)
        if todo is None:
            print('No more windows to collect; independent verification still needed.')
            return 0
        w, before = all_windows[todo], current[todo]
        if before['status'] == 'blocked_review_required':
            print(f'STOP: {w.key} has blocking errors or a discovered/queued mismatch; review the existing QA register.')
            return 5
        if before['status'] == 'in_progress' and before['pending_race_pages'] == 0 and before['unindexed_days'] == 0:
            print(f'STOP: {w.key} cannot progress without correcting its date/queue state.')
            return 5
        attempted += 1
        cmd = [sys.executable, str(controller), '--mode', 'full',
               '--start', w.start.isoformat(), '--end', w.end.isoformat(),
               '--date-order', 'oldest', '--batches', str(args.batches),
               '--batch-races', str(args.batch_races), '--delay', str(args.delay),
               '--max-runtime-minutes', str(args.max_runtime_minutes),
               '--database', str(db), '--logs', str(logs / 'windows' / w.key),
               '--exports', str(exports)]
        if args.offline_dir:
            cmd.extend(['--offline-dir', str(repo_path(args.offline_dir))])
        print(f'RUN {attempted}/{args.windows}: {w.start} through {w.end}; checkpoint reused.', flush=True)
        result = subprocess.run(cmd, cwd=ROOT, check=False)
        current = write_manifest(db, logs, all_windows)
        after = current[todo]
        if not args.no_export:
            output = export_window(db, exports, w, after)
            print(f'Window CSV + status exports: {output}')
        print('AFTER:', json.dumps(after, indent=2))
        if result.returncode != 0:
            print(f'STOP: Existing controller returned {result.returncode}; preserve this checkpoint and inspect QA logs.')
            return result.returncode
        if after['status'] not in INDEXED_STATUSES:
            print('Window PARTIAL: rerun the same command to resume it (no next window yet).')
            return 0
        if after['status'] == 'indexed_with_qa_holds':
            print('Window INDEXED WITH HOLDS: known incomplete races stay quarantined; not verified complete.')
        else:
            print('Window INDEXED: still requires independent fixture/source verification.')
    print('Run budget finished. Repeat the same command to continue the next incomplete window.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
