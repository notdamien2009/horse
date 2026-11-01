#!/usr/bin/env python3
"""Conservative, provenance-labelled repair of empty All-Weather surface fields.

This never marks a race verified. Use --apply for transactional SQLite updates;
by default the tool only reports the number of eligible records.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sl_history import infer_surface_from_going

def update_record(record):
    race = dict(record)
    if race.get('surface'):
        return None
    inferred = infer_surface_from_going(race.get('going'), race.get('race_type'))
    if not inferred:
        return None
    race['surface'] = inferred
    flags = [f for f in str(race.get('qa_flags') or '').split('|')
             if f and f != 'missing_surface']
    if 'surface_inferred_from_going' not in flags:
        flags.append('surface_inferred_from_going')
    race['qa_flags'] = '|'.join(flags)
    race['standards_input_allowed'] = False
    # Keep the original review status; an inference cannot mean approval.
    return race

def repair(db_path, apply=False):
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(db_path) as con:
        proposed = []
        for race_id, raw in con.execute('SELECT race_id,data FROM races'):
            replacement = update_record(json.loads(raw))
            if replacement is not None:
                proposed.append((json.dumps(replacement, ensure_ascii=False), race_id))
        if apply and proposed:
            backup_path = db_path.with_name(db_path.stem + '.before_surface_repair.sqlite')
            if not backup_path.exists():
                with sqlite3.connect(backup_path) as backup:
                    con.backup(backup)
            with con:
                con.executemany('UPDATE races SET data=? WHERE race_id=?', proposed)
        return len(proposed)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', default=str(ROOT/'data/racing_history.sqlite'))
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    count = repair(args.database, args.apply)
    print(f'Surface inference: {count} eligible races; applied={args.apply}. No standards approvals.')

if __name__ == '__main__':
    main()
