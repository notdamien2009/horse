#!/usr/bin/env python3
"""Create a self-contained, searchable HTML report from a local SQLite racing archive.

Requires only Python's standard library. Reads the ORIGINAL SQLite database
in read-only mode (including committed WAL transactions) and leaves it intact.
A .sqlite-wal file alone is insufficient; supply racing_history.sqlite.
"""
from __future__ import annotations

import argparse
import calendar
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

FIELDS_RACE = [
    ('race_date', 'Date'), ('scheduled_time', 'Off time'), ('track', 'Course'),
    ('race_name', 'Race'), ('race_type', 'Type'), ('distance_yards', 'Distance (yd)'),
    ('going', 'Going'), ('surface', 'Surface'), ('winning_time_seconds', 'Winning time (s)'),
    ('actual_runners', 'Runners'), ('qa_status', 'QA status'), ('race_id', 'Race ID'),
]
FIELDS_HORSE = [
    ('race_date', 'Date'), ('scheduled_time', 'Off time'), ('track', 'Course'),
    ('horse', 'Horse'), ('position', 'Pos.'), ('status', 'Status'),
    ('trainer', 'Trainer'), ('jockey', 'Jockey'), ('odds', 'Odds'),
    ('margin_from_preceding', 'Margin'), ('cumulative_beaten_lengths', 'Beaten lengths'),
    ('weight_lb', 'Weight (lb)'), ('race_id', 'Race ID'),
]
FIELDS_DAY = [
    ('race_date', 'Date'), ('index_state', 'Index state'), ('discovered', 'Discovered'),
    ('parsed', 'Parsed'), ('pending', 'Pending'), ('errors', 'Errors'),
    ('review', 'QA review'), ('assessment', 'Coverage assessment'),
]


