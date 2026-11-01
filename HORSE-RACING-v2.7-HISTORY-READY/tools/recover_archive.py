#!/usr/bin/env python3
"""Recover and audit racing records from the user's existing SQLite + CSV files.

Never accesses a website, never marks unverified results suitable for standards,
and never destroys an existing database. Python standard library only.
"""
import argparse
import csv
import datetime as dt
import json
import sqlite3
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
RACE_HEAD = ['date','race_id','track','race_name','scheduled_time','actual_off_time','distance_raw','distance_yards','class','going','surface','race_type','declared_runners','actual_runners','winning_time_raw','winning_time_seconds','status','course_configuration','finishers_captured','nonfinishers_captured','nonrunners_captured','qa_status','qa_flags','standards_input_allowed','url','source','extracted_at_utc']
RUN_HEAD = ['date','race_id','track','horse_id','horse','position','status','status_raw','saddlecloth','draw','margin_from_preceding','margin_lengths_numeric','cumulative_beaten_lengths','win_dist_from_winner','legacy_win_time_plus_dist','age','weight_raw','weight_lb','odds_raw','trainer','jockey','comment','comment_raw','runner_text_raw','identity_source','source','url','extracted_at_utc']
FLOAT = {'winning_time_seconds','margin_lengths_numeric','cumulative_beaten_lengths','win_dist_from_winner','legacy_win_time_plus_dist'}
INT = {'distance_yards','actual_runners','declared_runners','finishers_captured','nonfinishers_captured','nonrunners_captured','position','saddlecloth','draw','age','weight_lb'}
BOOLEANS={'standards_input_allowed'}

def normalise(row):
    out={}
    for k,v in row.items():
        if k is None:continue
        if v is None or (isinstance(v,str) and v.strip()==''):
            out[k]=None if k in FLOAT|INT|BOOLEANS else '';continue
        if k in FLOAT:
            try:out[k]=float(v)
            except (ValueError,TypeError):out[k]=None
        elif k in INT:
            try:out[k]=int(float(v))
            except (ValueError,TypeError):out[k]=None
        elif k in BOOLEANS:
            out[k]=str(v).lower() in ('1','true','yes')
        else:out[k]=str(v)
    return out

def readcsv(p):
    with p.open(newline='',encoding='utf-8-sig') as f:
        return [normalise(r) for r in csv.DictReader(f)]

