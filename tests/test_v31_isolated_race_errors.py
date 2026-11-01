"""Offline regression tests for quarantining a single incomplete race.

No website requests, no changes to the real user database.
"""
import csv
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'tools'))
from sl_history import db_open,register_index
from backfill_controller import (
    is_isolated_parse_error, error_counts, snapshot, export_queue_errors,
    run, open_db
)

class IsolatedRaceErrorTests(unittest.TestCase):
    def setUp(self):
        self.work=tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root=Path(self.work.name)
        self.db=self.root/'data.sqlite'
        self.day='2022-01-01'
        self.entries=[
          dict(race_id='663503',date=self.day,url='https://www.sportinglife.com/racing/results/2022-01-01/test/663503/race-a',
               listed_time='12:00',listed_label='Test race A',track='Test'),
          dict(race_id='663504',date=self.day,url='https://www.sportinglife.com/racing/results/2022-01-01/test/663504/race-b',
               listed_time='12:30',listed_label='Test race B',track='Test')]
        with closing(db_open(self.db)) as conn:
            register_index(conn,self.day,self.entries)

    def mark_error(self,race_id,message):
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE race_queue SET status='error',last_error=? WHERE race_id=?",
                        (message,race_id))

    def test_known_incomplete_page_is_quarantined_not_blocking(self):
        legacy='Race extraction incomplete, check page and recorded details'
        self.assertTrue(is_isolated_parse_error(legacy))
        self.assertTrue(is_isolated_parse_error('PARSE_INCOMPLETE: '+legacy))
        for msg in ('ACCESS_OR_TRANSPORT_ERROR: 403 Forbidden',
                    'UNEXPECTED_ERROR: KeyError',
                    'Unexpected unknown parse error',
                    ''):
            self.assertFalse(is_isolated_parse_error(msg))
        self.mark_error('663503',legacy)
        with closing(open_db(self.db)) as conn:
            state=snapshot(conn,self.day,self.day)
            self.assertEqual(state['isolated_parse_errors'],1)
            self.assertEqual(state['blocking_queue_errors'],0)
            self.assertEqual(state['pending'],1)
            outfile=self.root/'failed_race_pages.csv'
            export_queue_errors(conn,outfile,self.day,self.day)
            with outfile.open(encoding='utf-8-sig',newline='') as f:
                items=list(csv.DictReader(f))
            self.assertEqual(items[0]['race_id'],'663503')
            self.assertEqual(items[0]['failure_type'],'isolated_parse')

    def test_unknown_or_access_error_remains_blocking(self):
        self.mark_error('663503','ACCESS_OR_TRANSPORT_ERROR: access denied')
        with closing(open_db(self.db)) as conn:
            iso,blocking=error_counts(conn,self.day,self.day)
            self.assertEqual((iso,blocking),(0,1))

    def test_controller_check_mode_resumes_only_for_isolated_failure(self):
        legacy='Race extraction incomplete, check page and recorded details'
        self.mark_error('663503',legacy)
        args=SimpleNamespace(
           database=str(self.db),logs=str(self.root/'logs'),
           start=self.day,end=self.day,mode='check')
        self.assertEqual(run(args),0)
        self.mark_error('663503','UNEXPECTED_ERROR: invalid page layout')
        self.assertEqual(run(args),4)

if __name__=='__main__':
    unittest.main()
