"""Offline regression tests for scheduled, bounded archive collection."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from backfill_controller import runtime_budget_reached

class DailyScheduleTests(unittest.TestCase):
    def test_budget_boundary(self):
        self.assertFalse(runtime_budget_reached(100.0,48,now=100+47*60))
        self.assertTrue(runtime_budget_reached(100.0,48,now=100+48*60))
        self.assertTrue(runtime_budget_reached(100.0,48,now=100+49*60))
        self.assertFalse(runtime_budget_reached(100.0,0,now=100+300*60))

    def test_workflow_has_authorisation_gate(self):
        w=(ROOT/'.github/workflows/sportinglife.yml').read_text(encoding='utf-8')
        self.assertIn("vars.SL_SCHEDULE_ENABLED == 'true'",w)
        self.assertIn("vars.SL_COLLECTION_ENABLED == 'true'",w)
        self.assertIn("github.event_name == 'schedule' && 'oldest'",w)
        self.assertIn('--max-runtime-minutes 48',w)
        self.assertIn('--batches 36',w)
        self.assertIn('--delay 6',w)
        self.assertIn('racing_history.previous.sqlite.gz',w)
        self.assertIn('cancel-in-progress: false',w)

if __name__=='__main__': unittest.main()
