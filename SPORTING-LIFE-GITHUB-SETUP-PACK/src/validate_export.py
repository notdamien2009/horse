#!/usr/bin/env python3
"""Quality audit for historical racing CSVs. Never assumes row export order."""
from __future__ import annotations
import argparse,csv,json,math
from collections import defaultdict,Counter
from pathlib import Path

VALID={'finished','fell','brought_down','pulled_up','unseated_rider','refused',
       'ran_out','disqualified','did_not_finish','slipped_up','void','non_runner'}

def number(x):
    if x is None or str(x).strip()=='': return None
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError): return None

def readcsv(file):
    with file.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def audit(folder):
    races=readcsv(folder/'races_all.csv');runners=readcsv(folder/'runners_all.csv')
    issues=[]; warnings=[]; rr=defaultdict(list)
    for h in runners:rr[h['race_id']].append(h)
    race_ids={r['race_id'] for r in races}
    if len(race_ids)!=len(races):issues.append('duplicate_race_ids')
    if len({(r['race_id'],r['horse_id']) for r in runners})!=len(runners):issues.append('duplicate_race_horse_ids')
    for race in races:
        rid=race['race_id'];group=rr.get(rid,[])
        starters=[h for h in group if h['status']!='non_runner']
        finishers=[h for h in starters if h['status']=='finished']
        finishers.sort(key=lambda h:(number(h.get('position')) or math.inf,h['horse']))
        n=number(race.get('actual_runners'))
        if n is not None and len(starters)!=n:issues.append(f'{rid}:runner_count {len(starters)} != {n:g}')
        pos=[number(h.get('position')) for h in finishers]
        if pos!=list(range(1,len(pos)+1)):issues.append(f'{rid}:bad_finishing_positions {pos}')
        if finishers and number(race.get('finishers_captured')) is not None and number(race['finishers_captured']) != len(finishers):
            issues.append(f'{rid}:finisher_count_mismatch')
        win=number(race.get('winning_time_seconds'))
        if win is None:issues.append(f'{rid}:missing_winning_time')
        cumulative=0.0
        for h in finishers:
            name=h['horse'];margin=number(h.get('margin_lengths_numeric'))
            total=number(h.get('cumulative_beaten_lengths'))
            old=number(h.get('legacy_win_time_plus_dist'))
            if margin is None:
                cumulative=None
                if total is not None:issues.append(f'{rid}:{name}:unresolved_margin_has_total')
                continue
            if cumulative is not None: cumulative+=margin
            if cumulative is not None:
                if total is None or abs(total-cumulative)>0.00001:
                    issues.append(f'{rid}:{name}:bad_cumulative_margin')
                if win is not None and (old is None or abs(old-(win+cumulative))>0.00001):
                    issues.append(f'{rid}:{name}:bad_legacy_time')
            elif total is not None:
                issues.append(f'{rid}:{name}:cumulative_after_unknown_margin')
            if not h.get('comment'):
                issues.append(f'{rid}:{name}:missing_comment')
        for h in group:
            name=h['horse'];status=h.get('status')
            if status not in VALID:issues.append(f'{rid}:{name}:unknown_status {status}')
            if status!='finished':
                if number(h.get('legacy_win_time_plus_dist')) is not None:
                    issues.append(f'{rid}:{name}:nonfinisher_has_time')
            if status!='non_runner' and number(h.get('weight_lb')) is None:
                issues.append(f'{rid}:{name}:missing_weight')
            if status!='non_runner' and not h.get('comment'):
                warnings.append(f'{rid}:{name}:running_comment_missing')
            # Flag suspect jockey spillover rather than declaring all comments complete.
            jockey=h.get('jockey') or ''
            if any(x in jockey.lower() for x in ('mid-division','not fluent','held up','towards rear','weakened')):
                warnings.append(f'{rid}:{name}:possible_comment_in_jockey')
        if race.get('qa_status')=='review':warnings.append(f'{rid}:race_requires_review')
        if (race.get('course_configuration') or '').strip()=='':warnings.append(f'{rid}:course_configuration_unknown')
        if str(race.get('standards_input_allowed','')).lower()=='true':issues.append(f'{rid}:standards_approved_without_review')
    for rid in rr:
        if rid not in race_ids:issues.append(f'{rid}:runners_without_race')
    return {'race_records':len(races),'runner_records':len(runners),
      'statuses':dict(Counter(h.get('status') for h in runners)),
      'errors':len(issues),'error_examples':issues[:100],
      'warnings':len(warnings),'warning_examples':warnings[:100],
      'standard_time_eligibility':'NOT VERIFIED — course configuration and source checks still required'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,default=Path('data/exports'))
    a=p.parse_args();report=audit(a.folder)
    (a.folder/'v23_accuracy_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    raise SystemExit(1 if report['errors'] else 0)
