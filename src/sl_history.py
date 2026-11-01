#!/usr/bin/env python3
"""Sporting Life history *research* collector and importer.

Resumable one-source/date-range staging with SQLite, transparent HTTP, and local
HTML fixture mode. No login, CAPTCHA handling, fingerprint spoofing or proxies.
The site's published terms prohibit scraping; --live should only be used where
permission for the intended data collection has been obtained.

Original page parsing is imported from sporting_life_results_pilot.py.
"""
from __future__ import annotations

import argparse
import csv
from contextlib import closing
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

from sporting_life_results_pilot import (
    BASE, RESULT_PATH, RACE_FIELDS, RUNNER_FIELDS, clean,
    race_links, parse_race as legacy_header_parser, fetch,
)

INDEX_TIME = re.compile(r'^\s*(\d{1,2}:\d{2})\b')
BLOCKED_MARKERS = ('Client Challenge', 'Just a moment...', 'Attention Required!', 'Verify you are human', 'Access Denied')
EXTRA_RACE_FIELDS = ['actual_runners', 'finishers_captured', 'nonfinishers_captured', 'nonrunners_captured', 'standards_input_allowed', 'course_configuration', 'source', 'extracted_at_utc', 'qa_status', 'qa_flags']
EXTRA_RUNNER_FIELDS = ['status_raw', 'identity_source', 'margin_lengths_numeric', 'cumulative_beaten_lengths', 'win_dist_from_winner', 'legacy_win_time_plus_dist', 'time_adjustment_method', 'source', 'extracted_at_utc']
SOURCE = 'sportinglife'
from sl_structured_parser import parse_runner_records

def infer_surface_from_going(going, race_type):
    """Conservative broad classification, never a verified course surface.

    Standard going indicates All-Weather Flat racing, but does not identify
    the track material or the precise course configuration.
    """
    label = ' '.join(str(going or '').lower().replace('-', ' ').split())
    if str(race_type or '').lower() == 'flat' and label in {
        'standard', 'standard to slow', 'standard to fast'
    }:
        return 'All-Weather'
    return None

def parse_race(html, url):
    """Preserve prior race metadata, replace unreliable runner text splitting."""
    race, _ = legacy_header_parser(html, url)
    runners, errors = parse_runner_records(html, url, race)
    race['warnings'] = '|'.join(errors)
    return race, runners


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def check_access(html):
    head = html[:5000]
    if any(mark.lower() in head.lower() for mark in BLOCKED_MARKERS):
        raise AccessStopped('Access challenge/denial detected. Collection stopped; no bypass attempted.')


class AccessStopped(Exception):
    pass


def date_range(start, end, order='newest'):
    if order not in ('newest', 'oldest'):
        raise ValueError('order must be newest or oldest')
    current = end if order == 'newest' else start
    while (current >= start if order == 'newest' else current <= end):
        yield current.isoformat()
        current += timedelta(days=-1 if order == 'newest' else 1)


def parse_index(html, wanted_day):
    """Yield historical day links and scheduled off times from their text."""
    check_access(html)
    soup = BeautifulSoup(html, 'html.parser')
    seen = set()
    entries = []
    for a in soup.select('a[href]'):
        from urllib.parse import urljoin
        full_url = urljoin(BASE, a['href'])
        parsed = urlparse(full_url)
        if parsed.netloc not in ('www.sportinglife.com', 'sportinglife.com'):
            continue
        m = RESULT_PATH.fullmatch(parsed.path)
        if not m or m['day'] != wanted_day or m['id'] in seen:
            continue
        seen.add(m['id'])
        label = clean(a.get_text(' ', strip=True))
        start = INDEX_TIME.match(label)
        entries.append({'race_id': m['id'], 'date': wanted_day, 'url': full_url.split('#')[0],
                        'listed_time': start.group(1) if start else None,
                        'track': m['course'].replace('-', ' ').title(),
                        'listed_label': label})
    return entries


