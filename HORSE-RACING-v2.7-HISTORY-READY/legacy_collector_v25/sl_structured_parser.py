#!/usr/bin/env python3
"""Document-order Sporting Life runner parser.

Crucial: never divide the full text at '2nd', '3rd', etc. Those words occur
inside running comments. Boundaries are horse profile links and result labels
immediately before them. Fail with QA flags if a record is ambiguous.
"""
from __future__ import annotations
import re
import hashlib
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
from sporting_life_results_pilot import BASE, HORSE_PATH, WEIGHT, COMMENT_START, clean

POS = re.compile(r'^(?P<place>\d{1,2})\s*(?:st|nd|rd|th)\b\s*(?P<rest>.*)$', re.I)
STATE = re.compile(r'^(?P<state>PU|P|F|B|BD|UR|U|R|RO|RR|DSQ|DNF|SU|SL|VOID|NR)\b\s*(?P<rest>.*)$', re.I)
STATUS = {'P':'pulled_up','PU':'pulled_up','F':'fell','B':'brought_down','BD':'brought_down',
          'UR':'unseated_rider','U':'unseated_rider','R':'refused','RO':'ran_out',
          'RR':'refused','DSQ':'disqualified','DNF':'did_not_finish','SU':'slipped_up',
          'SL':'slipped_up','VOID':'void','NR':'non_runner'}
EXTRA_COMMENT_START = re.compile(r'\b(?:Fell|Brought down|Pulled up|Unseated|Refused|Ran out|Slipped up|Lost action|Collided)\b',re.I)
# Opening phrases describe how a horse began/ran. This is a grammar of
# race-comment starts, NOT a list of horses or specific race exceptions.
# Prefer a separate jockey/comment DOM field when available; this is fallback
# for flattened result text or archived text already in CSV.
COMMENT_OPENING = re.compile(
    r"(?i)\b(?:"
    r"mid[- ]division|not\s+always\s+fluent|towards\s+(?:the\s+)?rear|"
    r"in\s+(?:the\s+)?rear|in\s+touch|in\s+mid[- ]division|"
    r"held\s+up|chased\s+(?:leaders?|winner)|prominent|"
    r"tracked\s+(?:leaders?|winner)|raced\s+(?:keenly|freely|wide|in)|"
    r"made\s+(?:all|most|progress)|always\s+(?:in|towards|behind|prominent)|"
    r"slowly\s+away|slow\s+to\s+break|dwelt|stumbled|"
    r"pressed\s+leader|led\b|soon\s+(?:led|held|towards|prominent|in)|"
    r"settled\s+|jumped\s+|waited\s+with|off\s+the\s+pace|"
    r"weakened|pushed\s+along|fell|pulled\s+up|brought\s+down|"
    r"unseated|refused|ran\s+out|slipped\s+up|hampered|"
    r"rear\s+of|on\s+touch|"
    r"not\s+fluent|mistake|kept\s+on|ridden|"
    r"""not\s+always\s+fluent"""
    r")\b"
)

PRICE = re.compile(r'^(?P<price>\d+\s*/\s*\d+[a-z]*|Evens|EVS|SP)\b\s*',re.I)
DRAW = re.compile(r'\((\d{1,2})\)\s*$')
SIDECODES = {'also ran','non-runners','non runners'}
END_MARKERS = ('Unlimited Replays','Betting Breakdown','Forecasts','Previous Winners','Prize Money')


def tokenize(html):
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style','nav','footer','noscript']): tag.decompose()
    result=[]
    for node in soup.descendants:
        if isinstance(node,Tag) and node.name=='a':
            mm=HORSE_PATH.search(urlparse(urljoin(BASE,node.get('href',''))).path)
            if mm:
                name=clean(node.get_text(' ',strip=True))
                if name: result.append(('horse',name,mm.group(1)))
        elif isinstance(node,NavigableString):
            if node.find_parent('a') and HORSE_PATH.search(urlparse(urljoin(BASE,node.find_parent('a').get('href',''))).path):
                continue
            v=clean(str(node))
            if v: result.append(('text',v,None))
    return result


def split_context(tokens):
    """Find the last explicit stable button before an anchor to avoid cutting comments."""
    joined=clean(' '.join(tokens))
    if 'My Stable' in joined:
        joined=joined.rsplit('My Stable',1)[-1].strip()
    return [joined] if joined else []


