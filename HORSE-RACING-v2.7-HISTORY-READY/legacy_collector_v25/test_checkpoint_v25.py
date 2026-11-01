"""Regression: pre-existing imperfect races do not freeze a backfill.
Uses fictional HTML fixtures only; makes no website requests.
"""
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from sl_history import db_open, register_index
from backfill_controller import open_db, sync_qa, snapshot

BASE=Path(__file__).resolve().parent
DAY='2022-10-21'

def check():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        db=root/'race.sqlite'
        fixtures=BASE/'demo_pages'
        with db_open(db) as conn:
            # Two old records model the existing 944565 and 944574 warnings.
            for rid,flags in [('944565','not_confirmed_weighed_in|finish_order_gap_or_duplicate'),
                              ('944574','not_confirmed_weighed_in|unmatched_horse_99')]:
                data={'race_id':rid,'date':DAY,'track':'Example',
                    'qa_status':'review','qa_flags':flags,'standards_input_allowed':False}
                conn.execute('INSERT INTO races VALUES (?,?,?)',(rid,DAY,json.dumps(data)))
            conn.commit()
        with open_db(db) as conn:
            sync_qa(conn)
            assert snapshot(conn,DAY,DAY)['critical']==2
            assert sync_qa(conn)['new']==0, 'Cached races should not be parsed twice'
            # A corrected record should invalidate only its own cache entry.
            updated={'race_id':'944565','date':DAY,'track':'Example',
                     'qa_status':'parsed_not_verified','qa_flags':'course_configuration_unverified',
                     'standards_input_allowed':False}
            conn.execute('UPDATE races SET data=? WHERE race_id=?',(json.dumps(updated),'944565'))
            conn.commit()
            assert sync_qa(conn)['new']==1
            assert snapshot(conn,DAY,DAY)['critical']==1
            # Restore critical record to check warning-only start behaviour.
            updated['qa_status']='review';updated['qa_flags']='finish_order_gap_or_duplicate'
            conn.execute('UPDATE races SET data=? WHERE race_id=?',(json.dumps(updated),'944565'))
            conn.commit();sync_qa(conn)
            assert snapshot(conn,DAY,DAY)['critical']==2
        cmd=[sys.executable,str(BASE/'backfill_controller.py'),
             '--mode','full','--start',DAY,'--end',DAY,'--batches','3',
             '--batch-races','1','--delay','3','--offline-dir',str(fixtures),
             '--database',str(db),'--logs',str(root/'logs'),
             '--exports',str(root/'exports')]
        run=subprocess.run(cmd,text=True,capture_output=True,cwd=BASE)
        assert run.returncode==0, (run.stdout,run.stderr)
        assert 'QA QUARANTINE: 2 existing races' in run.stdout, run.stdout
        with open_db(db) as conn:
            s=snapshot(conn,DAY,DAY)
            assert s['parsed']==4,s
            assert s['pending']==0,s
            assert s['critical']>=2,s
        with (root/'logs'/'quarantined_races.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        assert {'944565','944574'} <= {x['race_id'] for x in rows},rows
        assert all(x['standards_input_allowed']=='0' for x in rows)
        assert (root/'logs'/'progress_v25.csv').exists()
        print('PASS: pre-existing bad races preserved in QA quarantine; collection resumed')
        print('PASS: incremental QA caching + invalidation, exports, full-day offline fixture')
        print('PASS: standards not approved, no data deleted, no network access')

if __name__=='__main__':check()