def numeric_margin(raw):
    """Only lengths with unambiguous numeric values. Head/nose conversions are NOT assumed."""
    if raw is None or str(raw).strip()=='':
        return None  # Unknown margin is NOT a dead heat
    raw = clean(raw).lower()
    if raw in ('dead heat', 'dh'):
        return 0.0
    if raw in ('nk', 'neck'):
        return 0.01  # User's historical racing-standard convention; not a physical length
    fractions = {'¼': 0.25, '½':0.5, '¾': 0.75, '⅛':0.125, '⅜':0.375, '⅝':0.625, '⅞':0.875}
    raw=re.sub(r'\s*(?:l|lengths?)$', '', raw).strip()
    if re.fullmatch(r'\d+(?:\.\d+)?',raw):
        return float(raw)
    m = re.fullmatch(r'(\d+)\s*([¼½¾⅛⅜⅝⅞])', raw)
    if m:
        return int(m[1]) + fractions[m[2]]
    if raw in fractions:
        return fractions[raw]
    m = re.fullmatch(r'(\d+)\s*/\s*(\d+)',raw)
    if m and int(m[2]):
        return float(Fraction(int(m[1]),int(m[2])))
    return None


def runner_sort_key(r):
    """Finishing positions first, then non-finishers, then non-runners.

    Stable across exports and reparses. Never assumes SQLite horse_id ordering
    equals finishing order. Position may be an int, float or CSV string.
    """
    status=r.get('status')
    if status=='finished':
        try: pos=int(float(r['position']))
        except (TypeError,ValueError): pos=10**7
        return (0,pos,str(r.get('horse') or '').casefold())
    return (2 if status=='non_runner' else 1,0,str(r.get('horse') or '').casefold())