def runner_prefix(items):
    seg=clean(' '.join(items))
    seg=re.sub(r'^.*?\bAlso\s+Ran\b','',seg,flags=re.I).strip() if re.search(r'\bAlso\s+Ran\b',seg,re.I) else seg
    # First runner may follow 'Racecard Live Odds Result' in the page header.
    seg=re.sub(r'^.*?\bResult\b\s*(?=\d{1,2}\s*(?:st|nd|rd|th)\b)', '', seg,flags=re.I)
    m=POS.match(seg)
    if m: return int(m['place']), 'finished',str(m['place']),m['rest']
    m=STATE.match(seg)
    if m: return None,STATUS[m['state'].upper()],m['state'].upper(),m['rest']
    return None,None,None,seg


def tokenize_runner_data(after):
    """Only take material before first My Stable button; no next horse's rank."""
    texts=[]
    for t in after:
        if t[0]=='horse': break
        value=t[1]
        if value.lower()=='my stable' or 'My Stable' in value:
            prefix=value.split('My Stable',1)[0]
            if prefix: texts.append(prefix)
            break
        texts.append(value)
    return clean(' '.join(texts))


def parse_prefix(pre):
    """Position/margin/saddle/draw must appear just before horse anchor."""
    if not pre: return None,None,None,None,None,None
    # Match first result heading after prior stable button, never search a comment.
    place, status, rawcode, other=runner_prefix(pre)
    if status is None: return None,None,None,None,None,None
    draw= DRAW.search(other)
    drawval=int(draw.group(1)) if draw else None
    if draw: other=clean(other[:draw.start()])
    n=re.search(r'(?:^|\s)(\d{1,2})\s*$',other)
    saddle=int(n.group(1)) if n else None
    margin=clean(other[:n.start()]) if n else None
    return place,status,rawcode,saddle,drawval,(margin or None)


def fields_after_anchor(content):
    w=WEIGHT.search(content)
    age,stone,pound=(int(w.group(k)) for k in ('age','stone','pound')) if w else (None,None,None)
    rest=clean(content[w.end():]) if w else content
    price=PRICE.match(rest)
    odds=clean(price.group('price')) if price else None
    if price: rest=clean(rest[price.end():])
    # Only parse comments when T: and J: are present; do not guess.
    tm=re.search(r'\bT:\s*(.+?)\s+J:\s*(.+)$',rest,re.I)
    trainer=jockey=comment=comment_raw=None
    if tm:
        trainer=clean(tm[1]); jplus=clean(tm[2])
        # Most comments start with a racing-position phrase. Prefer that over
        # a later incidental expression such as 'not fluent 3rd' in the same
        # comment; otherwise jockey names wrongly absorb the first sentence.
        matches=[m for m in (COMMENT_OPENING.search(jplus),COMMENT_START.search(jplus),
                              EXTRA_COMMENT_START.search(jplus)) if m]
        cs=min(matches,key=lambda m:m.start()) if matches else None
        if cs:
            jockey=clean(jplus[:cs.start()]); comment_raw=clean(jplus[cs.start():])
            comment=clean(re.split(r'\s+(?:op|tchd)\s+\d+(?:/\d+)?',comment_raw,maxsplit=1,flags=re.I)[0])
        else:
            jockey=jplus
    return dict(age=age,weight_raw=f'{stone}-{pound}' if w else None,
                weight_lb=stone*14+pound if w else None, odds_raw=odds,
                trainer=trainer,jockey=jockey,comment=comment,comment_raw=comment_raw)


