#!/usr/bin/env python3
"""Non-destructive CSV export from current database, without restoring seed or resetting history."""
import sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sl_history import export_db
sys.path.insert(0,str(ROOT/'tools'))
from recover_archive import ensure_tables,audit,export
DB=ROOT/'data/racing_history.sqlite'
def main():
    if not DB.exists():raise SystemExit('Database missing: '+str(DB))
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    try:
        with con:
            ensure_tables(con);audit(con)
        details=export(con,ROOT/'data/exports',start='2022-01-01',end='2026-10-31')
        print('Races:',details['races'],'Runners:',details['runners'])
        print('Output: '+str(ROOT/'data/exports'))
    finally:con.close()
if __name__=='__main__':main()
