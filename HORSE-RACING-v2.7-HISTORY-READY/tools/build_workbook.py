#!/usr/bin/env python3
"""Create an XLSX of recovered (not complete 2022-2026) racing data using artifact_tool."""
import csv, json
from pathlib import Path
from artifact_tool import Workbook, SpreadsheetFile
ROOT=Path(__file__).resolve().parents[1]
EXP=ROOT/'data/exports'
OUT=EXP/'horse_results_2022_2026_RECOVERED_PARTIAL.xlsx'

def data(fn):
    with (EXP/fn).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def cell_value(s):
    if s in ('','None',None):return None
    if isinstance(s,str) and s[:1] in ('=','+','-','@'):
        # Formula injection protection only in workbook; raw CSV stays byte-for-byte faithful.
        try: return float(s)
        except ValueError:return "'"+s
    if str(s).lower() in ('true','false'):return str(s).lower()=='true'
    return s

def populate_sheet(wb,name,fields,rows,widths=None,color='#194D63'):
    sheet=wb.worksheets.add(name)
    table=[[str(h).replace('_',' ').title() for h in fields]]
    for row in rows:table.append([cell_value(row.get(f)) for f in fields])
    if len(fields)>0:
        sheet.get_range_by_indexes(0,0,len(table),len(fields)).values=table
        header=sheet.get_range_by_indexes(0,0,1,len(fields));header.format={'fill':color,'font':{'bold':True,'color':'#FFFFFF'},'row_height':30,'wrap_text':True,'vertical_alignment':'center'}
        sheet.freeze_panes.freeze_rows(1)
        for i,f in enumerate(fields):
            width=widths.get(f,17) if widths else 17
            sheet.get_range_by_indexes(0,i,len(table),1).format.column_width=width
        # Most readers can filter via Excel Data > Filter; tables are useful when available.
        if 1<len(table)<2500 and len(fields)<=40:
            try:sheet.tables.add(sheet.get_range_by_indexes(0,0,len(table),len(fields)),True,'Tbl'+name.replace(' ','').replace('-',''))
            except Exception:pass
    return sheet

wb=Workbook.create()
summary=json.loads((EXP/'recovery_summary.json').read_text())
summary_sheet=wb.worksheets.add('Overview')
summary_sheet.get_range('A1:H1').merge();summary_sheet.get_range('A1').values=[['HORSE RACING • RECOVERED RESULTS']]
summary_sheet.get_range('A1:H1').format={'fill':'#11354B','font':{'bold':True,'color':'#FFFFFF','size':17},'row_height':42,'vertical_alignment':'center'}
summary_sheet.get_range('A3').values=[['Status']];summary_sheet.get_range('B3:D3').merge();summary_sheet.get_range('B3').values=[['PARTIAL ARCHIVE — NOT FULL 2022–2026 COVERAGE']]
summary_sheet.get_range('A3').format={'font':{'bold':True}}
summary_sheet.get_range('B3:D3').format={'fill':'#FFF1D6','font':{'color':'#8A5A00','bold':True},'row_height':28}
for row,name,v in [(5,'Races recovered',28),(6,'Horse records recovered',242),(7,'Years included','2022 and 2026 only'),(8,'Dates with actual records',2),(9,'Date range targeted','2022-01-01 to 2026-10-31'),(10,'Standard-time eligible races',0),(11,'Original 40th-percentile standards','NOT calculated')]:
    summary_sheet.get_range(f'A{row}').values=[[name]]
    summary_sheet.get_range(f'B{row}').values=[[v]]
    summary_sheet.get_range(f'A{row}').format={'font':{'bold':True}}
summary_sheet.get_range('A14:H14').merge();summary_sheet.get_range('A14').values=[['WHY THIS IS NOT A COMPLETE HISTORICAL DATABASE']]
summary_sheet.get_range('A14:H14').format={'fill':'#E3EDF3','font':{'bold':True,'color':'#11354B'},'row_height':26}
notes=[
 'Only one race date in 2022 and one date in 2026 have recovered records; 2023–2025 remain uncollected.',
 'All original racing fields are kept, including horse comments, finishing statuses, and original margin text.',
 'Cumulative lengths and legacy winning-time-plus-distance are preserved where available; they are not measured elapsed time.',
 'The previous nk = 0.01 convention is preserved, but it is a legacy rating convention, not 0.01 seconds measured.',
 'Course configuration, amended finishes and some symbolic margins still need independent verification.',
 'All records are excluded from newly computed standard times until QA and course configuration are approved.',
 'The repository is currently public. Do not upload raw licensed data there without appropriate rights.'
]
for j,line in enumerate(notes,start=16):
    summary_sheet.get_range(f'A{j}:H{j}').merge()
    summary_sheet.get_range(f'A{j}').values=[[line]]
    summary_sheet.get_range(f'A{j}:H{j}').format={'wrap_text':True,'row_height':29}
