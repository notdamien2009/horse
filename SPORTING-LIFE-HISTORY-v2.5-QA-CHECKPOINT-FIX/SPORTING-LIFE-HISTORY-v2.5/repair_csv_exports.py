#!/usr/bin/env python3
"""Offline repair of saved CSVs. Never modifies inputs or requests website data."""
from __future__ import annotations
import argparse,csv,json,collections
from pathlib import Path
from sl_structured_parser import fields_after_anchor
from sl_history import numeric_margin,runner_sort_key
from validate_export import audit


def load(path):
    with path.open(encoding='utf-8-sig',newline='') as fp:
        reader=csv.DictReader(fp)
        return list(reader),reader.fieldnames

def save(path,rows,fields):
    with path.open('w',encoding='utf-8-sig',newline='') as fp:
        w=csv.DictWriter(fp,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def fix(races_file,runners_file,dest):
    races,race_fields=load(races_file); runners,runner_fields=load(runners_file)
    if not races or not runners: raise ValueError('Both input CSVs must have rows')
    dest.mkdir(parents=True,exist_ok=True)
    by_race=collections.defaultdict(list)
    corrected_comment=[]
    for h in runners:
        if h.get('status')!='non_runner' and h.get('runner_text_raw'):
            info=fields_after_anchor(h['runner_text_raw'])
            # A recovered earlier opening is evidence-backed by the preserved
            # raw row text. Never truncate an existing comment to 'improve' it.
            prev=h.get('comment') or ''
            new=info.get('comment') or ''
            orig_jockey=h.get('jockey') or ''
            new_jockey=info.get('jockey') or ''
            if new and new_jockey and len(new)>len(prev) and (not prev or prev in new):
                h['comment']=new
                h['comment_raw']=info.get('comment_raw') or h.get('comment_raw')
                h['jockey']=new_jockey
                corrected_comment.append({'race_id':h['race_id'],'horse':h['horse'],
                                          'old_comment':prev,'new_comment':new,
                                          'old_jockey':orig_jockey,'new_jockey':new_jockey})
        by_race[h['race_id']].append(h)
    wrace={r['race_id']:r for r in races}
    corrected_margins=[]
    output=[]
    for race_id,group in by_race.items():
        group.sort(key=runner_sort_key)
        winning_time=wrace.get(race_id,{}).get('winning_time_seconds')
        try: w=float(winning_time)
        except (TypeError,ValueError):w=None
        cum=0.0
        for h in group:
            if h['status']=='finished':
                try:pos=int(float(h['position']))
                except (ValueError,TypeError):pos=-1
                raw=h.get('margin_from_preceding')
                margin=0 if pos==1 else numeric_margin(raw)
                old=h.get('cumulative_beaten_lengths')
                if margin is None or cum is None: cum=None
                else: cum=round(cum+margin,4)
                h['margin_lengths_numeric']=margin
                h['cumulative_beaten_lengths']=cum
                h['win_dist_from_winner']=cum
                h['legacy_win_time_plus_dist']=round(w+cum,4) if w is not None and cum is not None else None
            else:
                for field in ('margin_lengths_numeric','cumulative_beaten_lengths',
                              'win_dist_from_winner','legacy_win_time_plus_dist'):
                    h[field]=None
            output.append(h)
    output.sort(key=lambda r:(r.get('date') or '',str(r.get('race_id')),runner_sort_key(r)))
    races.sort(key=lambda r:(r.get('date') or '',str(r.get('race_id'))))
    save(dest/'races_all.csv',races,race_fields)
    save(dest/'runners_all.csv',output,runner_fields)
    report=audit(dest)
    report['comments_recovered_from_saved_raw_rows']=len(corrected_comment)
    (dest/'v23_accuracy_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'comment_repairs.json').write_text(json.dumps(corrected_comment,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--races',type=Path,required=True)
    a.add_argument('--runners',type=Path,required=True)
    a.add_argument('--output',type=Path,default=Path('corrected_exports'))
    x=a.parse_args()
    result=fix(x.races,x.runners,x.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(1 if result['errors'] else 0)