def parse_month(value):
    try:
        year, month = map(int, value.split('-'))
        if f'{year:04d}-{month:02d}' != value or not 1 <= month <= 12:
            raise ValueError
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('Month must be YYYY-MM, for example 2022-01')
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def obj(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {'raw_value': result}
    except (ValueError, TypeError):
        return {'parse_warning': 'Saved JSON could not be decoded', 'raw_value': str(value)[:4000]}


def scalar(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def pick(src, *names):
    for n in names:
        v = src.get(n)
        if v is not None and v != '':
            return v
    return ''


def tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def generate(db_path: Path, out_path: Path, month: str | None) -> dict:
    if db_path.name.lower().endswith(('-wal', '-shm')):
        raise ValueError('You selected a SQLite WAL/SHM companion file. Select racing_history.sqlite instead.')
    if not db_path.is_file():
        raise FileNotFoundError(f'Main database not found: {db_path}')
    start, end = parse_month(month) if month else (None, None)
    db_url = db_path.resolve().as_uri() + '?mode=ro'
    con = sqlite3.connect(db_url, uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute('BEGIN')  # consistent, read-only snapshot, even during WAL writes
        names = tables(con)
        if not {'races', 'runners'} <= names:
            raise ValueError('Database does not contain the expected races and runners tables.')
        cond = ' WHERE race_date BETWEEN ? AND ?' if start else ''
        params = (start.isoformat(), end.isoformat()) if start else ()
        race_rows = con.execute('SELECT race_id, race_date, data FROM races' + cond + ' ORDER BY race_date, race_id', params).fetchall()
        if len(race_rows) > 25000:
            raise ValueError('Too many races for a single HTML report. Use --month YYYY-MM to make smaller reports.')
        races = []
        race_by_id = {}
        for r in race_rows:
            saved = obj(r['data'])
            record = dict(saved)
            record['race_id'] = r['race_id']
            record['race_date'] = r['race_date']
            record['scheduled_time'] = pick(saved, 'scheduled_time', 'listed_time')
            record['track'] = pick(saved, 'track', 'course')
            record['race_name'] = pick(saved, 'race_name', 'name')
            record['qa_status'] = pick(saved, 'qa_status')
            record['_detail'] = saved
            races.append(record)
            race_by_id[str(r['race_id'])] = record
        horses = []
        if start:
            runrows = con.execute('''SELECT r.race_id, r.horse_id, r.data
                FROM runners r JOIN races a ON a.race_id=r.race_id
                WHERE a.race_date BETWEEN ? AND ? ORDER BY a.race_date,r.race_id,r.horse_id''', params)
        else:
            runrows = con.execute('SELECT race_id,horse_id,data FROM runners ORDER BY race_id,horse_id')
        for h in runrows:
            saved = obj(h['data'])
            parent = race_by_id.get(str(h['race_id']))
            if parent is None:
                continue
            record = dict(saved)
            record['race_id'] = h['race_id']
            record['horse_id'] = h['horse_id']
            record['race_date'] = parent['race_date']
            record['track'] = parent['track']
            record['scheduled_time'] = parent['scheduled_time']
            record['horse'] = pick(saved, 'horse', 'horse_name', 'name')
            record['trainer'] = pick(saved, 'trainer', 'trainer_name')
            record['jockey'] = pick(saved, 'jockey', 'jockey_name')
            record['odds'] = pick(saved, 'odds', 'sp', 'starting_price')
            record['_detail'] = saved
            horses.append(record)
        day_map = {}
        if 'days' in names:
            if start:
                day_rows = con.execute('SELECT * FROM days WHERE race_date BETWEEN ? AND ? ORDER BY race_date', params)
            else:
                day_rows = con.execute('SELECT * FROM days ORDER BY race_date')
            day_map = {r['race_date']: dict(r) for r in day_rows}
        counts = defaultdict(Counter)
        if 'race_queue' in names:
            q = "SELECT race_date,status,count(*) AS n FROM race_queue" + cond + ' GROUP BY race_date,status'
            for r in con.execute(q, params):
                counts[r['race_date']][r['status']] += r['n']
        by_day = Counter(r['race_date'] for r in races)
        qa_by_day = Counter(r['race_date'] for r in races if r.get('qa_flags') or r.get('qa_status') in ('review','imported_unverified'))
        days = []
        if start:
            all_dates = [ (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
        else:
            all_dates = sorted(set(day_map)|set(by_day)|set(counts))
        for day in all_dates:
            d = day_map.get(day, {})
            q = counts.get(day, Counter())
            discovered = d.get('discovered') or 0
            parsed = q.get('parsed', 0)
            pending = q.get('pending', 0)
            errors = q.get('error', 0)
            index_state = d.get('index_state', 'not_indexed')
            if index_state == 'error' or errors:
                assessment = 'Review errors'
            elif index_state != 'indexed':
                assessment = 'Not indexed'
            elif pending or (discovered and parsed < discovered):
                assessment = 'In progress'
            elif not discovered:
                assessment = 'Check empty day'
            else:
                assessment = 'Indexed — audit required'
            days.append({'race_date': day, 'index_state': index_state, 'discovered': discovered,
                         'parsed': parsed, 'pending': pending, 'errors': errors,
                         'review': qa_by_day[day], 'assessment': assessment})
        con.execute('ROLLBACK')
    finally:
        con.close()

    report = {
        'title': 'Sporting Life — Race Results Archive',
        'source': db_path.name,
        'month': month or 'All saved dates',
        'generated_utc': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
        'races': races, 'horses': horses, 'days': days,
        'columns': {'races': FIELDS_RACE, 'horses': FIELDS_HORSE, 'days': FIELDS_DAY},
        'stats': {
            'races': len(races), 'horses': len(horses), 'courses': len({str(r.get('track') or '') for r in races if r.get('track')}),
            'qa_review': sum(bool(r.get('qa_flags')) or r.get('qa_status') in ('review','imported_unverified') for r in races),
            'indexed_days': sum(d['index_state']=='indexed' for d in days),
            'days_total': len(days),
        },
        'disclaimer': 'Local database snapshot. Parsed records are not independently verified.'
    }
    payload = json.dumps(report, ensure_ascii=False, separators=(',', ':'), default=str)
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    output = HTML_TEMPLATE.replace('___ARCHIVE_JSON___', payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding='utf-8')
    return {'html': str(out_path.resolve()), 'races': len(races), 'horses': len(horses), 'days': len(days)}


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en-GB"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>Sporting Life · Racing data viewer</title>
<style>
:root{font-family:Inter,"Segoe UI",system-ui,Arial,sans-serif;color:#17273e;background:#f2f5f9;--navy:#122944;--blue:#2475dc;--line:#dce4ef;--muted:#66758a}
*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button{cursor:pointer}.top{background:linear-gradient(110deg,#10253f,#21486c);color:#fff;padding:28px max(24px,calc((100vw - 1420px)/2)) 32px}.eyebrow{font-size:12px;letter-spacing:2px;font-weight:700;color:#a9d1ff;text-transform:uppercase}.top h1{font-size:clamp(24px,3vw,36px);margin:10px 0}.top p{color:#cfdfed;margin:0;line-height:1.6}.wrap{max-width:1468px;padding:24px;margin:auto}.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:13px;margin-top:-39px;position:relative}.stat{background:white;border:1px solid var(--line);box-shadow:0 8px 28px #162f4f0c;border-radius:16px;padding:20px}.stat label{font-size:12px;color:var(--muted);font-weight:600;display:block}.stat strong{display:block;font-size:30px;margin-top:8px;font-variant-numeric:tabular-nums}.stat.warning strong{color:#bd6b1e}.notice{background:#fff9ec;border:1px solid #f3ddb4;color:#705220;padding:13px 16px;border-radius:12px;margin:20px 0 16px;font-size:13px;line-height:1.5}.panel{background:#fff;border:1px solid var(--line);border-radius:17px;overflow:hidden;box-shadow:0 4px 18px #182e4b08}.toolbar{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px;flex-wrap:wrap}.tabs{display:flex;flex-wrap:wrap;gap:7px}.tab{border:1px solid var(--line);background:#fff;color:#52657e;padding:10px 15px;border-radius:10px;font-weight:700;font-size:13px}.tab.active{background:var(--navy);color:white;border-color:var(--navy)}.field{border:1px solid #d6e1ed;padding:11px 12px;border-radius:10px;background:white;color:#21374e;min-width:175px}.search{flex:1;min-width:200px}.toolbar .right{margin-left:auto;display:flex;gap:10px;flex-wrap:wrap}.export{background:#eff6ff;border:1px solid #cfe0f8;color:#245b9b;font-weight:650;border-radius:10px;padding:10px 14px}.tableholder{overflow:auto;max-height:66vh}.table{width:100%;border-collapse:collapse;text-align:left;font-size:13px;white-space:nowrap}.table th{position:sticky;top:0;background:#f4f7fb;color:#58708a;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:13px 14px;border-bottom:1px solid var(--line);z-index:1}.table td{padding:12px 14px;border-bottom:1px solid #edf1f6;max-width:390px;overflow:hidden;text-overflow:ellipsis}.table tr:hover td{background:#f6faff;cursor:pointer}.table tr:nth-child(even){background:#fcfdff}.pill{border-radius:7px;padding:5px 9px;font-size:11px;font-weight:700;display:inline-block;background:#ebf2ff;color:#245b91}.pill.bad{background:#fff0e8;color:#ad4a19}.pill.ok{background:#eaf8ed;color:#237343}.muted{color:var(--muted)}.bottom{display:flex;justify-content:space-between;align-items:center;padding:15px 20px;border-top:1px solid var(--line);color:#677b92;font-size:13px;gap:12px;flex-wrap:wrap}.pagebuttons{display:flex;align-items:center;gap:8px}.pagebuttons button{padding:7px 13px;background:white;border:1px solid var(--line);border-radius:9px}.pagebuttons button:disabled{opacity:.45;cursor:not-allowed}.foot{font-size:12px;color:#66788e;margin-top:17px}.overlay{position:fixed;inset:0;background:#11203680;display:none;justify-content:flex-end;z-index:10}.overlay.open{display:flex}.drawer{width:min(650px,100%);height:100%;background:white;overflow:auto;padding:24px;box-shadow:-16px 0 40px #0002}.drawerhead{display:flex;align-items:flex-start;gap:20px;justify-content:space-between}.drawer h2{font-size:21px;line-height:1.3}.close{border:1px solid var(--line);background:#f6f8fb;border-radius:9px;padding:8px 12px}.detailgrid{display:grid;grid-template-columns:minmax(120px,190px) 1fr;gap:0;border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:20px}.detailgrid dt,.detailgrid dd{padding:11px 12px;margin:0;border-bottom:1px solid #edf1f5;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.detailgrid dt{background:#f6f8fc;color:#586e84;font-weight:700}.detailgrid dd{background:#fff;color:#253b53}.tiny{font-size:12px;color:#6a7990}.empty{padding:40px;text-align:center;color:var(--muted)}@media(max-width:860px){.stats{grid-template-columns:repeat(2,1fr)}.wrap{padding:16px}.top{padding:24px 18px 60px}.toolbar{padding:14px}.search{width:100%}.stat{padding:14px}.stat strong{font-size:23px}}@media(max-width:450px){.stats{grid-template-columns:repeat(2,1fr)}.tab{padding:9px}.toolbar .right{margin:0}.drawer{padding:15px}}
</style></head><body>
<header class="top"><div class="eyebrow">Historical racing archive · local snapshot</div><h1>Race Results Explorer</h1><p id="subtitle">Search saved races, horses, finishing positions and data-quality checks.</p></header>
<main class="wrap"><section class="stats" id="stats"></section><div class="notice">This is a read-only export of your local SQLite database. Records marked <b>parsed_not_verified</b> are not independently checked. This document works offline and does not send racing records to a server.</div>
<section class="panel"><div class="toolbar"><div class="tabs" id="tabs"></div><input id="search" class="field search" aria-label="Search rows" type="search" placeholder="Search course, horse, trainer, race..." /><div class="right"><select class="field" id="filter" aria-label="Filter by status"></select><button class="export" id="export">Export filtered CSV</button></div></div><div class="tableholder" id="tableholder"></div><div class="bottom"><span id="count"></span><div class="pagebuttons"><button id="prev">Previous</button><span id="paging"></span><button id="next">Next</button></div></div></section><p class="foot" id="footer"></p></main>
<div class="overlay" id="overlay" role="presentation"><div class="drawer" role="dialog" aria-modal="true" aria-label="Record details"><div class="drawerhead"><div><div class="eyebrow" style="color:#2475dc">Original saved fields</div><h2 id="detailtitle">Record details</h2><div class="tiny" id="detailmeta"></div></div><button class="close" id="close">Close</button></div><dl class="detailgrid" id="detailgrid"></dl></div></div>
<script type="application/json" id="data">___ARCHIVE_JSON___</script>
<script>
'use strict';
const report=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
let view='races',page=0,query='',filter='all'; const perPage=100;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>Number(n||0).toLocaleString('en-GB');
const badge=(v,k)=>{let s=String(v??'');if(!s)return '—';let c=/error|review|hold|not.indexed|critical/i.test(s)?'bad':/^(indexed|parsed|complete)$/i.test(s)?'ok':'';return '<span class="pill '+c+'">'+esc(s)+'</span>'};
const meta=[['races','Races'],['horses','Horse results'],['days','Date coverage']];
$('subtitle').textContent=`${report.month} · Generated ${report.generated_utc} · ${report.source}`;
$('footer').textContent=`${report.disclaimer} · Source: ${report.source}`;
$('stats').innerHTML=[['Saved races',report.stats.races],['Horse results',report.stats.horses],['Courses',report.stats.courses],['Indexed dates',report.stats.indexed_days+' / '+report.stats.days_total],['QA flagged races',report.stats.qa_review]].map((x,i)=>`<div class="stat ${i===4?'warning':''}"><label>${esc(x[0])}</label><strong>${typeof x[1]==='number'?fmt(x[1]):esc(x[1])}</strong></div>`).join('');
function getRows(){const s=query.trim().toLocaleLowerCase();return report[view].filter(row=>{
  if(filter!=='all') {const state=String(view==='days'?row.assessment:row.qa_status||'').toLowerCase();if(filter==='review' && !(view==='days'?(/review|error|not indexed|in progress|check empty/i.test(row.assessment)):Boolean(row.qa_flags)||state.includes('review')||state.includes('unverified')))return false; if(filter==='ok' && (view==='days'?row.assessment!=='Indexed — audit required':Boolean(row.qa_flags)||state.includes('review')))return false;}
  if(!s)return true;return report.columns[view].some(([k])=>String(row[k]??'').toLocaleLowerCase().includes(s))||(view==='horses'&&String(row.comment??'').toLocaleLowerCase().includes(s));
 });}
function draw(){const columns=report.columns[view], filtered=getRows(); const totalPages=Math.max(1,Math.ceil(filtered.length/perPage));page=Math.min(page,totalPages-1);const subset=filtered.slice(page*perPage,(page+1)*perPage);
 $('tabs').innerHTML=meta.map(([k,n])=>`<button class="tab ${k===view?'active':''}" data-view="${k}" aria-pressed="${k===view}">${n} <span style="opacity:.6">${fmt(report[k].length)}</span></button>`).join('');
 const table=`<table class="table"><thead><tr>${columns.map(([k,label])=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${subset.map((r,i)=>`<tr data-index="${page*perPage+i}" tabindex="0" title="Show saved details">${columns.map(([k])=>`<td>${k==='qa_status'||k==='assessment'||k==='index_state'?badge(r[k],k):esc(r[k]??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
 $('tableholder').innerHTML=subset.length?table:'<div class="empty">No matching results in this report.</div>';
 $('count').textContent=`Showing ${filtered.length?fmt(page*perPage+1):0}–${fmt(Math.min((page+1)*perPage,filtered.length))} of ${fmt(filtered.length)} rows`;
 $('paging').textContent=`Page ${page+1} of ${totalPages}`;$('prev').disabled=page===0;$('next').disabled=page>=totalPages-1;
 $('tabs').querySelectorAll('button').forEach(el=>el.onclick=()=>{view=el.dataset.view;page=0;filter='all';updateFilter();draw()});
 $('tableholder').querySelectorAll('tbody tr').forEach(el=>{const open=()=>details(filtered[Number(el.dataset.index)]);el.onclick=open;el.onkeydown=e=>{if(e.key==='Enter')open()}});
}
function updateFilter(){$('filter').innerHTML='<option value="all">All records</option><option value="review">Needs review / incomplete</option><option value="ok">No flagged issues</option>';$('filter').value=filter;}
function details(row){if(!row)return;const detail={...row._detail,...row};delete detail._detail;const keys=Object.keys(detail).filter(k=>!k.startsWith('_'));$('detailtitle').textContent=row.horse||row.race_name||row.race_date||'Saved record';$('detailmeta').textContent=[row.race_date,row.track,row.race_id?`Race ID ${row.race_id}`:''].filter(Boolean).join(' · ');
 $('detailgrid').innerHTML=keys.map(k=>`<dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(typeof detail[k]==='object'&&detail[k]!==null?JSON.stringify(detail[k],null,2):detail[k]??'—')}</dd>`).join('');$('overlay').classList.add('open');$('close').focus();}
function close(){ $('overlay').classList.remove('open'); }
$('close').onclick=close;$('overlay').onclick=e=>{if(e.target===$('overlay'))close()};window.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
$('search').oninput=e=>{query=e.target.value;page=0;draw()};$('filter').onchange=e=>{filter=e.target.value;page=0;draw()};$('prev').onclick=()=>{page=Math.max(0,page-1);draw()};$('next').onclick=()=>{page++;draw()};
$('export').onclick=()=>{const cols=report.columns[view];const quote=v=>'"'+String(v??'').replaceAll('"','""').replace(/\r?\n/g,' ')+'"';const rows=[cols.map(x=>x[1]),...getRows().map(r=>cols.map(([key])=>r[key]))];const csv='\uFEFF'+rows.map(r=>r.map(quote).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`horse_${view}_${report.month.replaceAll(/[^0-9a-z]+/gi,'_')}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
updateFilter();draw();
</script></body></html>'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database', default='data/racing_history.sqlite', type=Path,
                   help='Main racing_history.sqlite file, NOT .sqlite-wal')
    p.add_argument('--output', default='data/horse_results.html', type=Path)
    p.add_argument('--month', help='Optional YYYY-MM limit, e.g. 2022-01')
    a = p.parse_args()
    if a.month:
        parse_month(a.month)
    try:
        result = generate(a.database, a.output, a.month)
    except (FileNotFoundError, ValueError, sqlite3.Error, OSError) as err:
        print(f'ERROR: {err}', file=sys.stderr)
        return 2
    print('HTML report created successfully:')
    for k, v in result.items():
        print(f'  {k}: {v}')
    print('Double-click the HTML file to open it in Edge or Chrome. Your database remains unchanged.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
