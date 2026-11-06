"""Offline regression tests for tools/window_backfill.py; no website access."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from datetime import date

SOURCE = Path(__file__).resolve().parents[1] / 'tools' / 'window_backfill.py'
spec = importlib.util.spec_from_file_location('window_backfill', SOURCE)
import sys
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def make_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript('''
      CREATE TABLE days(race_date TEXT PRIMARY KEY,index_state TEXT NOT NULL,discovered INTEGER DEFAULT 0,last_error TEXT,indexed_utc TEXT);
      CREATE TABLE race_queue(race_id TEXT PRIMARY KEY,race_date TEXT NOT NULL,url TEXT NOT NULL,track TEXT,status TEXT NOT NULL,last_error TEXT,attempts INTEGER DEFAULT 0);
      CREATE TABLE races(race_id TEXT PRIMARY KEY,race_date TEXT NOT NULL,data TEXT NOT NULL);
      CREATE TABLE runners(race_id TEXT NOT NULL,horse_id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(race_id,horse_id));
    ''')
    con.commit()
    return con


class CalendarTests(unittest.TestCase):
    def test_monthly_boundaries_include_partial_final_month(self):
        x = list(module.windows(date(2022, 1, 1), date(2022, 3, 5), 1))
        self.assertEqual([(w.start.isoformat(), w.end.isoformat()) for w in x],
                         [('2022-01-01', '2022-01-31'), ('2022-02-01', '2022-02-28'), ('2022-03-01', '2022-03-05')])

    def test_three_month_and_leap_year(self):
        x = list(module.windows(date(2024, 1, 1), date(2024, 7, 2), 3))
        self.assertEqual([(str(w.start), str(w.end)) for w in x],
                         [('2024-01-01', '2024-03-31'), ('2024-04-01', '2024-06-30'), ('2024-07-01', '2024-07-02')])

    def test_mid_month_start_and_window_key(self):
        w = next(module.windows(date(2022, 2, 15), date(2022, 6, 30), 3))
        self.assertEqual(w.key, '20220215_20220430')


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'data' / 'racing_history.sqlite'
        self.con = make_db(self.db)
        self.addCleanup(self.con.close)
        self.win = module.Window(date(2022, 1, 1), date(2022, 1, 2))

    def add(self, day, race_id, status='parsed', err=None, discovered=1):
        self.con.execute('INSERT OR REPLACE INTO days VALUES(?,?,?,?,?)', (day, 'indexed', discovered, None, None))
        self.con.execute('INSERT INTO race_queue(race_id,race_date,url,track,status,last_error) VALUES(?,?,?,?,?,?)',
                         (race_id, day, f'https://www.sportinglife.com/racing/results/{day}/test/{race_id}/race', 'Test',status,err))
        if status == 'parsed':
            self.con.execute('INSERT INTO races VALUES(?,?,?)', (race_id, day, json.dumps({'race_id':race_id,'source':'sportinglife','date':day,'qa_status':'parsed_not_verified'})))
            self.con.execute('INSERT INTO runners VALUES(?,?,?)', (race_id, f'h{race_id}', json.dumps({'race_id':race_id,'horse_id':f'h{race_id}','horse':'Horse A','position':1,'status':'finished'})))
        self.con.commit()

    def test_partial_and_indexed_with_unverified_label(self):
        self.add('2022-01-01', 'race1')
        r = module.window_stats(self.con,self.win)
        self.assertEqual(r['status'],'in_progress')
        self.assertEqual(r['saved_runners'], 1)
        self.add('2022-01-02','race2')
        r = module.window_stats(self.con,self.win)
        self.assertEqual(r['status'],'indexed_audit_required')
        self.assertFalse(r['verified_complete'])

    def test_isolated_error_does_not_erase_data_or_claim_complete(self):
        self.add('2022-01-01', 'race1')
        self.add('2022-01-02','race2',status='error', err='PARSE_INCOMPLETE: Race extraction incomplete, check page and recorded details')
        r = module.window_stats(self.con,self.win)
        self.assertEqual(r['status'],'indexed_with_qa_holds')
        self.assertEqual(r['isolated_parse_holds'],1)
        self.assertFalse(r['verified_complete'])

    def test_transport_error_blocks_next_window(self):
        self.add('2022-01-01', 'race1')
        self.add('2022-01-02','race2',status='error',err='ACCESS_OR_TRANSPORT_ERROR: denied')
        self.assertEqual(module.window_stats(self.con,self.win)['status'], 'blocked_review_required')

    def test_saved_race_missing_runners_blocks_window(self):
        self.add("2022-01-01", "race1")
        self.add("2022-01-02", "race2")
        self.con.execute("DELETE FROM runners WHERE race_id='race2'")
        self.con.commit()
        r = module.window_stats(self.con,self.win)
        self.assertEqual(r["status"], "blocked_review_required")
        self.assertEqual(r["races_without_runners"], 1)


    def test_missing_queued_races_not_silently_complete(self):
        self.add('2022-01-01', 'race1', discovered=2)
        self.add('2022-01-02','race2')
        r = module.window_stats(self.con,self.win)
        self.assertEqual(r['status'], 'blocked_review_required')
        self.assertEqual(r['mismatched_index_days'],1)

    def test_exports_preserve_fields_and_positions(self):
        self.add('2022-01-01', 'race1')
        stats = module.window_stats(self.con,self.win)
        output = module.export_window(self.db,self.root/'exports',self.win,stats)
        race_csv = (output/'races.csv').read_text(encoding='utf-8-sig')
        runner_csv = (output/'runners.csv').read_text(encoding='utf-8-sig')
        self.assertIn('race1',race_csv)
        self.assertIn('Horse A',runner_csv)
        self.assertIn('2022-01-01', runner_csv)
        self.assertEqual(json.loads((output/'coverage.json').read_text())['status'],'in_progress')


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=self.root/'data'/'racing_history.sqlite'
        self.con=make_db(self.db)
        self.addCleanup(self.con.close)

    def test_status_mode_uses_existing_db_no_collection(self):
        with patch.object(module,'ROOT',self.root):
            with redirect_stdout(StringIO()):
                code=module.main(['--mode','status','--start','2022-01-01','--end','2022-01-02'])
        self.assertEqual(code,0)
        self.assertTrue((self.root/'data/backfill_logs/window_status.csv').is_file())
        self.assertFalse((self.root/'data/exports').exists())

    def test_repeated_collect_runs_resume_same_partial_window(self):
        (self.root/'src').mkdir()
        (self.root/'src'/'backfill_controller.py').write_text('# stub, not executed')
        with patch.object(module, 'ROOT', self.root):
            calls = []
            def fake_subprocess(argv, cwd, check):
                self.assertEqual(cwd, self.root)
                self.assertIn('--date-order', argv)
                self.assertEqual(argv[argv.index('--date-order') + 1], 'oldest')
                self.assertEqual(argv[argv.index('--start') + 1], '2022-01-01')
                self.assertEqual(argv[argv.index('--end') + 1], '2022-01-02')
                n = len(calls) + 1
                day = f'2022-01-0{n}'
                rid = f'race{n}'
                self.con.execute('INSERT INTO days VALUES(?,?,?,?,?)', (day, 'indexed', 1, None, None))
                self.con.execute('INSERT INTO race_queue(race_id,race_date,url,track,status) VALUES(?,?,?,?,?)',
                                 (rid, day, 'https://www.sportinglife.com', 'Test', 'parsed'))
                self.con.execute('INSERT INTO races VALUES(?,?,?)', (rid, day, json.dumps({'race_id':rid,'race_date':day,'source':'sportinglife'})))
                self.con.execute('INSERT INTO runners VALUES(?,?,?)', (rid, f'horse{n}', json.dumps({'race_id':rid,'horse_id':f'horse{n}','status':'finished','position':1})))
                self.con.commit()
                calls.append(argv)
                return type('Result', (), {'returncode': 0})()
            with patch.object(module.subprocess, 'run', side_effect=fake_subprocess):
                flags = ['--mode','collect','--offline-dir','fixtures', '--start','2022-01-01',
                         '--end','2022-01-02','--months','1','--batches','1']
                with redirect_stdout(StringIO()):
                    self.assertEqual(module.main(flags), 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(json.loads((self.root/'data/backfill_logs/window_status.json').read_text())['windows'][0]['status'], 'in_progress')
                with redirect_stdout(StringIO()):
                    self.assertEqual(module.main(flags), 0)
                self.assertEqual(len(calls), 2)
                self.assertEqual(json.loads((self.root/'data/backfill_logs/window_status.json').read_text())['windows'][0]['status'], 'indexed_audit_required')
                self.assertTrue((self.root/'data/exports/windows/20220101_20220102/runners.csv').exists())

    def test_live_mode_requires_permission_gate(self):
        with patch.object(module,'ROOT',self.root), patch.dict('os.environ',{'SL_COLLECTION_ENABLED':'false'}):
            with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
                code=module.main(['--mode','collect','--start','2022-01-01','--end','2022-01-02'])
        self.assertEqual(code,4)

    def test_no_fresh_database_created_when_checkpoint_missing(self):
        self.con.close()
        self.db.unlink()
        with patch.object(module,'ROOT',self.root):
            with redirect_stderr(StringIO()):
                code=module.main(['--mode','status','--start','2022-01-01','--end','2022-01-02'])
        self.assertEqual(code,4)
        self.assertFalse(self.db.exists())


if __name__=='__main__':
    unittest.main()
