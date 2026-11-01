#!/usr/bin/env python3
"""Resumable backfill controller with a separate, incremental QA quarantine.

Authorized-access collection only. Does not bypass access restrictions.
QA-review records are retained but NEVER designated verified for standards.
Stops for access/transport errors and systemic QA regressions, not for a
small number of existing quarantined races.
"""
from __future__ import annotations
import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
CRITICAL = {
    'invalid_or_missing_winning_time', 'invalid_distance', 'missing_going',
    'missing_surface', 'no_finishers_parsed', 'runner_count_mismatch',
    'finish_order_gap_or_duplicate', 'duplicate_horse_in_race',
    'not_confirmed_weighed_in', 'missing_running_comments',
    'non_runner_text_only_not_captured', 'non_runner_unclosed_record',
    'no_runner_rows_recognised',
}

def severity_flags(r):
    flags = set(filter(None, (r.get('qa_flags') or '').split('|')))
    critical = sorted(f for f in flags if f in CRITICAL or
                      f.startswith(('unmatched_horse_', 'duplicate_profile_anchor_')))
    return flags, critical


def open_db(db):
    db.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(db)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA busy_timeout=10000')
    # QA cache avoids re-reading every JSON race after every batch.
    # Triggers invalidate the cached QA when an existing race is reparsed.
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS backfill_qa_register(
          race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL,
          qa_status TEXT NOT NULL, all_flags TEXT NOT NULL,
          critical_flags TEXT NOT NULL, track TEXT, race_name TEXT,
          standards_input_allowed INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_bqa_date ON backfill_qa_register(race_date);
        CREATE TRIGGER IF NOT EXISTS bqa_update AFTER UPDATE ON races
        BEGIN DELETE FROM backfill_qa_register WHERE race_id=NEW.race_id; END;
        CREATE TRIGGER IF NOT EXISTS bqa_delete AFTER DELETE ON races
        BEGIN DELETE FROM backfill_qa_register WHERE race_id=OLD.race_id; END;
    ''')
    return conn


def sync_qa(conn):
    """Only assess newly added or invalidated races; returns their status."""
    new=[]
    for row in conn.execute('''SELECT races.race_id,races.race_date,races.data
        FROM races LEFT JOIN backfill_qa_register qa ON races.race_id=qa.race_id
        WHERE qa.race_id IS NULL''').fetchall():
        r=json.loads(row['data'])
        flags,crits=severity_flags(r)
        status=r.get('qa_status') or 'unknown'
        new.append((row['race_id'],row['race_date'],status,'|'.join(sorted(flags)),
                    '|'.join(crits),r.get('track'),r.get('race_name'),
                    # NEVER promote to standard input because of cache status.
                    1 if r.get('standards_input_allowed') is True else 0))
    if new:
        conn.executemany('''INSERT OR REPLACE INTO backfill_qa_register
            (race_id,race_date,qa_status,all_flags,critical_flags,track,race_name,
             standards_input_allowed) VALUES(?,?,?,?,?,?,?,?)''',new)
        conn.commit()
    return dict(new=len(new),critical=sum(bool(x[4]) for x in new),
                review=sum(x[2]=='review' for x in new),
                critical_ids=[x[0] for x in new if x[4]][:20])


def snapshot(conn,start,end):
    def count(query):return conn.execute(query,(start,end)).fetchone()[0]
    return {
      'parsed':count('SELECT count(*) FROM races WHERE race_date BETWEEN ? AND ?'),
      'indexed':count("SELECT count(*) FROM days WHERE race_date BETWEEN ? AND ? AND index_state='indexed'"),
      'index_errors':count("SELECT count(*) FROM days WHERE race_date BETWEEN ? AND ? AND index_state='error'"),
      'queue_errors':count("SELECT count(*) FROM race_queue WHERE race_date BETWEEN ? AND ? AND status='error'"),
      'pending':count("SELECT count(*) FROM race_queue WHERE race_date BETWEEN ? AND ? AND status='pending'"),
      'reviewed':count("SELECT count(*) FROM backfill_qa_register WHERE race_date BETWEEN ? AND ? AND qa_status='review'"),
      'critical':count("SELECT count(*) FROM backfill_qa_register WHERE race_date BETWEEN ? AND ? AND critical_flags != ''"),
    }


def quarantine(conn,output,start,end):
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f)
        w.writerow(['race_date','race_id','track','race_name','qa_status',
                    'critical_flags','all_flags','standards_input_allowed'])
        for r in conn.execute('''SELECT race_date,race_id,track,race_name,qa_status,
                    critical_flags,all_flags,standards_input_allowed
            FROM backfill_qa_register WHERE race_date BETWEEN ? AND ?
            AND (critical_flags != '' OR qa_status='review')
            ORDER BY race_date,race_id''',(start,end)):
            w.writerow(tuple(r))


def record(logpath,batch,state,action,new_critical=0):
    logpath.parent.mkdir(parents=True,exist_ok=True)
    with logpath.open('a',newline='',encoding='utf-8') as f:
        w=csv.writer(f)
        if f.tell()==0:
            w.writerow(['timestamp_utc','batch','action','races','dates_indexed',
              'pending','race_errors','date_errors','qa_review','critical','new_critical'])
        w.writerow([datetime.now(timezone.utc).isoformat(timespec='seconds'),batch,action,
           state['parsed'],state['indexed'],state['pending'],state['queue_errors'],
           state['index_errors'],state['reviewed'],state['critical'],new_critical])


def run(args):
    db=(BASE/args.database).resolve()
    if not db.exists():
        print('STOP: Database not found. Check the data folder and run a pilot first.')
        return 4
    logs=(BASE/args.logs).resolve(); logs.mkdir(parents=True,exist_ok=True)
    progress=logs/'progress_v25.csv'
    qa_file=logs/'quarantined_races.csv'
    total_days=(date.fromisoformat(args.end)-date.fromisoformat(args.start)).days+1
    with closing(open_db(db)) as conn:
        initial_sync=sync_qa(conn)
        before=snapshot(conn,args.start,args.end)
        quarantine(conn,qa_file,args.start,args.end)
    print(f'Date coverage: {args.start} to {args.end} (inclusive)')
    print(f'Existing archive: {before["parsed"]} races, {before["indexed"]} indexed dates, {before["pending"]} pending.')
    if before['critical']:
        print(f'QA QUARANTINE: {before["critical"]} existing races have critical flags; preserved, not approved for standards.')
        print(f'Review: {qa_file}')
    if before['queue_errors'] or before['index_errors']:
        print('STOP: existing collection errors require investigation (not automatically retried).')
        record(progress,0,before,'existing_collection_error')
        return 4
    if args.mode=='check':
        record(progress,0,before,'check');return 0
    if before['indexed']==total_days and before['pending']==0:
        print('Dates indexed and queue cleared; independently validate fixture coverage.')
        return 0
    for batch in range(1,args.batches+1):
        cmd=[sys.executable,str(BASE/'sl_history.py')]
        cmd += ['--html-dir',str((BASE/args.offline_dir).resolve())] if args.offline_dir else ['--live']
        cmd += ['--from-date',args.start,'--to-date',args.end,
                '--max-days','1','--max-races',str(args.batch_races),
                '--delay',str(args.delay),'--database',str(db),
                '--auto-export-limit','0','--output-dir',str((BASE/args.exports).resolve())]
        print(f'Batch {batch}/{args.batches}: up to {args.batch_races} race pages.',flush=True)
        with (logs/'run.log').open('a',encoding='utf-8') as logfile:
            logfile.write('\n== '+datetime.now(timezone.utc).isoformat()+' batch '+str(batch)+' ==\n')
            proc=subprocess.Popen(cmd,cwd=BASE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                        encoding='utf-8',errors='replace',bufsize=1)
            try:
                for line in proc.stdout:
                    print(line,end='',flush=True); logfile.write(line)
                exitcode=proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                print('Interrupted; completed records remain saved.')
                with closing(open_db(db)) as conn:
                    sync_qa(conn);after=snapshot(conn,args.start,args.end)
                    quarantine(conn,qa_file,args.start,args.end)
                record(progress,batch,after,'interrupted');return 130
        with closing(open_db(db)) as conn:
            new=sync_qa(conn)
            after=snapshot(conn,args.start,args.end)
            quarantine(conn,qa_file,args.start,args.end)
        new_count=max(0,after['parsed']-before['parsed'])
        new_critical=new['critical']
        record(progress,batch,after,'batch' if exitcode==0 else 'failure',new_critical)
        print(f'CHECKPOINT: {after["parsed"]} races, {after["indexed"]} indexed dates, '
              f'{after["pending"]} pending, {after["critical"]} quarantined critical flags '
              f'({new_critical} new).')
        if exitcode or (after['queue_errors']+after['index_errors'] >
                         before['queue_errors']+before['index_errors']):
            print('STOP: transport/collection error. Inspect run.log; no access-control workarounds.')
            return 2
        if args.mode=='pilot' and new['review']:
            print('STOP: pilot has new QA-review races; inspect quarantine before continuing.')
            return 6
        if new_critical>=args.max_critical_per_batch or (
            new_count>=args.min_qa_sample and new_critical/new_count>=args.max_critical_fraction):
            print(f'STOP: systemic QA threshold reached ({new_critical}/{new_count} new races).')
            print(f'Inspect {qa_file}; no questionable race is approved for standards.')
            return 5
        if new_critical:
            print(f'QA: {new_critical} new race(s) quarantined for review: {new["critical_ids"]}')
        if after['indexed']==total_days and after['pending']==0:
            print('All days indexed, no pending races. Verify fixture coverage separately.')
            return 0
        # Some dates legitimately have fewer pages than the configured batch size.
        made_progress = after['parsed']>before['parsed'] or after['indexed']>before['indexed']
        if not made_progress:
            print('STOP: no progress. Inspect index and queue; not claiming completeness.')
            return 3
        before=after
    print('Batch budget reached. Restart this launcher to resume remaining dates.')
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('pilot','full','check'),default='pilot')
    p.add_argument('--start',default='2022-01-01')
    p.add_argument('--end',default='2026-10-21')
    p.add_argument('--batches',type=int,default=3)
    p.add_argument('--batch-races',type=int,default=20)
    p.add_argument('--delay',type=float,default=6.0)
    p.add_argument('--offline-dir',default=None)
    p.add_argument('--database',default='data/racing_history.sqlite')
    p.add_argument('--logs',default='data/backfill_logs')
    p.add_argument('--exports',default='data/exports')
    p.add_argument('--max-critical-per-batch',type=int,default=5)
    p.add_argument('--max-critical-fraction',type=float,default=0.30)
    p.add_argument('--min-qa-sample',type=int,default=10)
    a=p.parse_args()
    if date.fromisoformat(a.start)>date.fromisoformat(a.end):p.error('start after end')
    if a.batches<1 or not 1<=a.batch_races<=250 or a.delay<3:p.error('Invalid batch or delay')
    if a.max_critical_per_batch<1 or not 0<a.max_critical_fraction<=1 or a.min_qa_sample<1:
        p.error('Invalid quality thresholds')
    return run(a)

if __name__=='__main__':raise SystemExit(main())
