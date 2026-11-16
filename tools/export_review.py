r"""Read-only export of results + sectionals to CSV/Excel for review. Usage: py tools\export_review.py [YYYY-MM sample month]"""
import sqlite3, json, re, sys, csv
from fractions import Fraction
from pathlib import Path
from datetime import date
import pandas as pd

SAMPLE = sys.argv[1] if len(sys.argv) > 1 else '2023-10'
OUT = Path('data/exports') / f'review_{date.today():%Y%m%d}'
OUT.mkdir(parents=True, exist_ok=True)

def dec(o):
    """fractional odds text -> decimal odds (incl. stake)."""
    if o is None: return None
    t = str(o).strip().lower().rstrip('fjc ').strip()
    if t in ('evs', 'evens', 'ev'): return 2.0
    m = re.fullmatch(r'(\d+)\s*/\s*(\d+)', t)
    return round(float(Fraction(int(m[1]), int(m[2]))) + 1, 3) if m else None

ODDS = r'(\d+/\d+|evs|evens)'
def moves(text):
    t = text.lower() if isinstance(text, str) else ''
    op = re.search(r'\bop\s+' + ODDS, t)
    tchd = re.findall(r'\btchd\s+' + ODDS + r'(?:\s+(?:and|&)\s+' + ODDS + r')?', t)
    touched = [x for pair in tchd for x in pair if x]
    return (op[1] if op else None), touched

def key_course(name):
    return re.split(r'[^a-z]+', name.lower().strip())[0] if isinstance(name, str) else ''
def key_horse(name):
    return re.sub(r'[^a-z]', '', re.sub(r'\(.*?\)', '', name.lower())) if isinstance(name, str) else ''

# ---------- results ----------
c = sqlite3.connect('file:data/racing_history.sqlite?mode=ro', uri=True)
races = pd.DataFrame([json.loads(d) for (d,) in c.execute('select data from races')])
runners = pd.DataFrame([json.loads(d) for (d,) in c.execute('select data from runners')])
rcols = ['date','race_id','track','scheduled_time','actual_off_time','race_name','race_type','surface','class',
         'distance_raw','distance_yards','going','actual_runners','winning_time_raw','winning_time_seconds',
         'status','qa_status','qa_flags','url']
races = races[[x for x in rcols if x in races]].sort_values(['date','track','scheduled_time'])

op_tchd = runners['comment_raw'].apply(moves)
runners['sp'] = runners['odds_raw']
runners['sp_decimal'] = runners['odds_raw'].apply(dec)
runners['open_price'] = op_tchd.str[0]
runners['open_decimal'] = runners['open_price'].apply(dec)
runners['touched_prices'] = op_tchd.str[1].apply(lambda l: ' | '.join(l))
runners['touched_decimals'] = op_tchd.str[1].apply(lambda l: ' | '.join(str(dec(x)) for x in l))
runners['open_to_sp_move_pct'] = ((runners['sp_decimal'] - runners['open_decimal']) / runners['open_decimal'] * 100).round(1)
runners['market_move'] = pd.cut(runners['open_to_sp_move_pct'], [-1000, -0.01, 0.01, 1e9], labels=['shortened (backed)', 'unchanged', 'drifted'])
runners['won'] = (runners['position'] == 1).astype(int)

import unicodedata
WORDS = {'dht':0.0,'nse':0.05,'sh':0.1,'shd':0.1,'hd':0.2,'snk':0.25,'nk':0.3,'dist':30.0,'dis':30.0}
def margin_len(m):
    """Sporting Life margin text -> lengths ('hd'=0.2, '1 ½'=1.5, '¾'=0.75)."""
    if not isinstance(m, str) or not m.strip(): return None
    t = m.strip().lower().replace('l', '')
    if t in WORDS: return WORDS[t]
    tot = 0.0; num = ''
    for ch in t:
        if ch.isdigit() or ch == '.': num += ch
        elif ch == '/' : num += ch
        elif unicodedata.numeric(ch, None) is not None and not ch.isdigit():
            tot += unicodedata.numeric(ch)
        elif ch.isspace():
            if num: tot += eval_num(num); num = ''
        else: return None
    if num: tot += eval_num(num)
    return round(tot, 3)
def eval_num(n):
    if '/' in n:
        a, b = n.split('/', 1); return float(a) / float(b)
    return float(n)

runners['margin_lengths'] = runners['margin_from_preceding'].apply(margin_len)
def beaten(g):
    g = g.sort_values('position')
    fin = g['position'].notna() & (g['status'] == 'finished')
    out = pd.Series(index=g.index, dtype='float64'); run = 0.0; ok = True
    for i, row in g[fin].iterrows():
        if row['position'] == 1: out[i] = 0.0; run = 0.0; continue
        ml = row['margin_lengths']
        if ml is None or pd.isna(ml): ok = False
        if ok: run += ml; out[i] = round(run, 3)
    return out
runners['beaten_lengths_from_winner'] = runners.groupby('race_id', group_keys=False)[['position','status','margin_lengths']].apply(beaten)

meta = races[['race_id','scheduled_time','race_type','class','distance_raw','distance_yards','going','actual_runners','winning_time_raw','winning_time_seconds']]
runners = runners.merge(meta, on='race_id', how='left')
ucols = ['date','track','scheduled_time','race_id','race_type','class','distance_yards','going','actual_runners',
         'horse','horse_id','position','won','status','winning_time_raw','winning_time_seconds','margin_from_preceding','margin_lengths','beaten_lengths_from_winner','distance_raw','saddlecloth','draw','age','weight_lb','trainer','jockey',
         'sp','sp_decimal','open_price','open_decimal','touched_prices','touched_decimals','open_to_sp_move_pct','market_move',
         'comment','comment_raw']
