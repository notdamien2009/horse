#!/usr/bin/env python3
"""Bounded, resumable controller for the existing historical collector.

Does not circumvent HTTP denials/challenges, authentication or rate limits.
Stops on transport errors, unsuccessful requests, data-quality regressions,
non-progress and user cancellation. For use only with authorised data access.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CRITICAL_FLAGS = {
    'invalid_or_missing_winning_time','invalid_distance','missing_going','missing_surface',
    'no_finishers_parsed','runner_count_mismatch','finish_order_gap_or_duplicate',
    'duplicate_horse_in_race','not_confirmed_weighed_in','missing_running_comments',
    'non_runner_text_only_not_captured','non_runner_unclosed_record','no_runner_rows_recognised',
}


def snapshot(db: Path, start: str, end: str) -> dict:
    if not db.exists():
        return dict(parsed=0, indexed=0, queue_errors=0, index_errors=0, pending=0,
                    reviewed=0, critical=0, reviewed_ids=[], critical_ids=[])
    with sqlite3.connect(db) as conn:
        parsed = conn.execute('SELECT count(*) FROM races WHERE race_date BETWEEN ? AND ?', (start,end)).fetchone()[0]
        indexed = conn.execute("SELECT count(*) FROM days WHERE race_date BETWEEN ? AND ? AND index_state='indexed'", (start,end)).fetchone()[0]
        index_errors = conn.execute("SELECT count(*) FROM days WHERE race_date BETWEEN ? AND ? AND index_state='error'", (start,end)).fetchone()[0]
        queue_errors = conn.execute("SELECT count(*) FROM race_queue WHERE race_date BETWEEN ? AND ? AND status='error'", (start,end)).fetchone()[0]
        pending = conn.execute("SELECT count(*) FROM race_queue WHERE race_date BETWEEN ? AND ? AND status='pending'", (start,end)).fetchone()[0]
        reviewed=critical=0; reviewed_ids=[]; critical_ids=[]
        for (rid, data) in conn.execute('SELECT race_id,data FROM races WHERE race_date BETWEEN ? AND ?',(start,end)):
            r=json.loads(data)
            if r.get('qa_status') == 'review':
                reviewed += 1
                if len(reviewed_ids) < 10: reviewed_ids.append(rid)
            flags=set(filter(None,(r.get('qa_flags') or '').split('|')))
            if flags & CRITICAL_FLAGS or any(x.startswith(('unmatched_horse_','duplicate_profile_anchor_')) for x in flags):
                critical += 1
                if len(critical_ids)<10: critical_ids.append(rid)
    return dict(parsed=parsed,indexed=indexed,index_errors=index_errors,
                queue_errors=queue_errors,pending=pending,
                reviewed=reviewed,critical=critical, reviewed_ids=reviewed_ids,
                critical_ids=critical_ids)


def emit_status(logpath:Path, batch:int, state:dict, action:str):
    logpath.parent.mkdir(parents=True,exist_ok=True)
    with logpath.open('a',newline='',encoding='utf-8') as f:
        writer=csv.writer(f)
        if f.tell()==0:
            writer.writerow(['timestamp_utc','batch','action','races','dates_indexed','pending','race_errors','date_errors','qa_review','critical'])
        writer.writerow([datetime.now(timezone.utc).isoformat(timespec='seconds'),batch,action,
                         state['parsed'],state['indexed'],state['pending'],
                         state['queue_errors'],state['index_errors'],state['reviewed'],state['critical']])


def run(args):
    db=(BASE_DIR/args.database).resolve()
    logdir=(BASE_DIR/args.logs).resolve()
    logdir.mkdir(parents=True,exist_ok=True)
    status_file=logdir/'progress.csv'
    before=snapshot(db,args.start,args.end)
    initial_critical=before['critical']
    initial_errors=before['queue_errors']+before['index_errors']
    print(f'Date coverage: {args.start} to {args.end} (inclusive)')
    print(f'Existing archive: {before["parsed"]} races, {before["indexed"]} indexed dates, {before["pending"]} pending')
    if initial_errors:
        print(f'STOP: {initial_errors} existing collection errors need review; no automatic reattempts.')
        emit_status(status_file,0,before,'existing_errors')
        return 4
    if initial_critical:
        print(f'STOP: {initial_critical} existing races have critical QA flags. Sample: {before["critical_ids"]}.')
        emit_status(status_file,0,before,'existing_qa_failure')
        return 5
    if args.mode == 'check':
        emit_status(status_file,0,before,'check')
        return 0
    total_days = (date.fromisoformat(args.end)-date.fromisoformat(args.start)).days+1
    if before['indexed']==total_days and before['pending']==0:
        print('All dates indexed with no pending race pages in the selected range. Validate source coverage before declaring the archive complete.')
        return 0
    for batch in range(1,args.batches+1):
        command=[sys.executable,str(BASE_DIR/'sl_history.py'),
                 *(['--html-dir',str((BASE_DIR/args.offline_dir).resolve())] if args.offline_dir else ['--live']),
                 '--from-date',args.start,'--to-date',args.end,
                 '--max-days','1','--max-races',str(args.batch_races),
                 '--delay',str(args.delay),'--database',str(db),
                 '--auto-export-limit','0',
                 '--output-dir',str((BASE_DIR/args.exports).resolve())]
        print(f'\nBatch {batch}/{args.batches}: running up to {args.batch_races} race pages (one day at a time).',flush=True)
        with (logdir/'run.log').open('a',encoding='utf-8') as logfile:
            logfile.write('\n== '+datetime.now(timezone.utc).isoformat()+' batch '+str(batch)+' ==\n')
            logfile.flush()
            # Tee: print normal output and preserve it for troubleshooting.
            proc=subprocess.Popen(command,cwd=BASE_DIR,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                  encoding='utf-8',errors='replace',bufsize=1)
            try:
                for line in proc.stdout:
                    print(line,end='',flush=True)
                    logfile.write(line)
                result=proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
                print('\nStopped by user. Completed batches remain saved.')
                emit_status(status_file,batch,snapshot(db,args.start,args.end),'interrupted')
                return 130
        after=snapshot(db,args.start,args.end)
        error_delta=(after['queue_errors']+after['index_errors'])-(before['queue_errors']+before['index_errors'])
        critical_delta=after['critical']-before['critical']
        reviewed_delta=after['reviewed']-before['reviewed']
        progress=after['parsed']>before['parsed'] or after['indexed']>before['indexed']
        emit_status(status_file,batch,after,'completed' if result==0 else 'failure')
        print(f'CHECKPOINT: {after["parsed"]} races; {after["indexed"]} indexed dates; '
              f'{after["pending"]} queued; {after["reviewed"]} QA review; {after["critical"]} critical.')
        if result != 0 or error_delta > 0:
            print('STOP: collection error or access restriction. See logs/run.log and progress.csv.')
            return 2
        if critical_delta > 0:
            print('STOP: critical accuracy flags found in new races: '+str(after['critical_ids']))
            print('Fix and reparse the relevant pages before continuing.')
            return 5
        if args.mode == 'pilot' and reviewed_delta > 0:
            print('STOP: Pilot contains QA-review races. Inspect before full collection.')
            return 6
        if after['indexed']==total_days and after['pending']==0:
            print('All dates indexed, with no pending pages. Compare the source fixture calendar before certifying completeness.')
            return 0
        if not progress:
            if after['pending'] == 0:
                print('No additional dates discovered. Inspect progress and coverage before claiming completion.')
            else:
                print('STOP: no progress although pending races remain.')
            return 3
        before=after
    print('\nBatch budget reached. Restart this launcher to resume; existing race IDs are not reinserted.')
    return 0


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('pilot','full','check'),default='pilot')
    p.add_argument('--start',default='2022-01-01')
    p.add_argument('--end',default='2026-10-21')
    p.add_argument('--batches',type=int,default=3)
    p.add_argument('--batch-races',type=int,default=20)
    p.add_argument('--delay',type=float,default=6.0)
    p.add_argument('--offline-dir',default=None,help='For local fixtures instead of live HTTP (test only)')
    p.add_argument('--database',default='data/racing_history.sqlite')
    p.add_argument('--logs',default='data/backfill_logs')
    p.add_argument('--exports',default='data/exports')
    a=p.parse_args()
    if date.fromisoformat(a.start)>date.fromisoformat(a.end):p.error('start after end')
    if a.batches<1 or a.batch_races<1 or a.batch_races>250 or a.delay<3:p.error('Invalid batch or delay: min 3s, 1-250 races, batches >=1')
    return run(a)

if __name__=='__main__':
    raise SystemExit(main())