def snapshot_db(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if not src.is_file():raise FileNotFoundError(src)
    with sqlite3.connect(f'file:{src}?mode=ro',uri=True) as inp,sqlite3.connect(dst) as out:
        inp.backup(out)
        test=out.execute('PRAGMA integrity_check').fetchone()[0]
        if test!='ok':raise RuntimeError('SQLite integrity failure: '+str(test))

def ensure_tables(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS recovery_provenance (
      record_type TEXT NOT NULL, race_id TEXT NOT NULL, record_id TEXT NOT NULL,
      imported_from TEXT NOT NULL, imported_utc TEXT NOT NULL,
      PRIMARY KEY(record_type,race_id,record_id));
    CREATE TABLE IF NOT EXISTS recovery_conflicts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, record_type TEXT, race_id TEXT,
      record_id TEXT, key_field TEXT, existing_value TEXT, incoming_value TEXT,
      candidate_source TEXT);
    CREATE TABLE IF NOT EXISTS recovery_audit (
      race_id TEXT PRIMARY KEY, race_date TEXT, track TEXT,
      finishers INTEGER, nonfinishers INTEGER, nonrunners INTEGER,
      qa_issues TEXT, standards_eligible INTEGER NOT NULL DEFAULT 0);
    ''')

def import_csv(con,kind,path):
    counts=Counter()
    base_keys=['race_id','race_date','data'] if kind=='races' else ['race_id','horse_id','data']
    source_name=path.name
    compare_fields=['winning_time_seconds','distance_yards','track','race_name'] if kind=='races' else ['horse','status','position','weight_lb','margin_from_preceding','comment']
    for row in readcsv(path):
        rid=str(row.get('race_id') or '').strip()
        if not rid:
            counts['skipped_missing_race_id']+=1;continue
        if kind=='races':
            key=rid
            rdate=row.get('date') or row.get('race_date')
            if not rdate:
                counts['skipped_missing_date']+=1;continue
            existing=con.execute('SELECT data FROM races WHERE race_id=?',(key,)).fetchone()
        else:
            hid=str(row.get('horse_id') or '').strip()
            if not hid:
                counts['skipped_missing_horse_id']+=1;continue
            existing=con.execute('SELECT data FROM runners WHERE race_id=? AND horse_id=?',(rid,hid)).fetchone()
        if existing:
            old=json.loads(existing[0]);counts['already_saved']+=1
            for f in compare_fields:
                a,b=old.get(f),row.get(f)
                if a is not None and a!='' and b is not None and b!='' and str(a)!=str(b):
                    # A recorded difference is not assumed to be a source error.
                    if f=='comment' and isinstance(a,str) and isinstance(b,str) and (a in b or b in a):
                        continue
                    con.execute('''INSERT INTO recovery_conflicts(record_type,race_id,record_id,key_field,existing_value,incoming_value,candidate_source)
                         VALUES (?,?,?,?,?,?,?)''', (kind,rid,rid if kind=='races' else hid,f,str(a)[:500],str(b)[:500],source_name))
                    counts['field_conflicts']+=1
            continue
        # Retain all supplied raw fields; do not pretend these rows have been verified.
        row['standards_input_allowed']=False if kind=='races' else row.get('standards_input_allowed')
        if kind=='races':
            if not row.get('qa_status'):row['qa_status']='imported_unverified'
            con.execute('INSERT INTO races(race_id,race_date,data) VALUES(?,?,?)', (rid,rdate,json.dumps(row,ensure_ascii=False)))
        else:
            if con.execute('SELECT 1 FROM races WHERE race_id=?',(rid,)).fetchone() is None:
                counts['skipped_orphan_runner']+=1;continue
            con.execute('INSERT INTO runners(race_id,horse_id,data) VALUES(?,?,?)',(rid,hid,json.dumps(row,ensure_ascii=False)))
        con.execute('''INSERT OR IGNORE INTO recovery_provenance VALUES(?,?,?,?,?)''',(
            kind,rid,rid if kind=='races' else hid,source_name,dt.datetime.now(dt.timezone.utc).isoformat()))
        counts['added']+=1
        if kind=='races':
            con.execute("UPDATE race_queue SET status='parsed',last_error=NULL WHERE race_id=? AND status!='parsed'",(rid,))
    return dict(counts)

def audit(con):
    by_race=defaultdict(list)
    for rid,data in con.execute('SELECT race_id,data FROM runners'):
        by_race[rid].append(json.loads(data))
    con.execute('DELETE FROM recovery_audit')
    summary=Counter()
    for rid,rdate,data in con.execute('SELECT race_id,race_date,data FROM races'):
        race=json.loads(data)
        runners=by_race[rid]
        finish=[r for r in runners if r.get('status')=='finished']
        nf=[r for r in runners if r.get('status') not in ('finished','non_runner')]
        nr=[r for r in runners if r.get('status')=='non_runner']
        issues=[]
        def flag(s):
            if s not in issues:issues.append(s)
        t=race.get('winning_time_seconds')
        try: valid_time=0<float(t)<1200
        except (TypeError,ValueError):valid_time=False
        if not valid_time:flag('winning_time_invalid_or_missing')
        d=race.get('distance_yards')
        try: valid_dist=int(d)>=220
        except (TypeError,ValueError):valid_dist=False
        if not valid_dist:flag('distance_invalid_or_missing')
        if not race.get('going'):flag('going_missing')
        if not race.get('surface'):flag('surface_missing')
        if not race.get('course_configuration'):flag('course_configuration_unverified')
        if race.get('status')!='weighed_in':flag('result_status_unverified')
        if not finish:flag('no_finishers')
        positions=[]
        for r in finish:
            try:positions.append(int(r.get('position')))
            except (ValueError,TypeError):flag('position_missing_or_non_numeric')
        if sorted(positions)!=list(range(1,len(finish)+1)):flag('finish_positions_not_contiguous')
        if race.get('actual_runners') not in ('',None):
            try:
                if int(race['actual_runners'])!=len(finish)+len(nf):flag('starter_count_mismatch')
            except (ValueError,TypeError):flag('starter_count_invalid')
        if any(not r.get('comment') for r in finish+nf):flag('running_comment_missing')
        if any(r.get('weight_lb') in ('',None) for r in finish+nf):flag('runner_weight_missing')
        if any(r.get('margin_from_preceding') and r.get('cumulative_beaten_lengths') in ('',None) for r in finish):flag('cumulative_margin_unavailable')
        if any(r.get('horse_id') in ('',None) for r in runners):flag('horse_identity_missing')
        if any(r.get('status') not in ('finished','non_runner','fell','brought_down','pulled_up','unseated','unseated_rider','refused','refused_to_race','ran_out','void','other_nonfinisher') for r in runners):flag('unknown_runner_status')
        for x in issues:summary[x]+=1
        con.execute('INSERT INTO recovery_audit VALUES (?,?,?,?,?,?,?,0)', (rid,rdate,race.get('track'),len(finish),len(nf),len(nr),'|'.join(issues)))
    return dict(summary)

def write_csv(path,rows,preferred):
    path.parent.mkdir(parents=True,exist_ok=True)
    keys=list(preferred)+sorted(set().union(*(r.keys() for r in rows))-set(preferred)) if rows else list(preferred)
    with path.open('w',newline='',encoding='utf-8-sig') as fp:
        writer=csv.DictWriter(fp,keys,extrasaction='ignore');writer.writeheader()
        for row in rows:
            writer.writerow({k:'' if v is None else ('true' if v is True else 'false' if v is False else v) for k,v in row.items()})
    return len(keys)

def export(con,out,start='2022-01-01',end='2026-10-31'):
    out.mkdir(parents=True,exist_ok=True)
    race_rows=[json.loads(d) for (d,) in con.execute('SELECT data FROM races ORDER BY race_date,race_id')]
    runner_rows=[json.loads(d) for (d,) in con.execute('SELECT ru.data FROM runners ru JOIN races ra ON ru.race_id=ra.race_id ORDER BY ra.race_date,ru.race_id, CASE WHEN json_extract(ru.data,\'$.status\')=\'finished\' THEN 0 ELSE 1 END, CAST(json_extract(ru.data,\'$.position\') AS INT),ru.horse_id')]
    for r in race_rows:r['standards_input_allowed']=False
    def race_date(r):return r.get('date') or r.get('race_date') or ''
    race_type_by_id={x.get('race_id'):x.get('race_type') for x in race_rows}
    for r in runner_rows:
        typ=race_type_by_id.get(r.get('race_id'))
        # 9st Flat and 11st hurdles/chases per user's stated original benchmark.
        # NH Flat is not forced into either category without a verified convention.
        r['reference_weight_lb']=126 if typ=='flat' else 154 if typ in ('hurdle','chase') else None
    write_csv(out/'races_all.csv',race_rows,RACE_HEAD)
    write_csv(out/'runners_all.csv',runner_rows,RUN_HEAD+['reference_weight_lb'])
    qa_rows=[]
    for rid,rd,track,finish,nf,nr,issues,allowed in con.execute('SELECT * FROM recovery_audit ORDER BY race_date,race_id'):
        qa_rows.append(dict(race_date=rd,race_id=rid,track=track,finishers=finish,nonfinishers=nf,nonrunners=nr,issues=issues,standards_input_allowed=False))
    write_csv(out/'qa_issues.csv',qa_rows,['race_date','race_id','track','finishers','nonfinishers','nonrunners','issues','standards_input_allowed'])
    conflicts=[dict(zip(['id','record_type','race_id','record_id','key_field','existing_value','incoming_value','candidate_source'],z))
        for z in con.execute('SELECT * FROM recovery_conflicts')]
    write_csv(out/'source_conflicts.csv',conflicts,['id','record_type','race_id','record_id','key_field','existing_value','incoming_value','candidate_source'])
    byday=Counter(race_date(r) for r in race_rows)
    st=dt.date.fromisoformat(start);en=dt.date.fromisoformat(end)
    days=[];cur=st
    while cur<=en:
        key=cur.isoformat();count=byday.get(key,0)
        days.append(dict(race_date=key,year=cur.year,races_available=count,coverage_status='PARTIAL / UNVERIFIED' if count else 'NOT COLLECTED',complete=False))
        cur+=dt.timedelta(days=1)
    write_csv(out/'coverage_calendar.csv',days,['race_date','year','races_available','coverage_status','complete'])
    counts=Counter(race_date(r)[:4] for r in race_rows)
    unique_days=Counter(k[:4] for k,v in byday.items() if v)
    stats={'date_range_requested':[start,end],'races':len(race_rows),'runners':len(runner_rows),
        'races_by_year':{str(y):counts.get(str(y),0) for y in range(int(start[:4]),int(end[:4])+1)},
        'days_with_any_data':dict(unique_days),'days_in_range':len(days),
        'issues_by_name':dict(Counter(x for q in qa_rows for x in q['issues'].split('|') if x)),
        'source_conflicts':len(conflicts),'standards_approved':0,
        'coverage_warning':'Only dates with actual uploaded records are present; this is not a complete historical archive.',
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (out/'recovery_summary.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
    return stats

def run():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed-db',type=Path,default=ROOT/'seed/original_racing_history.sqlite')
    p.add_argument('--output-db',type=Path,default=ROOT/'data/racing_history.sqlite')
    p.add_argument('--export-dir',type=Path,default=ROOT/'data/exports')
    p.add_argument('--seed-dir',type=Path,default=ROOT/'seed')
    a=p.parse_args()
    if a.output_db.resolve()==a.seed_db.resolve():p.error('Output must differ from seed: do not overwrite the original')
    if not a.output_db.exists():snapshot_db(a.seed_db,a.output_db)
    if sqlite3.connect(a.output_db).execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Bad output SQLite')
    con=sqlite3.connect(a.output_db)
    try:
        with con:
            ensure_tables(con)
            report={}
            for date_label in ('2022','2026'):
                report['races_'+date_label]=import_csv(con,'races',a.seed_dir/f'races_{date_label}.csv')
                report['runners_'+date_label]=import_csv(con,'runners',a.seed_dir/f'runners_{date_label}.csv')
            report['audit']=audit(con)
        stats=export(con,a.export_dir)
        report['summary']=stats
        print(json.dumps(report,indent=2))
    finally:con.close()
if __name__=='__main__':run()
