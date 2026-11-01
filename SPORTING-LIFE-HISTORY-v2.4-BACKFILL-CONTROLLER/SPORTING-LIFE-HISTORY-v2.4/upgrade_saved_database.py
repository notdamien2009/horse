#!/usr/bin/env python3
"""Safe one-time repair of comment boundaries in already saved SQLite rows.

Backs up existing SQLite database BEFORE modifying it. Does not contact any site,
change horse IDs, replace races or invent missing margins/times.
"""
from __future__ import annotations
import argparse,sqlite3,json
from pathlib import Path
from datetime import datetime,timezone
from contextlib import closing
from sl_structured_parser import fields_after_anchor
from sl_history import db_open,export_db


def upgrade(dbfile,outdir):
    if not dbfile.exists(): raise FileNotFoundError(f'Missing SQLite database: {dbfile}')
    backup=dbfile.with_name(dbfile.name+'.bak-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.sqlite')
    with closing(sqlite3.connect(dbfile)) as src,closing(sqlite3.connect(backup)) as dst:
        src.backup(dst)
    updated=[]; n=0
    with closing(db_open(dbfile)) as conn:
        # Reading row by row, only update fields with evidence in runner_text_raw.
        with conn:
            for row in conn.execute('SELECT race_id,horse_id,data FROM runners'):
                n+=1
                r=json.loads(row['data'])
                if r.get('status')=='non_runner' or not r.get('runner_text_raw'):continue
                info=fields_after_anchor(r['runner_text_raw'])
                old=r.get('comment') or '';new=info.get('comment') or ''
                jockey=info.get('jockey') or ''
                if new and jockey and len(new)>len(old) and (not old or old in new):
                    r['comment']=new
                    r['comment_raw']=info.get('comment_raw') or r.get('comment_raw')
                    r['jockey']=jockey
                    conn.execute('UPDATE runners SET data=? WHERE race_id=? AND horse_id=?',
                                 (json.dumps(r,ensure_ascii=False),row['race_id'],row['horse_id']))
                    updated.append(f"{row['race_id']}:{r.get('horse')}")
        result=export_db(conn,outdir)
    return {'backup':str(backup),'runner_records_scanned':n,
            'comment_boundaries_repaired':len(updated),
            'repaired_horses':updated[:50], 'export':result}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--database',type=Path,default=Path('data/racing_history.sqlite'))
    ap.add_argument('--output-dir',type=Path,default=Path('data/exports'))
    a=ap.parse_args()
    print(json.dumps(upgrade(a.database,a.output_dir),ensure_ascii=False,indent=2))
