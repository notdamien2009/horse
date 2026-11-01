"""Offline regression tests; must never make live website requests."""
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tools'))
from sl_history import date_range,infer_surface_from_going
from repair_surface import update_record,repair
from qa_diagnostics import summarise,generate

class BackfillImprovementTests(unittest.TestCase):
    def test_surface_inference_conservative(self):
        self.assertEqual(infer_surface_from_going(' Standard ','flat'),'All-Weather')
        self.assertEqual(infer_surface_from_going('Standard to Slow','flat'),'All-Weather')
        self.assertIsNone(infer_surface_from_going('Good to Soft','flat'))
        self.assertIsNone(infer_surface_from_going('Standard','chase'))

    def test_no_standards_approval(self):
        race={'surface':'','race_type':'flat','going':'Standard',
              'qa_flags':'missing_surface|course_configuration_unverified',
              'qa_status':'review','standards_input_allowed':False}
        updated=update_record(race)
        self.assertEqual(updated['surface'],'All-Weather')
        self.assertNotIn('missing_surface',updated['qa_flags'])
        self.assertIn('surface_inferred_from_going',updated['qa_flags'])
        self.assertEqual(updated['qa_status'],'review')
        self.assertFalse(updated['standards_input_allowed'])
        self.assertEqual(race['surface'],'')

    def test_repair_idempotent_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE races(race_id TEXT PRIMARY KEY,data TEXT NOT NULL)')
                con.execute('INSERT INTO races VALUES(?,?)',('r1',json.dumps({
                    'track':'Southwell','surface':'','race_type':'flat','going':'Standard',
                    'qa_flags':'missing_surface','qa_status':'review'})))
            self.assertEqual(repair(db,False),1)
            with sqlite3.connect(db) as con:
                row=json.loads(con.execute('SELECT data FROM races').fetchone()[0])
                self.assertEqual(row['surface'],'')
            self.assertEqual(repair(db,True),1)
            self.assertEqual(repair(db,True),0)
            self.assertTrue((Path(folder)/'test.before_surface_repair.sqlite').exists())

    def test_chronological_order_is_opt_in(self):
        first=date(2022,1,1);last=date(2022,1,3)
        self.assertEqual(list(date_range(first,last,'oldest')),
                         ['2022-01-01','2022-01-02','2022-01-03'])
        self.assertEqual(list(date_range(first,last)),
                         ['2022-01-03','2022-01-02','2022-01-01'])

    def test_qa_report_groups_flags_and_preserves_approval(self):
        records=[{'track':'Southwell','qa_flags':'missing_surface|course_configuration_unverified',
                  'standards_input_allowed':False},
                 {'track':'Bath','qa_flags':'runner_count_mismatch|course_configuration_unverified',
                  'standards_input_allowed':False}]
        s=summarise(records)
        self.assertEqual(s['all_flag_counts']['course_configuration_unverified'],2)
        self.assertEqual(s['structural_flag_counts']['runner_count_mismatch'],1)
        self.assertEqual(s['distinct_races_with_structural_flags'],1)
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'qa.sqlite'
            with sqlite3.connect(db) as con:
                con.execute('CREATE TABLE races(race_id TEXT PRIMARY KEY,data TEXT)')
                con.executemany('INSERT INTO races VALUES(?,?)',
                                [(str(i),json.dumps(r)) for i,r in enumerate(records)])
            s=generate(db,Path(folder)/'exports')
            self.assertEqual(s['not_approved_for_standards'],2)
            self.assertTrue((Path(folder)/'exports'/'qa_flags_by_track.csv').exists())

if __name__=='__main__':unittest.main()
