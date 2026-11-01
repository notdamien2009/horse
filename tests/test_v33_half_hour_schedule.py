"""No-network checks for half-hour opt-in schedule and non-overlapping fallback."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github' / 'workflows' / 'sportinglife.yml'

class HalfHourSchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding='utf-8')

    def test_both_cron_patterns_exist(self):
        self.assertIn('cron: "27 3 * * *"', self.workflow)
        self.assertIn('cron: "17,47 * * * *"', self.workflow)

    def test_half_hour_is_extra_opt_in(self):
        self.assertIn("vars.SL_HALFHOURLY_ENABLED == 'true'", self.workflow)
        self.assertIn("vars.SL_SCHEDULE_ENABLED == 'true'", self.workflow)
        self.assertIn("vars.SL_COLLECTION_ENABLED == 'true'", self.workflow)
        self.assertIn("github.event.repository.private == true", self.workflow)

    def test_daily_is_disabled_when_half_hour_enabled(self):
        self.assertIn("vars.SL_HALFHOURLY_ENABLED != 'true'", self.workflow)
        self.assertIn("github.event.schedule == '27 3 * * *'", self.workflow)
        self.assertIn("github.event.schedule == '17,47 * * * *'", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_half_hour_job_has_a_shorter_budget(self):
        self.assertIn("github.event.schedule == '17,47 * * * *' && '18' || '48'", self.workflow)
        self.assertIn('--max-runtime-minutes "$RUN_BUDGET_MINUTES"', self.workflow)
        self.assertIn('--date-order "$DATE_ORDER"', self.workflow)
        self.assertIn('--delay 6', self.workflow)
        self.assertIn('Store SQLite checkpoint as private Release asset', self.workflow)
        self.assertIn('racing_history.previous.sqlite.gz', self.workflow)

if __name__=='__main__':
    unittest.main()
