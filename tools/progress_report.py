#!/usr/bin/env python3
"""Status report for the racing SQLite; does not claim unverified dates complete."""
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
import json,sqlite3,csv
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/racing_history.sqlite'; OUT=ROOT/'data/exports'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if not DB.exists(): raise SystemExit('Missing database: '+str(DB))
    with sqlite3.connect(f'file:{DB}?mode=ro',uri=True) as con:
        rows=con.execute('SELECT race_date, COUNT(*) FROM races GROUP BY race_date').fetchall()
        counts=dict(rows)
        total=sum(counts.values())
        runners=con.execute('SELECT count(*) FROM runners').fetchone()[0]
        days={row[0]:dict(zip(['index_state','discovered'],row[1:])) for row in con.execute('SELECT race_date,index_state,discovered FROM days')}
        status=Counter(row[0] for row in con.execute('SELECT status FROM race_queue'))
        issues=[]
        for d,rid,payload in con.execute('SELECT race_date,race_id,data FROM races'):
            r=json.loads(payload)
            if r.get('qa_status') in ('review','imported_unverified') or r.get('qa_flags'):
                issues.append((d,rid,r.get('track'),r.get('qa_status'),r.get('qa_flags')))
    begin=date(2022,1,1); end=date(2026,10,31)
    with (OUT/'history_coverage_2022_2026.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['date','year','saved_races','date_index_state','discovered_links','coverage_assessment'])
        d=begin
        while d<=end:
            stamp=d.isoformat(); n=counts.get(stamp,0);day=days.get(stamp,{})
            w.writerow([stamp,d.year,n,day.get('index_state','NOT_INDEXED'),day.get('discovered',''),
                'REQUIRES INDEPENDENT VERIFICATION' if n else 'NO RACES IN LOCAL DATABASE'])
            d+=timedelta(days=1)
    with (OUT/'review_races.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['date','race_id','track','qa_status','qa_flags']);w.writerows(sorted(issues))
    result={'saved_races':total,'saved_runner_records':runners,'dates_with_records':len(counts),
        'year_races':{str(y):sum(n for day,n in rows if day.startswith(str(y))) for y in range(2022,2027)},
        'queue_statuses':dict(status),'races_with_flags':len(issues),
        'note':'No local date is marked fully complete solely from saved race counts. Verify against meeting list and original result.'}
    (OUT/'LIVE_PROGRESS_SUMMARY.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    print('VIEW THESE FILES:')
    print(' ',OUT/'history_coverage_2022_2026.csv')
    print(' ',OUT/'review_races.csv')
if __name__=='__main__':main()
