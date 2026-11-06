#!/usr/bin/env python3
"""Local, restartable controller for the EXISTING Sporting Life project.

Place this file in the checkout's root beside src/, tools/, and data/.
No site requests are made in --verify/--status/--stop modes.
Live collection requires an explicit, locally configured access authorisation.
This program does not bypass source restrictions, rotate IPs, or evade blocks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOG_DIR = DATA / 'local_runner'
CONFIG = ROOT / 'local_collector_config.json'
DATABASE = DATA / 'racing_history.sqlite'
STOP_FILE = LOG_DIR / 'STOP_REQUESTED'
LOCK_FILE = LOG_DIR / 'runner.lock'
STATUS_FILE = LOG_DIR / 'status.json'
LOG_FILE = LOG_DIR / 'background.log'
BACKUPS = LOG_DIR / 'backups'
DEFAULT = {
    'source_access_authorised': False,
    'start_date': '2022-01-01',
    'end_date': '2026-10-31',
    'date_order': 'oldest',
    'batch_races': 20,
    'request_delay_seconds': 6,
    'rest_between_batches_seconds': 15,
    'backup_interval_minutes': 30,
    'keep_backups': 8,
}


def setup_logger():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('local_history_runner')
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=4,
                                  encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    return logger


def load_config():
    if not CONFIG.is_file():
        raise RuntimeError(f'Missing {CONFIG.name}. Copy the files from the ZIP to the repository root.')
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    invalid = set(data) - set(DEFAULT)
    if invalid:
        raise ValueError('Unknown configuration settings: ' + ', '.join(sorted(invalid)))
    options = DEFAULT | data
    if type(options['source_access_authorised']) is not bool:
        raise ValueError('source_access_authorised must be true or false')
    if options['date_order'] not in ('newest', 'oldest'):
        raise ValueError('Invalid date_order')
    start = dt.date.fromisoformat(options['start_date'])
    end = dt.date.fromisoformat(options['end_date'])
    if start > end:
        raise ValueError('start_date must not exceed end_date')
    if not (1 <= options['batch_races'] <= 50):
        raise ValueError('batch_races must be between 1 and 50')
    if float(options['request_delay_seconds']) < 6:
        raise ValueError('Delay must be at least 6 seconds; no aggressive requests')
    if not (0 <= float(options['rest_between_batches_seconds']) <= 86400):
        raise ValueError('rest_between_batches_seconds out of range')
    if not (5 <= float(options['backup_interval_minutes']) <= 1440):
        raise ValueError('backup_interval_minutes out of range')
    if not (1 <= int(options['keep_backups']) <= 20):
        raise ValueError('keep_backups out of range')
    return options


def validate_project():
    required = [ROOT / 'src' / 'backfill_controller.py',
                ROOT / 'src' / 'sl_history.py',
                ROOT / 'tools' / 'sl_checkpoint.py',
                DATABASE]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError('Missing project components: ' + ', '.join(missing) + '. '
                           'Use the latest private GitHub project and restore its SQLite checkpoint first.')
    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)) as conn:
        check = conn.execute('PRAGMA integrity_check').fetchone()[0]
        if check != 'ok':
            raise RuntimeError('SQLite integrity check failed: ' + check)
        for name in ('races', 'runners', 'race_queue', 'days'):
            conn.execute('SELECT count(*) FROM ' + name).fetchone()


def counts():
    if not DATABASE.is_file():
        return {'database_found': False}
    try:
        with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True)) as c:
            result = {
                'database_found': True,
                'races': c.execute('SELECT count(*) FROM races').fetchone()[0],
                'runners': c.execute('SELECT count(*) FROM runners').fetchone()[0],
                'dates_indexed': c.execute("SELECT count(*) FROM days WHERE index_state='indexed'").fetchone()[0],
            }
            result['pending'] = c.execute("SELECT count(*) FROM race_queue WHERE status='pending'").fetchone()[0]
            result['failed_pages'] = c.execute("SELECT count(*) FROM race_queue WHERE status='error'").fetchone()[0]
            return result
    except (sqlite3.Error, OSError) as err:
        return {'database_found': True, 'status_error': str(err)}


def write_status(phase: str, **extra):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    obj = {'updated_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
           'phase': phase, 'pid': os.getpid(), **counts(), **extra}
    tmp = STATUS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=2), encoding='utf-8')
    os.replace(tmp, STATUS_FILE)
    return obj


def lock_instance():
    """Windows/Linux kernel lock; automatically released if process exits."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    f = LOCK_FILE.open('a+b')
    f.seek(0, os.SEEK_END)
    if f.tell() == 0:
        f.write(b'0')
        f.flush()
    f.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as err:
        f.close()
        raise RuntimeError('Collector already running. Check status or request STOP.') from err
    return f


def is_worker_running():
    """Probe the kernel lock; a stale status file does not mean active work."""
    if not LOCK_FILE.is_file():
        return False
    f = LOCK_FILE.open('a+b')
    try:
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            else:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                return False
        import fcntl
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return False
    finally:
        f.close()


