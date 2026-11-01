#!/usr/bin/env python3
"""Small, transparent Sporting Life results extraction *pilot*.

Requires: pip install requests beautifulsoup4

This script reads public HTML without logins, stealth, CAPTCHA solving or proxies.
Sporting Life's published terms expressly prohibit scraping; run HTTP mode
only if you have permission for your intended collection. Offline HTML mode
works with independently supplied HTML and does not contact the website.

Usage:
  python sporting_life_results_pilot.py --self-test
  python sporting_life_results_pilot.py --date 2026-10-21 --max-races 3
  python sporting_life_results_pilot.py --html-dir exported_pages --date 2026-10-21
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit('Install requirements: python -m pip install requests beautifulsoup4') from exc

BASE = 'https://www.sportinglife.com'
DAY_PATH = '/racing/results'
RESULT_PATH = re.compile(r'^/racing/results/(?P<day>\d{4}-\d{2}-\d{2})/(?P<course>[a-z0-9-]+)/(?P<id>\d+)/(?P<slug>[^/?#]+)$')
HORSE_PATH = re.compile(r'/racing/profiles/horse/(\d+)(?:/|$)')
PLACE = re.compile(r'(?<!\w)(\d{1,2})\s*(?:st|nd|rd|th)\b', re.I)
WEIGHT = re.compile(r'\b(?P<age>\d{1,2})\s+(?P<stone>\d{1,2})-(?P<pound>\d{1,2})\b')
TIME = re.compile(r'\bWinning\s+time\s*:\s*((?:\d+m\s*)?\d+(?:\.\d+)?s|\-)', re.I)
DISTANCE = re.compile(r'\b(?:\d+m(?:\s+\d+f)?(?:\s+\d+y)?|\d+f(?:\s+\d+y)?)\b', re.I)
COMMENT_START = re.compile(
    r'\b(?:Towards rear|Rear of midfield|In rear|In touch|Midfield|Prominent|'
    r'Made all|Held up|Chased|Tracked|Raced|Went|Led|Slowly away|'
    r'Stumbled|Dwelt|Keen|Always|Jumped|Hampered|Close up|Pressed|'
    r'Steadied|Not fluent|Bumped|Waited|Soon|Settled|Pushed along|'
    r'Reared|Missed break|Broke well|Slightly slow|Slowly into stride|'
    r'Sat|Squeezed|Wore hood|Off the pace|Towards the rear|Ridden)\b', re.I)
RACE_FIELDS = ['date','race_id','track','race_name','scheduled_time','actual_off_time',
               'distance_raw','distance_yards','class','going','surface','race_type',
               'declared_runners','winning_time_raw','winning_time_seconds','status','url','warnings']
RUNNER_FIELDS = ['date','race_id','track','horse_id','horse','position','status',
                 'saddlecloth','draw','margin_from_preceding','age','weight_raw',
                 'weight_lb','odds_raw','trainer','jockey','comment','comment_raw',
                 'runner_text_raw','url']


def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s.replace('\u00a0', ' ')).strip()


def time_seconds(s: str):
    if not s or s == '-':
        return None
    m = re.fullmatch(r'(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s', clean(s))
    return round(60 * int(m.group(1) or 0) + float(m.group(2)), 2) if m else None


def yards(s: str):
    parts = dict((unit, int(number)) for number, unit in re.findall(r'(\d+)\s*([mfy])', s or ''))
    if not parts:
        return None
    return parts.get('m', 0)*1760 + parts.get('f', 0)*220 + parts.get('y', 0)


def race_links(html: str, day: str):
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    for a in soup.select('a[href]'):
        u = urljoin(BASE, a.get('href', ''))
        pu = urlparse(u)
        if pu.netloc not in {'www.sportinglife.com', 'sportinglife.com'}:
            continue
        m = RESULT_PATH.fullmatch(pu.path)
        if m and m.group('day') == day:
            result[m.group('id')] = u
    return list(result.values())


def race_type(name: str):
    text = name.lower()
    if 'hurdle' in text:
        return 'hurdle'
    if 'chase' in text or 'steeplechase' in text:
        return 'chase'
    if 'national hunt flat' in text or 'nh flat' in text or 'bumper' in text:
        return 'nh_flat'
    return 'flat'


def parse_race(html: str, url: str):
    u = urlparse(url)
    m = RESULT_PATH.fullmatch(u.path)
    if not m:
        raise ValueError('Not a Sporting Life dated result URL: ' + url)
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'noscript']):
        tag.decompose()
    full = clean(soup.get_text(' ', strip=True))
    h1 = soup.find('h1')
    name = clean(h1.get_text(' ', strip=True)) if h1 else ''
    # Header begins with a time + track, before the page's main title.
    marker = full.find(name) if name else -1
    after_title = full[marker + len(name):] if marker >= 0 else full
    header = after_title.split('Winning time:', 1)[0]
    pre = full[:marker] if marker >= 0 else ''
    scheduled = re.search(r'(\b\d\d?:\d\d)\s+' + re.escape(m.group('course').replace('-', ' ')), pre, re.I)
    actual_off = re.search(r'Off\s+time\s*:\s*(\d{1,2}:\d{2})', after_title, re.I)
    t = TIME.search(after_title)
    d = DISTANCE.search(header)
    declared = re.search(r'(\d+)\s+Runners\b', header, re.I)
    class_match = re.search(r'\bClass\s+(\d+)\b', header, re.I)
    surfaces = re.search(r'\b(Polytrack|Tapeta|Fibresand|Turf|Dirt|Synthetic)\b', header, re.I)
    going_list = ('Heavy', 'Soft', 'Good to Soft', 'Good', 'Good to Firm',
                  'Firm', 'Standard / Slow', 'Standard to Slow', 'Standard',
                  'Yielding to Soft', 'Yielding', 'Fast', 'Sloppy')
    # Choose first identifiable going phrase after distance, prioritising longer phrases.
    going = None
    if d:
        after_distance = header[d.end():]
        best = [re.search(r'\b' + re.escape(g) + r'\b', after_distance, re.I) for g in sorted(going_list, key=len, reverse=True)]
        matches = [(mm.start(), -len(g), g) for mm,g in zip(best, sorted(going_list, key=len, reverse=True)) if mm]
        if matches:
            going = sorted(matches)[0][2]
    warning = []
    wt = time_seconds(t.group(1)) if t else None
    if wt is None:
        warning.append('missing_winning_time')
    if 'Weighed In' not in header and 'weighed in' not in header.lower():
        warning.append('not_confirmed_weighed_in')
    if not d:
        warning.append('missing_distance')
    if not name:
        warning.append('missing_race_name')
    race = {
        'date':m.group('day'), 'race_id':m.group('id'),
        'track':m.group('course').replace('-', ' ').title(), 'race_name':name,
        'scheduled_time':scheduled.group(1) if scheduled else None,
        'actual_off_time':actual_off.group(1) if actual_off else None,
        'distance_raw':d.group(0) if d else None,
        'distance_yards':yards(d.group(0)) if d else None,
        'class':class_match.group(1) if class_match else None,
        'going':going, 'surface':surfaces.group(1) if surfaces else None,
        'race_type':race_type(name),
        'declared_runners':int(declared.group(1)) if declared else None,
        'winning_time_raw':t.group(1) if t else None, 'winning_time_seconds':wt,
        'status':'weighed_in' if 'weighed in' in header.lower() else 'unconfirmed',
        'url':url, 'warnings':'|'.join(warning),
    }

    # Restrict the segment scan to the results section, not previous winners.
    sec_start = after_title.find('Winning time:')
    body = after_title[sec_start:] if sec_start >= 0 else after_title
    place_start = PLACE.search(body)
    body = body[place_start.start():] if place_start else ''
    end = re.search(r'\b(?:Also Ran|Non[- ]Runners|Betting Breakdown|Unlimited Replays|Prize Money)\b',body,re.I)
    if end:
        body = body[:end.start()]
    # Horse-profile anchors provide horse names/IDs and eliminate guessing.
    horses = []
    for a in soup.select('a[href]'):
        link = urlparse(urljoin(BASE, a['href']))
        mm = HORSE_PATH.search(link.path)
        if mm:
            n = clean(a.get_text(' ', strip=True))
            if n and (n, mm.group(1)) not in horses:
                horses.append((n, mm.group(1)))
    runners = []
    starts = list(PLACE.finditer(body))
    for i, p in enumerate(starts):
        chunk = clean(body[p.end(): starts[i+1].start() if i+1 < len(starts) else len(body)])
        matches = [(chunk.find(hname), hname, hid) for hname,hid in horses if hname in chunk]
        matches = [(start,hname,hid) for start,hname,hid in matches if start >= 0]
        if not matches:
            warning.append('unmatched_runner_position_' + p.group(1))
            continue
        at, hname, hid = sorted(matches)[0]
        before, rest = clean(chunk[:at]), clean(chunk[at + len(hname):])
        w = WEIGHT.search(rest)
        age, stone, lb = (int(w.group(k)) for k in ('age','stone','pound')) if w else (None,None,None)
        after_weight = clean(rest[w.end():]) if w else rest
        # Remove the horse's odds but retain full raw text separately.
        price_match = re.match(r'^(\d+\s*/\s*\d+[a-z]*|Evens|EVS|SP)\b\s*', after_weight, re.I)
        price = clean(price_match.group(1)) if price_match else None
        data = clean(after_weight[price_match.end():]) if price_match else after_weight
        tm = re.search(r'\bT:\s*(.+?)\s+J:\s*(.+)$', data, re.I)
        trainer, jockey, comment, full_comment = None, None, None, None
        if tm:
            trainer = clean(tm.group(1))
            j_plus = clean(tm.group(2))
            cs = COMMENT_START.search(j_plus)
            if cs:
                jockey = clean(j_plus[:cs.start()])
                full_comment = clean(j_plus[cs.start():].split('My Stable',1)[0])
                comment = re.split(r'\s+(?:op|tchd)\s+\d+(?:/\d+)?',full_comment, maxsplit=1,flags=re.I)[0]
            else:
                # Do not invent a comment if separation is ambiguous.
                jockey = j_plus.split('My Stable',1)[0]
        short = before
        draw_match = re.search(r'\((\d+)\)\s*$', short)
        draw = int(draw_match.group(1)) if draw_match else None
        if draw_match:
            short = clean(short[:draw_match.start()])
        number_match = re.search(r'(\d+)\s*$', short)
        number = int(number_match.group(1)) if number_match else None
        margin = clean(short[:number_match.start()]) if number_match else None
        if not margin: margin = None
        runners.append({
            'date':m.group('day'),'race_id':m.group('id'), 'track':race['track'],
            'horse_id':hid,'horse':hname,'position':int(p.group(1)),'status':'finished',
            'saddlecloth':number,'draw':draw,'margin_from_preceding':margin,
            'age':age,'weight_raw':f'{stone}-{lb}' if w else None,
            'weight_lb':stone*14+lb if w else None,
            'odds_raw':price,'trainer':trainer,'jockey':jockey,'comment':comment,
            'comment_raw':full_comment,'runner_text_raw':chunk,'url':url,
        })
    if not runners:
        warning.append('no_runners_parsed')
    if race['declared_runners'] is not None and len(runners) < race['declared_runners']:
        warning.append(f'partial_results_{len(runners)}_of_{race["declared_runners"]}')
    race['warnings'] = '|'.join(dict.fromkeys(warning))
    return race, runners


def fetch(session, url):
    response = session.get(url, timeout=20)
    if response.status_code in (401,403,429):
        raise RuntimeError(f'Site returned HTTP {response.status_code}; stopping rather than evading access controls')
    response.raise_for_status()
    return response.text


def write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def run_self_test():
    day = '2026-10-21'
    race_url = BASE+'/racing/results/2026-10-21/newmarket/944562/example-race'
    index = f'<a href="{race_url}">13:50 Example Race</a>'
    assert race_links(index, day) == [race_url]
    fixture = '''<html><body><main><p>13:50 Newmarket</p><h1>Example Stakes</h1>
    <div>2YO only | Class 4 | 7f | Good to Soft | 2 Runners | Turf | Weighed In</div>
    <p>Off time: 13:51 | Winning time: 1m 28.36s</p><div>Racecard Live Odds Result</div>
    <section><span>1<sup>st</sup></span> 4 (8)
    <a href="/racing/profiles/horse/123">Horse A</a> 2 8-13 10/1 T: A Trainer J: C Lee
    Rear of midfield, ridden 2f out, led near finish op 9/1 My Stable</section>
    <section><span>2<sup>nd</sup></span> ¾ 6 (1)
    <a href="/racing/profiles/horse/124">Horse B</a> 2 8-13 8/13f T: B Trainer J: K Shoemark
    Went right start, led, headed near finish My Stable</section>
    <h3>Betting Breakdown</h3></main></body></html>'''
    race, runners = parse_race(fixture,race_url)
    assert race['winning_time_seconds'] == 88.36, race
    assert race['distance_yards'] == 1540, race
    assert len(runners) == 2, (race,runners)
    assert [r['horse'] for r in runners] == ['Horse A','Horse B'], runners
    assert [r['weight_lb'] for r in runners] == [125,125], runners
    assert [r['position'] for r in runners] == [1,2], runners
    assert runners[1]['margin_from_preceding'] == '¾', runners
    assert runners[0]['comment'].startswith('Rear of midfield'), runners
    assert race['going'].lower() == 'good to soft',race
    assert time_seconds('4m 55.80s') == 295.8
    assert yards('2m 3f 29y') == 4209
    print('PASS: 11 local checks on fictitious Sporting Life-shaped HTML (NO live site call)')


def main():
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--date',default=datetime.now(ZoneInfo('Europe/London')).date().isoformat(),
                        help='UK local race date, YYYY-MM-DD (default: today Europe/London)')
    parser.add_argument('--max-races',type=int,default=3,help='Maximum race pages to test, default 3; cap 10')
    parser.add_argument('--delay',type=float,default=4.0,help='Seconds between requests, minimum 3')
    parser.add_argument('--output-dir',type=Path,default=Path('sl_pilot_output'))
    parser.add_argument('--html-dir',type=Path,default=None,
                        help='Offline: directory with saved sportinglife HTML pages. Skips HTTP.')
    parser.add_argument('--race-url',type=str,default=None,
                        help='Test one exact dated Sporting Life result URL instead of the day listing')
    parser.add_argument('--self-test',action='store_true')
    args = parser.parse_args()
    if args.self_test:
        run_self_test(); return 0
    try:
        datetime.strptime(args.date,'%Y-%m-%d')
    except ValueError:
        parser.error('Date must be YYYY-MM-DD')
    if not 1 <= args.max_races <= 10:
        parser.error('--max-races must be between 1 and 10 for this pilot')
    if args.delay < 3:
        parser.error('--delay must be at least 3 seconds')
    if args.race_url:
        parsed = urlparse(args.race_url)
        mm = RESULT_PATH.fullmatch(parsed.path)
        if parsed.scheme != 'https' or parsed.netloc not in {'www.sportinglife.com','sportinglife.com'} or not mm:
            parser.error('--race-url must be an HTTPS Sporting Life dated result page')
        if mm.group('day') != args.date:
            parser.error('The --date must match the date in --race-url')
        if args.html_dir is not None:
            parser.error('Choose either --html-dir or --race-url, not both')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    race_pages=[]
    if args.html_dir is not None:
        day_files = list(args.html_dir.glob('day*.html'))
        if not day_files:
            parser.error('Offline directory requires day.html or day_*.html with result links')
        urls = race_links(day_files[0].read_text(encoding='utf-8'),args.date)[:args.max_races]
        for url in urls:
            race_id = RESULT_PATH.fullmatch(urlparse(url).path).group('id')
            path = args.html_dir / (race_id+'.html')
            if path.exists(): race_pages.append((url,path.read_text(encoding='utf-8')))
            else: print(f'WARNING: no offline race HTML for race {race_id}',file=sys.stderr)
    else:
        print('NOTE: Sporting Life prohibits scraping in its terms; use network mode only with permission.')
        session = requests.Session()
        session.headers.update({'User-Agent':'Horse-figures-research-pilot/0.1 (transparent single-day check)',
                                'Accept':'text/html,application/xhtml+xml'})
        today = datetime.now(ZoneInfo('Europe/London')).date().isoformat()
        index_url = BASE + (DAY_PATH if args.date == today else DAY_PATH+'/'+args.date)
        try:
            if args.race_url:
                urls = [args.race_url]
                print('Testing one specified race URL')
            else:
                listing = fetch(session,index_url)
                urls = race_links(listing,args.date)
                if not urls:
                    print('No matching race result links on day page. Site markup may have changed or results unavailable.')
                    return 2
                print(f'Found {len(urls)} dated race links; testing first {min(len(urls),args.max_races)}')
            for i,url in enumerate(urls[:args.max_races]):
                if i: time.sleep(args.delay)
                try:
                    race_pages.append((url,fetch(session,url)))
                except RuntimeError as e:
                    print(str(e),file=sys.stderr); break
                except requests.RequestException as e:
                    print(f'Cannot fetch {url}: {e}',file=sys.stderr)
        except (requests.RequestException,RuntimeError) as e:
            print(f'Network test failed: {e}',file=sys.stderr)
            return 2
    races,runners=[],[]
    for url,html in race_pages:
        try:
            race, rs = parse_race(html,url)
            races.append(race); runners.extend(rs)
            print(f'{race["track"]:<18} {race["race_id"]}  winner_time={race["winning_time_seconds"]}  '
                  f'finishers={len(rs)}  warnings={race["warnings"] or "none"}')
        except Exception as e:
            print(f'ERROR PARSING {url}: {e}',file=sys.stderr)
    if not races:
        print('No race data extracted; no result files written.',file=sys.stderr)
        return 2
    out = args.output_dir
    write_csv(out / f'races_{args.date}.csv', RACE_FIELDS, races)
    write_csv(out / f'runners_{args.date}.csv', RUNNER_FIELDS, runners)
    (out / f'audit_{args.date}.json').write_text(json.dumps({
        'date':args.date,'race_pages_parsed':len(races),'finishers_extracted':len(runners),
        'races_with_winning_time':sum(r['winning_time_seconds'] is not None for r in races),
        'races_with_comments':sum(any(h['comment'] for h in runners if h['race_id']==r['race_id']) for r in races),
        'races_with_warnings':[{'race_id':r['race_id'],'warnings':r['warnings']} for r in races if r['warnings']],
        'important_notes':['Finishing margins are versus the immediately preceding finisher, not cumulative.',
                           'Non-finishers and non-runners are not yet extracted in this pilot.',
                           'Comment splitting is heuristic; inspect comment_raw and runner_text_raw.',
                           'No speed figures or standard times are computed.']
    }, indent=2),encoding='utf-8')
    print('Saved:', out.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