def parse_runner_records(html,url,race):
    tokens=tokenize(html)
    start=0
    for i,t in enumerate(tokens):
        if t[0]=='text' and 'Winning time:' in t[1]: start=i+1; break
    # No legitimate horse is extracted before the race results start.
    end=len(tokens)
    for i in range(start,len(tokens)):
        if tokens[i][0]=='text' and any(marker in tokens[i][1] for marker in END_MARKERS):
            end=i; break
    data=tokens[start:end]
    anchor_positions=[i for i,t in enumerate(data) if t[0]=='horse']
    output=[]; issues=[]; last_end=0; ids=set()
    for j,i in enumerate(anchor_positions):
        marker,horse,hid=data[i]
        if hid in ids:
            issues.append('duplicate_profile_anchor_'+hid)
            continue
        ids.add(hid)
        region=[x[1] for x in data[last_end:i] if x[0]=='text']
        pre=split_context(region)
        try:
            pos,status,code,saddle,draw,margin=parse_prefix(pre)
        except Exception:
            pos=status=code=saddle=draw=margin=None
        if status is None:
            issues.append('unmatched_horse_'+hid)
            last_end=i+1
            continue
        next_anchor=anchor_positions[j+1] if j+1<len(anchor_positions) else end-start
        detail=tokenize_runner_data(data[i+1:next_anchor])
        info=fields_after_anchor(detail)
        record={'date':race['date'],'race_id':race['race_id'],'track':race['track'],
                'horse_id':hid,'horse':horse,'position':pos,'status':status,
                'status_raw':code,'saddlecloth':saddle,'draw':draw,
                'margin_from_preceding':margin if status=='finished' and pos!=1 else None,
                'age':info['age'],'weight_raw':info['weight_raw'],'weight_lb':info['weight_lb'],
                'odds_raw':info['odds_raw'],'trainer':info['trainer'],
                'jockey':info['jockey'],'comment':info['comment'],
                'comment_raw':info['comment_raw'], 'runner_text_raw':detail,'url':url,
                'identity_source':'horse_profile'}
        output.append(record)
        last_end=i+1
    # Non-runners can be text-only rather than horse-profile anchors.
    # Their IDs are explicitly synthetic, race-scoped; never conflate with profile IDs.
    section=[]; in_nr=False
    for t in tokens:
        if t[0]=='text' and re.search(r'\bNon[- ]Runners\b',t[1],re.I):
            in_nr=True
            continue
        if in_nr and t[0]=='text' and any(k in t[1] for k in ('Betting Breakdown','Forecasts','Previous Winners')):
            break
        if in_nr: section.append(t)
    nr_blocks=[]; block=[]
    for token in section:
        block.append(token)
        if token[0]=='text' and re.fullmatch(r'NR',token[1],re.I):
            nr_blocks.append(block); block=[]
    if block and any('Weight:' in x[1] for x in block): issues.append('non_runner_unclosed_record')
    names_in_output={r['horse'].casefold() for r in output}
    for n, blk in enumerate(nr_blocks):
        raw=clean(' '.join(t[1] for t in blk if t[0]=='text'))
        w=re.search(r'\bWeight:\s*(\d{1,2})-(\d{1,2})\s*\|?\s*Age:\s*(\d{1,2})\b',raw,re.I)
        if not w:
            issues.append('unparsed_non_runner_'+str(n+1)); continue
        head=clean(raw[:w.start()]); saddle_match=re.match(r'^(\d{1,2})\s+',head)
        saddle=int(saddle_match[1]) if saddle_match else None
        if saddle_match: head=clean(head[saddle_match.end():])
        # Some pages append a superscript form statistic after the horse name.
        head=re.sub(r'\s+\d{1,4}$','',head)
        horse=head.strip()
        if not horse:
            issues.append('non_runner_without_name_'+str(n+1)); continue
        if horse.casefold() in names_in_output: continue
        name_slug=re.sub(r'[^a-z0-9]+','-',horse.lower()).strip('-')
        synthetic_id='NR-'+hashlib.sha256((race['race_id']+'|'+name_slug).encode()).hexdigest()[:12]
        tr=re.search(r'\bT:\s*(.+?)\s+J:\s*(.+?)\s*NR\b',raw,re.I)
        runner={'date':race['date'],'race_id':race['race_id'],'track':race['track'],
                'horse_id':synthetic_id,'horse':horse,'position':None,'status':'non_runner',
                'status_raw':'NR','saddlecloth':saddle,'draw':None,'margin_from_preceding':None,
                'age':int(w[3]),'weight_raw':w[1]+'-'+w[2],
                'weight_lb':int(w[1])*14+int(w[2]),'odds_raw':None,
                'trainer':clean(tr[1]) if tr else None,'jockey':clean(tr[2]) if tr else None,
                'comment':None,'comment_raw':None,'runner_text_raw':raw,'url':url,
                'identity_source':'non_runner_name_only_synthetic_id'}
        output.append(runner); names_in_output.add(horse.casefold())
    if not output: issues.append('no_runner_rows_recognised')
    return output,issues
