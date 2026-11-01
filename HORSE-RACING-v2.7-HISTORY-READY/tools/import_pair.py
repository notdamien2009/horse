#!/usr/bin/env python3
"""Import a race/runner CSV pair into the canonical local SQLite database.
Inputs must use the matching fields of this project. No website access.
"""
import argparse, sqlite3, json
from pathlib import Path
from recover_archive import ensure_tables, import_csv, audit, export, ROOT

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--races',type=Path,required=True)
    ap.add_argument('--runners',type=Path,required=True)
    ap.add_argument('--database',type=Path,default=ROOT/'data/racing_history.sqlite')
    ap.add_argument('--exports',type=Path,default=ROOT/'data/exports')
    a=ap.parse_args()
    for p in (a.races,a.runners,a.database):
        if not p.is_file():ap.error('File missing: '+str(p))
    db=sqlite3.connect(a.database)
    try:
        with db:
            ensure_tables(db)
            report={'races':import_csv(db,'races',a.races),'runners':import_csv(db,'runners',a.runners),'qa':audit(db)}
        report['summary']=export(db,a.exports)
        print(json.dumps(report,indent=2))
    finally:db.close()
if __name__=='__main__':main()
