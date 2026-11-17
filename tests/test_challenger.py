import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from argparse import Namespace
import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location('challenger', Path(__file__).resolve().parents[1] / 'tools/challenger_figures.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class ChallengerTests(unittest.TestCase):
    def test_clock_agreement_and_quarantine(self):
        a = {'win_time_official':70.0,'rtv_results_time':70.3,'sect_time':70.2}
        clock,flag=model.choose_clock(a)
        self.assertEqual(flag,'AGREED_PAIR')
        self.assertEqual(clock,70.3)
        self.assertEqual(model.choose_clock({'win_time_official':70.,'rtv_results_time':80.,'sect_time':90.})[1], 'DISPUTED_CLOCK')
        self.assertEqual(model.choose_clock({'win_time_official':'unknown','rtv_results_time':70.0})[1], 'SINGLE_rtv_results_time')

    def test_small_sample_quantile(self):
        self.assertAlmostEqual(model.robust_q(pd.Series([1,2,3,4,5]),.5),3.)

    def test_complete_pipeline_synthetic(self):
        rng = np.random.default_rng(123)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'data/speed_v4').mkdir(parents=True)
            fig,dc,sec_races,sec_runners,sec_splits = [],[],[],[],[]
            for i in range(400):
                date = (pd.Timestamp('2025-01-01')+pd.Timedelta(days=i//4)).date().isoformat()
                course = ['Course Alpha','Course Beta'][i%2]
                base = 73.5 if course=='Course Alpha' else 75.5
                t = base + rng.normal(0,0.6) + 0.3 * (i%4)
                key = f'R{i:04}'
                dc.append({'race_id':key,'rtv_race_id':i+1,'exact_yards':1320,'base_yards':1320,
                    'win_time_official':t,'rtv_results_time':t+0.02,'sect_time':t+0.04})
                sec_races.append((i+1,date,1320.0))
                # Horses recur, but finishing order varies: avoid a trivially perfect benchmark.
                horse_choices = rng.choice(70,size=5,replace=False)
                for j in range(5):
                    horse = f'Horse {horse_choices[j]:03d}'
                    runner_total = t + j * 0.65
                    eff_wt = 126.0
                    fig.append({'race_id':key,'horse':horse,'horse_id':horse,'place':j+1,'date':date,
                        'off_time':f'{12+i%5:02}:10', 'course':course,'surface':'Turf','code':'Flat',
                        'dist_f':6.,'going':'Good','class_group':'Flat|Flat|C4','win_time':t,
                        'lbs_per_sec':7.0,'beaten_l_eff':j*0.65*7/2.2,'lbs_per_length':2.2,
                        'eff_wt':eff_wt,'weighted_fig':98 - 2*j + rng.normal(0,1),
                        'skip_reason':''})
                    sec_runners.append((i+1,i*10+j+1,horse,j+1,runner_total))
                    raw = np.array([1.07,1.01,1.0,0.98,0.97,0.97])
                    raw = raw * (1+rng.normal(0,0.01,6))
                    raw = raw / raw.sum() * runner_total
                    for k,val in enumerate(raw):
                        sec_splits.append((i+1,i*10+j+1,k,float(val)))
            pd.DataFrame(fig).to_csv(root/'data/speed_v4/speed_figures.csv',index=False)
            pd.DataFrame(dc).to_csv(root/'data/speed_v4/distance_corrections.csv',index=False)
            con=sqlite3.connect(root/'data/sectionals.sqlite')
            con.execute('CREATE TABLE rtv_races(rtv_race_id INTEGER PRIMARY KEY,race_date TEXT,distance_yards REAL)')
            con.execute('CREATE TABLE rtv_runners(rtv_race_id INTEGER,rtv_runner_id INTEGER,horse_name TEXT,finish_position INTEGER,total_time_s REAL)')
            con.execute('CREATE TABLE rtv_sectionals(rtv_race_id INTEGER,rtv_runner_id INTEGER,sector_number INTEGER,sector_time REAL)')
            con.executemany('INSERT INTO rtv_races VALUES (?,?,?)',sec_races)
            con.executemany('INSERT INTO rtv_runners VALUES (?,?,?,?,?)',sec_runners)
            con.executemany('INSERT INTO rtv_sectionals VALUES (?,?,?,?)',sec_splits)
            con.commit();con.close()
            F0,R0 = model.load_inputs(root/'data/speed_v4/speed_figures.csv',
                                     root/'data/speed_v4/distance_corrections.csv')
            self.assertTrue((F0['base_wt'] == 126.0).all())
            self.assertTrue((R0['base_wt'] == 126.0).all())
            cutoff=pd.Timestamp('2025-03-20')
            original_std=model.fit_standard_model(R0,cutoff)[0][['key','std_base_s']]
            altered=R0.copy()
            altered.loc[altered['date'] >= cutoff, 'base_weight_time'] += 100
            future_invariant_std=model.fit_standard_model(altered,cutoff)[0][['key','std_base_s']]
            pd.testing.assert_frame_equal(original_std,future_invariant_std)
            report = model.run(Namespace(root=str(root),out=None,train_end='2025-03-19'))
            self.assertGreater(report['valid_race_clocks'],300)
            self.assertEqual(report['disputed_clocks'],0)
            self.assertGreater(report['sectionals']['rated_runners'],100)
            self.assertGreater(report['n_standard_groups'],0)
            df=pd.read_csv(root/'data/challenger_v1/result_speed_figures.csv.gz')
            self.assertGreater(df['challenger_fig'].notna().sum(),1000)
            self.assertGreater(df['sectional_clock_fig'].notna().sum(),1000)
            self.assertLess(df.loc[df['sectional_clock_fig'].notna(),'sectional_clock_delta'].abs().median(),2.)
            self.assertLess(df['late_index'].dropna().abs().sub(100).median(),10.)
            self.assertTrue((root/'data/challenger_v1/head_to_head_picks.csv').exists())
            self.assertTrue((root/'data/challenger_v1/sectional_splits.csv.gz').exists())
            self.assertTrue((root/'data/challenger_v1/audit.json').exists())
            self.assertTrue((root/'data/challenger_v1/result_standard_comparison.csv.gz').exists())
            self.assertGreater(report['benchmark']['n_comparable_races'], 25)
            self.assertLess(report['benchmark']['baseline_v4']['top_win_rate'], .8)
            self.assertLess(report['benchmark']['challenger_v1']['top_win_rate'], .8)


if __name__=='__main__':
    unittest.main()