runners = runners[[x for x in ucols if x in runners]].sort_values(['date','track','scheduled_time','position'], na_position='last')

# ---------- sectionals ----------
s = sqlite3.connect('file:data/sectionals.sqlite?mode=ro', uri=True)
srace = pd.read_sql('select * from rtv_races', s)
srun = pd.read_sql('select * from rtv_runners', s)
iq = pd.read_sql("select rtv_race_id, rtv_runner_id, metric_group||'_'||metric m, value from rtv_raceiq where metric_group in ('race_metrics','speed','stride')", s)
iq = iq.pivot_table(index=['rtv_race_id','rtv_runner_id'], columns='m', values='value').reset_index()
srun = srun.merge(iq, on=['rtv_race_id','rtv_runner_id'], how='left').merge(
    srace[['rtv_race_id','race_date','course','off_time','race_name','race_type','race_class','distance_text','distance_yards','going','runner_count','winner_time_s','win_time_vs_par','has_sectionals']],
    on='rtv_race_id', how='left')

# ---------- link sectionals -> results (date + course + off time, then horse name) ----------
races['_k'] = races['date'] + '|' + races['track'].map(key_course) + '|' + races['scheduled_time'].fillna('')
srace['_k'] = srace['race_date'] + '|' + srace['course'].map(key_course) + '|' + srace['off_time'].fillna('')
link = srace[['rtv_race_id','_k']].merge(races[['race_id','_k']], on='_k', how='left')
srun = srun.merge(link[['rtv_race_id','race_id']], on='rtv_race_id', how='left')
srun['_h'] = srun['horse_name'].map(key_horse)
runners['_h'] = runners['horse'].map(key_horse)
srun = srun.merge(runners[['race_id','_h','horse_id','sp','sp_decimal','open_decimal','open_to_sp_move_pct']], on=['race_id','_h'], how='left').drop(columns='_h')
runners = runners.drop(columns='_h')
lead = ['race_date','course','off_time','race_id','rtv_race_id','race_type','race_class','distance_text','going','horse_name','horse_id',
        'finish_position','sp','sp_decimal','open_decimal','open_to_sp_move_pct','finishing_time_s','total_time_s','finishing_speed_pct']
srun = srun[lead + [x for x in srun.columns if x not in lead]].sort_values(['race_date','course','off_time','finish_position'], na_position='last')

# ---------- data check ----------
races['month'] = races['date'].str[:7]
runners['month'] = runners['date'].str[:7]
srace['month'] = srace['race_date'].str[:7]
srun['month'] = srun['race_date'].str[:7]
chk = (races.groupby('month').agg(results_races=('race_id','count'), race_days=('date','nunique'),
                                  qa_review=('qa_status', lambda x: (x=='review').sum()))
       .join(runners.groupby('month').agg(results_runners=('horse','count'),
                                          sp_found_pct=('sp_decimal', lambda x: round(x.notna().mean()*100,1)),
                                          open_price_found_pct=('open_decimal', lambda x: round(x.notna().mean()*100,1)),
                                          winning_time_found_pct=('winning_time_seconds', lambda x: round(x.notna().mean()*100,1))), how='outer')
       .join(srace.groupby('month').agg(sectional_races=('rtv_race_id','count'), with_sectionals=('has_sectionals','sum')), how='outer')
       .join(srun.groupby('month').agg(sectional_runners_linked_to_results_pct=('race_id', lambda x: round(x.notna().mean()*100,1))), how='outer')
       .reset_index())
for df in (races, runners, srun): df.drop(columns='month', inplace=True)
races = races.drop(columns='_k')

# ---------- write ----------
races.to_csv(OUT/'results_races.csv', index=False, encoding='utf-8-sig')
runners.to_csv(OUT/'results_runners_with_odds.csv', index=False, encoding='utf-8-sig')
srun.to_csv(OUT/'sectionals_runners.csv', index=False, encoding='utf-8-sig')
chk.to_csv(OUT/'data_check_by_month.csv', index=False, encoding='utf-8-sig')
xl = OUT / f'REVIEW_{SAMPLE}.xlsx'
with pd.ExcelWriter(xl, engine='openpyxl') as w:
    chk.to_excel(w, sheet_name='Data check by month', index=False)
    races[races['date'].str.startswith(SAMPLE)].to_excel(w, sheet_name=f'Races {SAMPLE}', index=False)
    runners[runners['date'].str.startswith(SAMPLE)].to_excel(w, sheet_name=f'Runners+odds {SAMPLE}', index=False)
    srun[srun['race_date'].fillna('').str.startswith(SAMPLE)].to_excel(w, sheet_name=f'Sectionals {SAMPLE}', index=False)
    for ws in w.book.worksheets:
        ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(max(len(str(col[0].value or '')) + 2, 10), 40)
print('OUT', OUT.resolve())
print('results races', len(races), 'runners', len(runners), 'sectional runners', len(srun))
print('sp found %', round(runners['sp_decimal'].notna().mean()*100,1), 'open found %', round(runners['open_decimal'].notna().mean()*100,1))
print('sectional runners linked to results % (overlap months only):',
      round(srun.loc[srun['race_date']>='2023-03-01','race_id'].notna().mean()*100,1),
      'horse matched %', round(srun.loc[srun['race_id'].notna(),'horse_id'].notna().mean()*100,1))
print(chk.tail(40).to_string())