summary_sheet.get_range('A:A').format.column_width=31
summary_sheet.get_range('B:H').format.column_width=22

races=data('races_all.csv'); runners=data('runners_all.csv');qa=data('qa_issues.csv');calendar=data('coverage_calendar.csv')
years=[]
for y in range(2022,2027):
    ra=sum(r.get('date','').startswith(str(y)) for r in races)
    ru=sum(r.get('date','').startswith(str(y)) for r in runners)
    days=len({r.get('date') for r in races if r.get('date','').startswith(str(y))})
    years.append({'year':y,'races':ra,'horse_records':ru,'days_with_any_records':days,'archive_complete':'NO'})
populate_sheet(wb,'Year Coverage',['year','races','horse_records','days_with_any_records','archive_complete'],years,{'year':12,'races':14,'horse_records':18,'days_with_any_records':25,'archive_complete':20})

race_fields=list(races[0]);runner_fields=list(runners[0])
populate_sheet(wb,'Races',race_fields,races,{'race_id':16,'date':15,'track':19,'race_name':45,'url':40,'qa_flags':36,'going':20,'winning_time_seconds':22,'distance_yards':20,'course_configuration':25})
populate_sheet(wb,'Runners',runner_fields,runners,{'race_id':16,'date':15,'horse_id':17,'horse':26,'comment':56,'comment_raw':56,'runner_text_raw':40,'margin_from_preceding':24,'cumulative_beaten_lengths':26,'legacy_win_time_plus_dist':27,'url':40,'reference_weight_lb':23})
populate_sheet(wb,'QA Review',list(qa[0]),qa,{'race_id':16,'race_date':16,'track':23,'issues':60,'standards_input_allowed':28},'#855114')
populate_sheet(wb,'Coverage Calendar',list(calendar[0]),calendar,{'race_date':18,'year':12,'races_available':20,'coverage_status':35,'complete':15},'#485E6A')
dictionary=[
  {'field':'race_id / horse_id','meaning':'Source-specific race and horse identifiers; never assume IDs from different providers match.'},
  {'field':'winning_time_seconds','meaning':'Race-winning recorded time in seconds. Not the time of every runner.'},
  {'field':'distance_yards','meaning':'Reported race distance in yards; verify course configurations and distance adjustments.'},
  {'field':'actual_runners','meaning':'Published starter count. Audit against finishers + non-finishers.'},
  {'field':'status','meaning':'finished / fell / brought_down / pulled_up / unseated_rider / non_runner etc.'},
  {'field':'margin_from_preceding','meaning':'Original published beaten margin text to preceding finisher.'},
  {'field':'cumulative_beaten_lengths','meaning':'Sum of converted margins in official finishing order, if every relevant margin is available.'},
  {'field':'legacy_win_time_plus_dist','meaning':'User legacy numeric winning_time_seconds + cumulative_beaten_lengths; NOT measured time.'},
  {'field':'reference_weight_lb','meaning':'126 Flat, 154 hurdle/chase; NH Flat deliberately blank pending specification.'},
  {'field':'qa_flags / issues','meaning':'Reasons a result needs confirmation; the presence of a row does NOT mean verified.'},
  {'field':'course_configuration','meaning':'Layout or course variant; unverified values are blank.'},
  {'field':'standards_input_allowed','meaning':'False until independent source QA and course metadata approve the race.'},
  {'field':'url','meaning':'Original race-result web address where supplied.'},
  {'field':'comment / comment_raw','meaning':'Running commentary from the supplied records; may require source checks before further distribution.'}
]
populate_sheet(wb,'Field Dictionary',['field','meaning'],dictionary,{'field':34,'meaning':110},'#455E77')

# Programmatic verification, useful on Windows when regenerating workbook.
check=wb.inspect({'kind':'table','range':'Year Coverage!A1:E6','include':'values','table_max_rows':6,'table_max_cols':5})
print(check.ndjson[:2300])
try:
    err=wb.inspect({'kind':'match','search_term':'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A','options':{'use_regex':True,'max_results':50},'summary':'formula error scan'})
    print('FORMULA_ERRORS:',err.ndjson[:800])
except Exception as e:print('FORMULA_ERROR_SCAN_UNAVAILABLE:',str(e)[:300])
SpreadsheetFile.export_xlsx(wb).save(str(OUT))
print('EXPORTED',OUT,OUT.stat().st_size)
