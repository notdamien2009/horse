#!/usr/bin/env python3
"""Safely requeue exactly one previously timed-out Sporting Life race.

Offline database maintenance only: no network access and no access-control bypass.
Requires an explicit --apply; otherwise previews the record. Makes a consistent
SQLite backup, preserves the original error in an audit table, and retains the
original queue attempt count. Run only while the collector is stopped.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, date
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]


def recovery(db: Path, race_id: str, day: str, apply: bool) -> int:
    if not db.is_file():
        print(f'STOP: Database not found: {db}', file=sys.stderr)
        return 2
    print(f'Using database: {db.resolve()}', flush=True)
    try:
        with sqlite3.connect(db, timeout=10) as con:
            con.row_factory = sqlite3.Row
            con.execute('PRAGMA busy_timeout=10000')
            row = con.execute(
                'SELECT race_id, race_date, track, status, attempts, last_error '
                'FROM race_queue WHERE race_id=?', (race_id,)
            ).fetchone()
            if row is None:
                print(f'STOP: Race {race_id} not found in this database. Nothing changed.')
                print('Checking recorded failures on the same date:')
                matches = con.execute(
                    "SELECT race_id, race_date, track, status, last_error "
                    "FROM race_queue WHERE race_id LIKE ? "
                    "OR (race_date=? AND status='error') "
                    "ORDER BY race_date, race_id LIMIT 15",
                    (f'%{race_id}%', day)).fetchall()
                if matches:
                    for match in matches:
                        print(f"  {match['race_id']!r} | {match['race_date']} | "
                              f"{match['track']} | {match['status']} | {match['last_error']}")
                else:
                    print('  No matching race IDs or failed race pages found.')
                print('Database totals:')
                print('  queue:', con.execute('SELECT COUNT(*) FROM race_queue').fetchone()[0],
                      'races:', con.execute('SELECT COUNT(*) FROM races').fetchone()[0])
                # Diagnostic only. Never silently repair a different database.
                print('Checking for another local SQLite copy containing this race:')
                candidates = sorted({*db.parent.glob('*.sqlite'),
                                     *db.parent.glob('backups/*.sqlite')})
                found = False
                for candidate in candidates[:100]:
                    if candidate.resolve() == db.resolve():
                        continue
                    try:
                        with sqlite3.connect(f'{candidate.resolve().as_uri()}?mode=ro', uri=True) as other:
                            hit = other.execute(
                                'SELECT race_date,status,last_error FROM race_queue WHERE race_id=?',
                                (race_id,)).fetchone()
                        if hit:
                            print(f'  OTHER COPY: {candidate.resolve()} | date={hit[0]} | status={hit[1]}')
                            found = True
                    except sqlite3.Error:
                        continue
                if not found:
                    print('  No other matching SQLite copy in the data directory.')
                print('Use the displayed database path and matching race status to identify the correct next step.')
                return 3
            print(f"Race {row['race_id']} | {row['race_date']} | {row['track']} "
                  f"| status={row['status']} | attempts={row['attempts']}")
            print(f"Last error: {row['last_error']}")
            err = row['last_error'] or ''
            if row['status'] == 'parsed':
                print('NO REPAIR NEEDED: This race is already marked parsed in this database.')
                return 0
            if row['race_date'] != day or row['status'] != 'error' or not (
                err.startswith('ACCESS_OR_TRANSPORT_ERROR:') and
                'read timed out' in err.casefold()
            ):
                print('STOP: Not the specified unresolved read-timeout. Nothing changed.', file=sys.stderr)
                return 4
            if not apply:
                print('DRY RUN: Matching transient read timeout; use --apply to back up and requeue.')
                return 0
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            backups = db.parent / 'backups'
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / f'{db.stem}.before_retry_{race_id}_{stamp}.sqlite'
            if backup.exists():
                print(f'STOP: Backup path already exists: {backup}', file=sys.stderr)
                return 5
            # SQLite backup API gives a consistent copy including committed WAL changes.
            with sqlite3.connect(backup) as dest:
                con.backup(dest)
                check = dest.execute('PRAGMA integrity_check').fetchone()[0]
                if check != 'ok':
                    print(f'STOP: Backup integrity check failed: {check}', file=sys.stderr)
                    return 6
            print(f'Verified backup: {backup}')
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            with con:
                con.execute('''CREATE TABLE IF NOT EXISTS timeout_requeue_audit (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   at_utc TEXT NOT NULL,
                   race_id TEXT NOT NULL,
                   race_date TEXT NOT NULL,
                   track TEXT,
                   previous_status TEXT NOT NULL,
                   previous_attempts INTEGER NOT NULL,
                   previous_error TEXT NOT NULL,
                   action TEXT NOT NULL
                )''')
                con.execute('''INSERT INTO timeout_requeue_audit
                    (at_utc, race_id, race_date, track, previous_status,
                     previous_attempts, previous_error, action)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (now, race_id, day, row['track'], row['status'],
                     row['attempts'], err, 'manually_requeued_one_read_timeout'))
                result = con.execute('''UPDATE race_queue SET status='pending', updated_utc=?
                    WHERE race_id=? AND race_date=? AND status='error' AND last_error=?''',
                    (now, race_id, day, err))
                if result.rowcount != 1:
                    raise RuntimeError('Queue record changed during repair; rolled back.')
            print('OK: One race requeued as pending. Its original error is preserved in the audit table.')
            print('Attempts and all collected race and runner records remain unchanged.')
            return 0
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        print(f'STOP: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 7


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--race-id', required=True, help='Exactly one race ID, e.g. 677244')
    p.add_argument('--date', required=True, help='Exact date YYYY-MM-DD')
    p.add_argument('--database', default='data/racing_history.sqlite')
    p.add_argument('--apply', action='store_true', help='Backup, audit and requeue one matching timeout')
    a = p.parse_args()
    if not a.race_id.isdigit():
        p.error('race-id must be numeric')
    try:
        date.fromisoformat(a.date)
    except ValueError:
        p.error('date must be YYYY-MM-DD')
    path = Path(a.database)
    if not path.is_absolute():
        path = ROOT / path
    return recovery(path.resolve(), a.race_id, a.date, a.apply)


if __name__ == '__main__':
    raise SystemExit(main())
