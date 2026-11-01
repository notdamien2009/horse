"""Regression fixtures: racing positions vs running comments, F/B/PU/NR, margins, time."""
import unittest
from sl_history import parse_race, enhance, numeric_margin

URL='https://www.sportinglife.com/racing/results/2022-10-21/cheltenham/708999/example-chase'
HTML='''<html><body><main>
<div>14:10 Cheltenham</div><h1>Example Chase</h1>
<div>4YO plus | Class 2 | 1m 7f 199y | Good | 6 Runners | Turf | Weighed In</div>
<div>Off time: 14:10 | Winning time: 3m 58.90s</div>
<div>Racecard Live Odds Result</div>
<article><div>1<sup>st</sup></div>6 <a href="/racing/profiles/horse/101">Winner</a>
7 11-9 5/2 T: First Trainer J: First Rider Chased leaders, went 2nd 2 out, led flat, stayed on My Stable</article>
<article><div>2<sup>nd</sup></div>nk 1 <a href="/racing/profiles/horse/102">Second</a>
6 11-12 3/1 T: Second Trainer J: Second Rider Not fluent 3rd, ridden, finished strongly op 4/1 My Stable</article>
<article><div>3<sup>rd</sup></div>3 ¼ 3 <a href="/racing/profiles/horse/103">Third</a>
8 11-4 4/1 T: Third Trainer J: Third Rider Made progress before 5th and went 3rd late My Stable</article>
<h3>Also Ran</h3>
<article>F 4 <a href="/racing/profiles/horse/104">Faller</a>
7 11-2 16/1 T: Trainer Four J: Rider Four Fell at last when challenging My Stable</article>
<article>B 5 <a href="/racing/profiles/horse/105">Brought Down</a>
7 11-2 16/1 T: Trainer Five J: Rider Five Brought down near finish My Stable</article>
<article>PU 7 <a href="/racing/profiles/horse/106">Pulled Up</a>
8 11-0 33/1 T: Trainer Six J: Rider Six Held up, weakened before 4 out My Stable</article>
<h4>Unlimited Replays</h4>
<h3>Non-Runners</h3><div>9</div><div>Did Not Start</div><span>19</span>
<div>Weight: 11-9 | Age: 6</div><div>T: Non Runner Trainer J: Non Runner Jockey</div><div>NR</div>
<h3>Betting Breakdown</h3>
</main></body></html>'''

class Accuracy(unittest.TestCase):
    def test_complete(self):
        race, runners = parse_race(HTML, URL)
        race, runners=enhance(race,runners,{'listed_time':'14:10'})
        assert len(runners)==7, runners
        assert [r['horse'] for r in runners[:3]]==['Winner','Second','Third']
        assert [r['status'] for r in runners[:3]]==['finished']*3
        assert [r['position'] for r in runners[:3]]==[1,2,3]
        assert [r['cumulative_beaten_lengths'] for r in runners[:3]]==[0,0.01,3.26]
        assert [r['legacy_win_time_plus_dist'] for r in runners[:3]]==[238.9,238.91,242.16]
        assert {r['horse']:r['status'] for r in runners[3:]}=={
            'Faller':'fell','Brought Down':'brought_down',
            'Pulled Up':'pulled_up','Did Not Start':'non_runner'}
        assert all(r['legacy_win_time_plus_dist'] is None for r in runners[3:])
        assert 'went 2nd 2 out' in runners[0]['comment']
        assert 'Not fluent 3rd' in runners[1]['comment']
        assert 'went 3rd late' in runners[2]['comment']
        assert race['actual_runners']==6 and race['finishers_captured']==3 and race['nonfinishers_captured']==3 and race['nonrunners_captured']==1
        assert race['qa_status']=='parsed_not_verified',race['qa_flags']
    def test_comment_opening_before_mid_sentence_incident(self):
        from sl_structured_parser import fields_after_anchor
        sample=("6 10-10 16/1 T: J C McConnell J: Kieren Buckley "
                "Mid-division on inside, outpaced from 2 out, "
                "well held when not fluent last op 12/1")
        got=fields_after_anchor(sample)
        assert got['jockey']=='Kieren Buckley'
        assert got['comment'].startswith('Mid-division on inside,')
        assert got['comment'].endswith('not fluent last')

    def test_finish_order_independent_of_input(self):
        from sl_history import runner_sort_key
        values=[{'status':'finished','position':4,'horse':'D'},
                {'status':'pulled_up','position':None,'horse':'E'},
                {'status':'finished','position':2,'horse':'B'},
                {'status':'finished','position':1,'horse':'A'},
                {'status':'non_runner','position':None,'horse':'F'},
                {'status':'finished','position':3,'horse':'C'}]
        values.sort(key=runner_sort_key)
        assert [x['horse'] for x in values]==['A','B','C','D','E','F']

    def test_qa_not_falsely_failed_by_source_order(self):
        # Newmarket 944565 demonstrated an input order like 4,3,5,6,1,2.
        # The source DOM order must NOT itself be a critical QA error.
        race=dict(race_id='QA-SOURCE-ORDER',date='2026-10-21',track='Newmarket',
            race_name='Example',status='weighed_in',winning_time_seconds=120.0,
            distance_yards=2200,going='Soft',surface='Turf',scheduled_time='15:35',
            actual_off_time='15:36',declared_runners=6,warnings='')
        runners=[dict(race_id='QA-SOURCE-ORDER',horse_id=str(pos),horse=f'Horse {pos}',
            position=pos,status='finished',weight_lb=126,comment='Ran throughout',
            margin_from_preceding='nk' if pos>1 else None)
            for pos in (4,3,5,6,1,2)]
        got, runners=enhance(race,runners,{'listed_time':'15:35'})
        assert 'finish_order_gap_or_duplicate' not in got['qa_flags'],got['qa_flags']
        assert [r['position'] for r in runners]==[1,2,3,4,5,6]
        assert runners[-1]['cumulative_beaten_lengths']==0.05

    def test_margins(self):
        assert numeric_margin('nk') == 0.01
        assert numeric_margin('1 ½') == 1.5
        assert numeric_margin('2 ¼') == 2.25
        assert numeric_margin('hd') is None # no assumed conversion
        assert numeric_margin('') is None

if __name__=='__main__': unittest.main(verbosity=2)

