"""Offline checks independent of any externally collected racing records."""
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checkpoint_module():
    path = ROOT / 'tools' / 'sl_checkpoint.py'
    spec = importlib.util.spec_from_file_location('sl_checkpoint', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_restore_roundtrip(tmp_path):
    source = tmp_path / 'source.sqlite'
    with sqlite3.connect(source) as conn:
        conn.execute('CREATE TABLE races (race_id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO races VALUES (?)', ('TEST001',))
    module = checkpoint_module()
    archive = tmp_path / 'backup.sqlite.gz'
    restored = tmp_path / 'restored.sqlite'
    module.save(source, archive)
    assert archive.stat().st_size > 0
    module.restore(archive, restored)
    assert module.verify(restored) == 1


def test_backup_rejects_decreasing_record_count(tmp_path):
    old = tmp_path / 'old.sqlite'
    new = tmp_path / 'new.sqlite'
    archive = tmp_path / 'new.sqlite.gz'
    for path, count in [(old, 2), (new, 1)]:
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE races (race_id TEXT PRIMARY KEY)')
            conn.executemany('INSERT INTO races VALUES (?)', [(str(n),) for n in range(count)])
    module = checkpoint_module()
    module.save(new, archive)
    try:
        module.restore(archive, old)
    except RuntimeError as exc:
        assert 'Refusing' in str(exc)
    else:
        raise AssertionError('Overwriting the larger database should have been blocked')
    assert module.verify(old) == 2


def test_collector_offline_self_test():
    result = subprocess.run([sys.executable, str(ROOT / 'src' / 'sl_history.py'), '--self-test'],
                            capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
