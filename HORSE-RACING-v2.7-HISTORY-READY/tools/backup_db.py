#!/usr/bin/env python3
"""Consistent SQLite backup; never change the user's live database."""
from pathlib import Path
from datetime import datetime,timezone
import sqlite3
ROOT=Path(__file__).resolve().parents[1];db=ROOT/'data/racing_history.sqlite'
if not db.is_file():raise SystemExit('ERROR: Cannot find '+str(db))
out=ROOT/'data/backups';out.mkdir(parents=True,exist_ok=True)
target=out/('racing_history_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sqlite')
with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as source, sqlite3.connect(target) as dest:
    source.backup(dest)
    if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Backup integrity failed')
print('BACKUP OK',target)