def enhance(race, runners, listing):
    """Fill a known failure without changing historic parser's original raw values."""
    race = dict(race)
    runners = [dict(r) for r in runners]
    race['scheduled_time'] = listing.get('listed_time') or race.get('scheduled_time')
    race['actual_runners'] = race.get('declared_runners')
    # Page header Runners is the number who actually ran, not pre-declaration count.
    race['declared_runners'] = None
    race['source'] = SOURCE
    race['course_configuration'] = ''  # Deliberate: needs verified Rowley/July, etc.
    race['extracted_at_utc'] = utcnow()
    name = (race.get('race_name') or '').lower()
    if 'national hunt flat' in name or 'nh flat' in name or 'bumper' in name or 'flat race' in name:
        race['race_type'] = 'nh_flat'
    flags = []
    if not race.get('surface'):
        inferred = infer_surface_from_going(race.get('going'), race.get('race_type'))
        if inferred:
            race['surface'] = inferred
            flags.append('surface_inferred_from_going')
    time_seconds = race.get('winning_time_seconds')
    if not isinstance(time_seconds,(int,float)) or not 0 < time_seconds < 1200:
        flags.append('invalid_or_missing_winning_time')
    if not race.get('distance_yards') or race.get('distance_yards') < 220:
        flags.append('invalid_distance')
    if not race.get('going'):
        flags.append('missing_going')
    if not race.get('surface'):
        flags.append('missing_surface')
    if not race.get('scheduled_time'):
        flags.append('missing_scheduled_time')
    if race.get('status') != 'weighed_in':
        flags.append('not_confirmed_weighed_in')
    if not race.get('actual_off_time'):
        flags.append('missing_actual_off_time')
    starters = [r for r in runners if r.get('status')!='non_runner']
    finishers = [r for r in starters if r.get('status')=='finished']
    nonfinishers = [r for r in starters if r.get('status')!='finished']
    race['finishers_captured'] = len(finishers)
    race['nonfinishers_captured'] = len(nonfinishers)
    race['nonrunners_captured'] = len(runners)-len(starters)
    if not finishers:
        flags.append('no_finishers_parsed')
    if len(starters) != race.get('actual_runners'):
        flags.append('runner_count_mismatch')
    # DOM/source order is NOT necessarily official finishing order. Verify
    # unique, contiguous finishing positions without assuming input order.
    try:
        positions = sorted(int(r.get('position')) for r in finishers)
    except (TypeError, ValueError):
        positions = []
    if positions != list(range(1,len(finishers)+1)):
        flags.append('finish_order_gap_or_duplicate')
    if len({(r.get('race_id'),r.get('horse_id')) for r in runners}) != len(runners):
        flags.append('duplicate_horse_in_race')
    if any(not r.get('comment') for r in starters):
        flags.append('missing_running_comments')
    if any(r.get('weight_lb') is None for r in starters):
        flags.append('missing_runner_weight')
    # Sort by official result, not horse profile ID or source DOM order.
    # Non-finishers and non-runners follow finishers and never receive fake times.
    runners.sort(key=runner_sort_key)
    # Winner starts at zero. Mark cumulative as unavailable after any nonnumeric margin.
    cumulative = 0.0
    for r in runners:
        if r.get('status')=='finished':
            # A missing placing margin is UNKNOWN, never silently converted to zero.
            margin = 0.0 if r.get('position') == 1 else numeric_margin(r.get('margin_from_preceding'))
            r['margin_lengths_numeric'] = margin
            if cumulative is not None and margin is not None: cumulative += margin
            else: cumulative = None
            r['cumulative_beaten_lengths'] = round(cumulative,4) if cumulative is not None else None
        else:
            r['margin_lengths_numeric'] = None
            r['cumulative_beaten_lengths'] = None
        r['win_dist_from_winner'] = r['cumulative_beaten_lengths']
        # Deliberately preserve the user's old arithmetic, NOT a true clock time.
        r['legacy_win_time_plus_dist'] = (round(float(time_seconds)+r['cumulative_beaten_lengths'],4)
            if r['cumulative_beaten_lengths'] is not None and isinstance(time_seconds,(int,float)) else None)
        r['time_adjustment_method']='legacy_numeric_margin_added_to_seconds' if r['legacy_win_time_plus_dist'] is not None else None
        r['source'] = SOURCE
        r['extracted_at_utc'] = race['extracted_at_utc']
    if any(r['margin_lengths_numeric'] is None for r in finishers):
        flags.append('unconverted_symbolic_margins')
    for problem in filter(None,(race.get('warnings') or '').split('|')):
        if problem not in flags: flags.append(problem)
    # Restrict standards calculations until course configuration and going are audited.
    flags.append('course_configuration_unverified')
    race['qa_status'] = ('review' if any(x in flags for x in
        ('invalid_or_missing_winning_time','invalid_distance','missing_going','missing_surface',
         'no_finishers_parsed','runner_count_mismatch','finish_order_gap_or_duplicate','duplicate_horse_in_race',
         'not_confirmed_weighed_in','missing_running_comments','unconverted_symbolic_margins',
         'non_runner_text_only_not_captured','non_runner_unclosed_record','no_runner_rows_recognised'))
        or any(x.startswith('unmatched_horse_') or x.startswith('duplicate_profile_anchor_') for x in flags)
        else 'parsed_not_verified')
    race['qa_flags'] = '|'.join(flags)
    race['standards_input_allowed'] = False  # No standards until independent source verification and track configuration
    return race, runners