def backup(logger):
    """Consistent SQLite snapshot, compressed; never copy a live .sqlite file."""
    from gzip import open as gzip_open
    import shutil
    import tempfile
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    archive = BACKUPS / f'racing_history_{stamp}.sqlite.gz'
    with tempfile.TemporaryDirectory(dir=str(BACKUPS)) as tmp:
        snap = Path(tmp) / 'snapshot.sqlite'
        with closing(sqlite3.connect(str(DATABASE))) as src, closing(sqlite3.connect(str(snap))) as dst:
            src.backup(dst)
        with closing(sqlite3.connect(str(snap))) as c:
            ok = c.execute('PRAGMA integrity_check').fetchone()[0]
            if ok != 'ok':
                raise RuntimeError('Backup failed SQLite integrity check: ' + ok)
        partial = Path(tmp) / 'pending.gz'
        with snap.open('rb') as inp, gzip_open(partial, 'wb', compresslevel=6) as out:
            shutil.copyfileobj(inp, out)
        os.replace(partial, archive)
    logger.info('SQLite backup saved: %s', archive)
    return archive


def keep_latest(n):
    archives = sorted(BACKUPS.glob('racing_history_*.sqlite.gz'), reverse=True)
    for path in archives[n:]:
        path.unlink(missing_ok=True)


def run_batch(options, logger):
    cmd = [sys.executable, str(ROOT / 'src' / 'backfill_controller.py'),
           '--mode', 'full', '--start', options['start_date'],
           '--end', options['end_date'], '--date-order', options['date_order'],
           '--batches', '1', '--batch-races', str(options['batch_races']),
           '--delay', str(options['request_delay_seconds']),
           '--database', str(DATABASE),
           '--logs', str(DATA / 'backfill_logs'),
           '--exports', str(DATA / 'exports')]
    logger.info('Starting one bounded batch (%d pages max)', options['batch_races'])
    with subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, bufsize=1, encoding='utf-8',
                          errors='replace') as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            logger.info('COLLECTOR %s', line.rstrip())
        returncode = proc.wait()
    logger.info('Batch finished with exit code %d', returncode)
    return returncode


def run_local(once):
    logger = setup_logger()
    lock = lock_instance()
    try:
        options = load_config()
        if not options['source_access_authorised']:
            raise RuntimeError('Live collection disabled. Confirm authorised source access in '
                               'local_collector_config.json before starting.')
        validate_project()
        STOP_FILE.unlink(missing_ok=True)
        logger.info('Local collector started; root=%s; PID=%d', ROOT, os.getpid())
        initial = counts()
        if initial.get('races', 0) == 0:
            raise RuntimeError('Refusing to start with empty archive; restore the latest saved checkpoint')
        last_backup = time.monotonic()
        backup(logger)
        keep_latest(int(options['keep_backups']))
        batches = 0
        while True:
            if STOP_FILE.is_file():
                logger.info('Stop request detected; ending between batches')
                write_status('stopped_by_user', batches=batches)
                break
            before = counts()
            write_status('collecting', batches=batches)
            try:
                code = run_batch(options, logger)
            except Exception:
                logger.exception('Unexpected local launcher failure. Stopping.')
                write_status('launcher_error', batches=batches)
                raise
            batches += 1
            after = counts()
            changes = after.get('races', 0) - before.get('races', 0)
            logger.info('Database now %s; newly saved races in batch=%d', after, changes)
            if code != 0:
                write_status('stopped_on_collector_error', exit_code=code, batches=batches)
                backup(logger)
                keep_latest(int(options['keep_backups']))
                logger.error('Collector stopped on QA/access/transport error. Inspect background.log and failed_race_pages.csv.')
                break
            if time.monotonic() - last_backup >= 60 * float(options['backup_interval_minutes']):
                backup(logger)
                keep_latest(int(options['keep_backups']))
                last_backup = time.monotonic()
            made_progress = (changes > 0 or
                             after.get('dates_indexed', 0) > before.get('dates_indexed', 0) or
                             after.get('pending', 0) != before.get('pending', 0) or
                             after.get('failed_pages', 0) > before.get('failed_pages', 0))
            if not made_progress:
                # No new races, date indexes, queue changes or quarantined pages.
                logger.warning('Batch made no recorded progress; pausing for review rather than looping.')
                write_status('stopped_no_progress', batches=batches)
                break
            write_status('waiting_between_batches', batches=batches)
            if once:
                logger.info('Single batch requested; exiting normally')
                write_status('single_batch_complete', batches=batches)
                break
            remaining = float(options['rest_between_batches_seconds'])
            while remaining > 0 and not STOP_FILE.exists():
                sleep_for = min(2, remaining)
                time.sleep(sleep_for)
                remaining -= sleep_for
        logger.info('Local launcher finished')
    finally:
        lock.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--status', action='store_true')
    mode.add_argument('--stop', action='store_true')
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--loop', action='store_true')
    args = p.parse_args()
    if args.verify:
        validate_project()
        print('PROJECT OK:', ROOT)
        print('DATABASE:', json.dumps(counts(), indent=2))
        print('No website requests made.')
    elif args.status:
        print('Background worker active:', 'YES' if is_worker_running() else 'NO')
        print(json.dumps(counts(), indent=2))
        if STATUS_FILE.is_file():
            print(STATUS_FILE.read_text(encoding='utf-8'))
        else:
            print('No previous local launcher status.')
    elif args.stop:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        STOP_FILE.write_text('Stop safely after active batch', encoding='utf-8')
        print('Stop requested. Current batch can finish before exit.')
    else:
        try:
            run_local(args.once)
        except Exception as err:
            logger = setup_logger()
            logger.exception('Failed to launch local collector')
            write_status('error', error=str(err))
            print('COLLECTOR ERROR:', err)
            raise SystemExit(1)


if __name__ == '__main__':
    main()
