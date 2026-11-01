#!/usr/bin/env python3
"""Report distinct structural and standards-readiness flags without hiding data."""
from __future__ import annotations
import argparse
import collections
import csv
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STRUCTURAL={
 'invalid_or_missing_winning_time', 'invalid_distance', 'no_finishers_parsed',
 'runner_count_mismatch', 'finish_order_gap_or_duplicate',
 'duplicate_horse_in_race','non_runner_text_only_not_captured',
 'non_runner_unclosed_record','no_runner_rows_recognised'
}

def structural_flags(flags):
    return {f for f in flags if f in STRUCTURAL or
            f.startswith(('unmatched_horse_','duplicate_profile_anchor_'))}

def summarise(races):
    all_flags=collections.Counter()
    structural=collections.Counter()
    by_track=collections.defaultdict(collections.Counter)
    unapproved=0
    structural_races=0
    status=collections.Counter()
    total=0
    for race in races:
        total+=1
        status[str(race.get('qa_status') or 'unknown')]+=1
        track=str(race.get('track') or '(unknown)')
        if race.get('standards_input_allowed') is not True:
            unapproved+=1
        flags={f for f in str(race.get('qa_flags') or '').split('|') if f}
        found=structural_flags(flags)
        if found:structural_races+=1
        for flag in flags:
            all_flags[flag]+=1
            by_track[track][flag]+=1
        for flag in found:structural[flag]+=1
    return {
      'total_races':total,
      'qa_status_counts':dict(sorted(status.items())),
      'not_approved_for_standards':unapproved,
      'distinct_races_with_structural_flags':structural_races,
      'all_flag_counts':dict(sorted(all_flags.items(),key=lambda x:(-x[1],x[0]))),
      'structural_flag_counts':dict(sorted(structural.items(),key=lambda x:(-x[1],x[0]))),
      'by_track':{k:dict(v) for k,v in sorted(by_track.items())},
      'note':'Coverage incomplete. Inferred surfaces and symbolic margins are NOT independently verified.'
    }

def generate(db_path,output_dir):
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True) as con:
        races=[json.loads(raw) for (raw,) in con.execute('SELECT data FROM races')]
    summary=summarise(races)
    (output_dir/'qa_diagnostics.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    with (output_dir/'qa_flags_by_track.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['track','flag','number_of_races'])
        for track,flags in sorted(summary['by_track'].items()):
            for flag,num in sorted(flags.items(),key=lambda x:(-x[1],x[0])):
                w.writerow([track,flag,num])
    print(f'QA report: {summary["total_races"]} races, '
          f'{summary["distinct_races_with_structural_flags"]} with structural flags; '
          f'{summary["not_approved_for_standards"]} unapproved.')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',default=str(ROOT/'data/racing_history.sqlite'))
    p.add_argument('--output-dir',default=str(ROOT/'data/exports'))
    args=p.parse_args()
    generate(args.database,args.output_dir)