def db_open(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS days (
          race_date TEXT PRIMARY KEY, index_state TEXT NOT NULL,
          discovered INTEGER NOT NULL DEFAULT 0, last_error TEXT,
          indexed_utc TEXT);
        CREATE TABLE IF NOT EXISTS race_queue (
          race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL, url TEXT NOT NULL,
          listed_time TEXT, listed_label TEXT, track TEXT,
          status TEXT NOT NULL DEFAULT 'pending', last_error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
          updated_utc TEXT);
        CREATE INDEX IF NOT EXISTS ix_race_queue_day ON race_queue(race_date,status);
        CREATE TABLE IF NOT EXISTS races (race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runners (
          race_id TEXT NOT NULL, horse_id TEXT NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY (race_id,horse_id));
    ''')
    conn.commit()
    return conn


def register_index(conn, day, entries):
    with conn:
        conn.execute('INSERT INTO days(race_date,index_state,discovered,last_error,indexed_utc) '
                     'VALUES(?,?,?,?,?) ON CONFLICT(race_date) DO UPDATE SET '
                     'index_state=excluded.index_state, discovered=excluded.discovered, '
                     'last_error=NULL, indexed_utc=excluded.indexed_utc',
                     (day,'indexed',len(entries),None,utcnow()))
        for item in entries:
            conn.execute('''INSERT OR IGNORE INTO race_queue
                (race_id,race_date,url,listed_time,listed_label,track,status,updated_utc)
                VALUES(?,?,?,?,?,?,?,?)''',
                (item['race_id'],day,item['url'],item['listed_time'],item['listed_label'],
                 item['track'],'pending',utcnow()))


def save_race(conn, race, runners):
    with conn:
        conn.execute('INSERT INTO races (race_id,race_date,data) VALUES (?,?,?) ON CONFLICT(race_id) DO UPDATE SET '
                     'data=excluded.data, race_date=excluded.race_date',
                     (race['race_id'],race['date'],json.dumps(race,ensure_ascii=False)))
        conn.execute('DELETE FROM runners WHERE race_id=?', (race['race_id'],))
        for r in runners:
            if not r['horse_id']:
                raise ValueError('Runner without horse ID, refusing to store partial identity')
            conn.execute('INSERT INTO runners (race_id,horse_id,data) VALUES(?,?,?)',
                         (race['race_id'],r['horse_id'],json.dumps(r,ensure_ascii=False)))
        conn.execute('UPDATE race_queue SET status=?, last_error=NULL, attempts=attempts+1, updated_utc=? WHERE race_id=?',
                     ('parsed',utcnow(),race['race_id']))


def fail_race(conn, rid, err):
    with conn:
        conn.execute('UPDATE race_queue SET status=?,last_error=?,attempts=attempts+1,updated_utc=? WHERE race_id=?',
                     ('error',str(err)[:400],utcnow(),rid))


def fail_index(conn, day, err):
    with conn:
        conn.execute('INSERT INTO days(race_date,index_state,last_error) VALUES(?,?,?) '
                     'ON CONFLICT(race_date) DO UPDATE SET index_state=excluded.index_state,last_error=excluded.last_error',
                     (day,'error',str(err)[:400]))


def output_csv(file, fields, rows):
    with file.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)


def export_db(conn,out_dir):
    """Full CSV export is intentionally opt-in once the collection grows large."""
    out_dir.mkdir(parents=True,exist_ok=True)
    races_count = 0
    runners_count = 0
    time_missing = 0
    scheduled_missing = 0
    review_count = 0
    comments_missing = 0
    with (out_dir/'races_all.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f,fieldnames=RACE_FIELDS+EXTRA_RACE_FIELDS,extrasaction='ignore')
        writer.writeheader()
        for row in conn.execute('SELECT data FROM races ORDER BY race_date,race_id'):
            r=json.loads(row['data']); writer.writerow(r)
            races_count += 1
            if not r.get('winning_time_seconds'): time_missing += 1
            if not r.get('scheduled_time'): scheduled_missing += 1
            if r.get('qa_status')=='review': review_count += 1
    with (out_dir/'runners_all.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f,fieldnames=RUNNER_FIELDS+EXTRA_RUNNER_FIELDS,extrasaction='ignore')
        writer.writeheader()
        current_race=None
        race_group=[]
        def write_group(group):
            nonlocal runners_count,comments_missing
            for r in sorted(group,key=runner_sort_key):
                writer.writerow(r)
                runners_count+=1
                if r.get('status')!='non_runner' and not r.get('comment'):
                    comments_missing+=1
        for row in conn.execute('SELECT race_id,data FROM runners ORDER BY race_id'):
            if current_race is not None and row['race_id']!=current_race:
                write_group(race_group)
                race_group=[]
            current_race=row['race_id']
            race_group.append(json.loads(row['data']))
        if race_group: write_group(race_group)
    days=[dict(r) for r in conn.execute('SELECT * FROM days ORDER BY race_date DESC')]
    for d in days:
        q=conn.execute('SELECT status,count(*) as n FROM race_queue WHERE race_date=? GROUP BY status',(d['race_date'],))
        counts={r['status']:r['n'] for r in q}
        d.update({'parsed':counts.get('parsed',0),'pending':counts.get('pending',0),'errors':counts.get('error',0)})
        d['coverage']='complete' if d['discovered'] and d['parsed']==d['discovered'] else 'incomplete'
    output_csv(out_dir/'daily_coverage.csv',
               ['race_date','index_state','discovered','parsed','pending','errors','coverage','last_error','indexed_utc'],days)
    summary={
        'race_pages_parsed':races_count, 'runner_records':runners_count,
        'dates_indexed':sum(d['index_state']=='indexed' for d in days),
        'dates_complete':sum(d['coverage']=='complete' for d in days),
        'dates_incomplete':sum(d['coverage']!='complete' for d in days),
        'races_missing_winning_time':time_missing,
        'races_missing_scheduled_time':scheduled_missing,
        'races_with_review_flags':review_count,
        'runners_missing_comment':comments_missing,
        'important':'No course standard times computed. QA review races and unverified course configurations are not suitable as standards inputs.',
        'exported_utc':utcnow(),
    }
    (out_dir/'qa_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary


def quick_summary(conn):
    result={
        'race_pages_parsed':conn.execute('SELECT COUNT(*) FROM races').fetchone()[0],
        'runner_records':conn.execute('SELECT COUNT(*) FROM runners').fetchone()[0],
        'dates_indexed':conn.execute("SELECT COUNT(*) FROM days WHERE index_state='indexed'").fetchone()[0],
        'race_pages_pending':conn.execute("SELECT COUNT(*) FROM race_queue WHERE status='pending'").fetchone()[0],
        'race_pages_with_errors':conn.execute("SELECT COUNT(*) FROM race_queue WHERE status='error'").fetchone()[0],
        'csv_export':'Run --export-only for current full CSV files',
    }
    return result


def read_offline(path,day,race_id=None):
    dayfolder=path/day
    if not dayfolder.exists():
        dayfolder=path
    file=(dayfolder/f'{race_id}.html') if race_id else (dayfolder/'day.html')
    if not file.exists():
        raise FileNotFoundError(f'Offline page missing: {file}')
    return file.read_text(encoding='utf-8')


def collect(args):
    """Always release SQLite file handles, including on parser/export failures.

    Critical on Windows: open SQLite connections prevent TemporaryDirectory cleanup
    and may leave user database files locked after a failed run.
    """
    with closing(db_open(args.database)) as conn:
        return collect_with_connection(args, conn)


def collect_with_connection(args, conn):
    if args.export_only:
        print(json.dumps(export_db(conn,args.output_dir),indent=2)); return 0
    if not args.live and args.html_dir is None:
        raise SystemExit('Choose --html-dir for offline HTML or --live (only with collection permission).')
    if args.live and args.html_dir:
        raise SystemExit('Choose either --live or --html-dir, not both.')
    start=date.fromisoformat(args.from_date or args.date or '2022-01-01')
    end=date.fromisoformat(args.to_date or args.date or date.today().isoformat())
    if start>end:
        raise SystemExit('from-date must not be after to-date')
    if args.live and args.delay<3:
        raise SystemExit('--delay must be at least 3 seconds')
    session = None
    if args.live:
        print('NOTICE: Sporting Life prohibits scraping; use HTTP mode only with permission.')
        session=requests.Session()
        session.headers.update({'User-Agent':'HorseRacingStandardsResearch/0.2',
                                'Accept':'text/html,application/xhtml+xml'})
    day_count=0
    fetched=0
    stopped=False
    for day in date_range(start,end,args.date_order):
        if day_count>=args.max_days or fetched>=args.max_races or stopped:
            break
        existing=conn.execute('SELECT * FROM days WHERE race_date=?',(day,)).fetchone()
        if existing and existing['index_state']=='error' and not args.retry_errors:
            continue
        if existing is None or args.refresh_index:
            if day_count>=args.max_days: break
            try:
                if args.live:
                    html=fetch(session,BASE+'/racing/results/'+day)
                else:
                    html=read_offline(args.html_dir,day)
                check_access(html)
                links=parse_index(html,day)
                if not links:
                    raise ValueError('No race links; date could be empty or page layout could have changed. NOT marked complete.')
                register_index(conn,day,links)
                print(f'{day}: indexed {len(links)} race links')
                day_count+=1
                if args.live:
                    time.sleep(args.delay)
            except (RuntimeError,AccessStopped) as err:
                fail_index(conn,day,err); print(f'STOP {day}: {err}',file=sys.stderr); break
            except (requests.RequestException,FileNotFoundError,ValueError) as err:
                fail_index(conn,day,err); print(f'INDEX ERROR {day}: {err}',file=sys.stderr)
                day_count+=1
                continue
        else:
            pending=conn.execute('SELECT COUNT(*) FROM race_queue WHERE race_date=? AND status IN '+
                                 ("('pending','error')" if args.retry_errors else "('pending')"),(day,)).fetchone()[0]
            if pending==0 and not getattr(args,'reparse',False): continue
            day_count+=1
        if getattr(args,'reparse',False):
            queue=conn.execute("SELECT * FROM race_queue WHERE race_date=? ORDER BY rowid",(day,)).fetchall()
        elif args.retry_errors:
            queue=conn.execute("SELECT * FROM race_queue WHERE race_date=? AND status IN ('pending','error') ORDER BY rowid",(day,)).fetchall()
        else:
            queue=conn.execute("SELECT * FROM race_queue WHERE race_date=? AND status='pending' ORDER BY rowid",(day,)).fetchall()
        for item in queue:
            if fetched>=args.max_races: break
            try:
                if args.live:
                    html=fetch(session,item['url'])
                else:
                    html=read_offline(args.html_dir,day,item['race_id'])
                check_access(html)
                r, runners=parse_race(html,item['url'])
                r, runners=enhance(r,runners,dict(item))
                # Invalid/no finishers is a parser error, not a successful download.
                if not runners or r['qa_status']=='review' and not r.get('winning_time_seconds'):
                    raise ValueError('Race extraction incomplete, check page and recorded details')
                save_race(conn,r,runners)
                fetched+=1
                print(f'  {item["listed_time"] or "--:--"} {r["track"]:<16} {r["race_id"]}: '
                      f'{len(runners)} horse records, time={r["winning_time_seconds"]}, '
                      f'QA={r["qa_status"]}')
            except (AccessStopped,RuntimeError) as err:
                fail_race(conn,item['race_id'],err)
                print(f'STOP {item["race_id"]}: {err}',file=sys.stderr)
                stopped=True
                break
            except (Exception,) as err:
                fail_race(conn,item['race_id'],err)
                fetched+=1
                print(f'RACE ERROR {item["race_id"]}: {err}',file=sys.stderr)
            if args.live and not stopped:
                time.sleep(args.delay)
    number_of_races=conn.execute('SELECT COUNT(*) FROM races').fetchone()[0]
    summary=(export_db(conn,args.output_dir) if number_of_races <= args.auto_export_limit
             else quick_summary(conn))
    print('Database:',args.database.resolve())
    print('Exports:',args.output_dir.resolve(), '(automatic CSV export skipped on large collections)'
          if number_of_races > args.auto_export_limit else '')
    print('Summary:',json.dumps(summary,indent=2))
    return 2 if stopped else 0


def self_test():
    assert numeric_margin('¾')==0.75
    assert numeric_margin('4 ½')==4.5
    assert numeric_margin('3 ¼')==3.25
    assert numeric_margin('nk') == 0.01
    assert numeric_margin('') is None
    assert numeric_margin('sh') is None
    assert numeric_margin('hd') is None
    assert infer_surface_from_going('Standard','flat') == 'All-Weather'
    assert infer_surface_from_going('Standard to Slow','flat') == 'All-Weather'
    assert infer_surface_from_going('Good','flat') is None
    assert infer_surface_from_going('Standard','chase') is None
    assert list(date_range(date(2022,1,1),date(2022,1,3),'oldest')) == ['2022-01-01','2022-01-02','2022-01-03']
    assert list(date_range(date(2022,1,1),date(2022,1,3))) == ['2022-01-03','2022-01-02','2022-01-01']
    url=BASE+'/racing/results/2022-10-21/cheltenham/708998/example-race'
    entries=parse_index(f'<a href="{url}">13:35 Showcasing Sustainability Handicap Hurdle</a>','2022-10-21')
    assert len(entries)==1 and entries[0]['listed_time']=='13:35'
    r,hs=parse_race('''<main><div>13:35 Cheltenham</div><h1>Example Hurdle</h1>
        3YO plus | Class 3 | 2m 87y | Good | 2 Runners | Turf | Weighed In
        Off time: 13:36 | Winning time: 3m 57.61s
        <span>1<sup>st</sup></span> 4 <a href="/racing/profiles/horse/1234">Horse A</a>
        5 11-0 10/1 T: A Trainer J: A Rider Prominent, led near finish My Stable
        <span>2<sup>nd</sup></span> 3 ¼ 6 <a href="/racing/profiles/horse/1235">Horse B</a>
        5 10-12 8/1 T: B Trainer J: B Rider Held up, stayed on My Stable
        <h3>Betting Breakdown</h3></main>''',url)
    r,hs=enhance(r,hs,entries[0])
    assert r['scheduled_time']=='13:35'
    assert r['actual_runners']==2 and r['declared_runners'] is None
    assert r['winning_time_seconds']==237.61
    assert len(hs)==2 and hs[1]['margin_lengths_numeric']==3.25
    assert hs[1]['cumulative_beaten_lengths']==3.25
    assert hs[1]['legacy_win_time_plus_dist']==240.86
    assert r['race_type']=='hurdle'
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        with closing(db_open(root/'test.sqlite')) as conn:
            register_index(conn,'2022-10-21',entries)
            save_race(conn,r,hs)
            register_index(conn,'2022-10-21',entries)
            save_race(conn,r,hs)
            q=export_db(conn,root/'out')
            assert q['race_pages_parsed']==1 and q['runner_records']==2
            assert q['dates_complete']==1
        # DB is closed *before* TemporaryDirectory attempts to remove its files.
        # Particularly important on Windows (WinError 32 on test.sqlite).
    print('PASS: offline field, index, margin, SQLite upsert/resume and CSV QA tests.')


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--live',action='store_true',help='HTTP mode; requires permission for intended collection')
    parser.add_argument('--html-dir',type=Path,help='Locally held HTML directory for permitted offline importing')
    parser.add_argument('--date',help='Single day YYYY-MM-DD')
    parser.add_argument('--from-date',help='Start day YYYY-MM-DD; default 2022-01-01')
    parser.add_argument('--to-date',help='End day YYYY-MM-DD; default today')
    parser.add_argument('--max-days',type=int,default=1,help='Dates to process in one run (default 1)')
    parser.add_argument('--date-order',choices=('newest','oldest'),default='newest',
                        help='Calendar traversal; newest remains the legacy default')
    parser.add_argument('--max-races',type=int,default=3,help='Race pages to process in one run (default 3)')
    parser.add_argument('--delay',type=float,default=4,help='HTTP delay seconds (minimum 3)')
    parser.add_argument('--retry-errors',action='store_true',help='Retry previously failed records')
    parser.add_argument('--reparse',action='store_true',help='Reprocess existing parsed race IDs from available pages; use with --date and small --max-races during QA')
    parser.add_argument('--refresh-index',action='store_true',help='Re-read existing daily listings')
    parser.add_argument('--export-only',action='store_true',help='Export from database without connecting')
    parser.add_argument('--auto-export-limit',type=int,default=1000,
                        help='On collection, produce full CSVs only when database has <= N races. Default 1000.')
    parser.add_argument('--database',type=Path,default=Path('data')/'racing_history.sqlite')
    parser.add_argument('--output-dir',type=Path,default=Path('data')/'exports')
    args=parser.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.date and (args.from_date or args.to_date):
        parser.error('Use --date OR --from-date/--to-date')
    if args.max_days<1 or args.max_days>31 or args.max_races<1 or args.max_races>250:
        parser.error('max-days 1..31 and max-races 1..250')
    return collect(args)

if __name__=='__main__':
    raise SystemExit(main())
