import csv, sqlite3, json, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import recover_archive as ra
ROOT=Path(__file__).resolve().parents[1]
class Recovery(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.c=sqlite3.connect(ROOT/'data/racing_history.sqlite')
    cls.races=[json.loads(x[0]) for x in cls.c.execute('select data from races')]
    cls.runners=[json.loads(x[0]) for x in cls.c.execute('select data from runners')]
  @classmethod
  def tearDownClass(cls):cls.c.close()
  def test_integrity(self):self.assertEqual(self.c.execute('pragma integrity_check').fetchone()[0],'ok')
  def test_recovered_coverage(self):
    self.assertEqual(len(self.races),28);self.assertEqual(len(self.runners),242)
    from collections import Counter
    self.assertEqual(Counter(r.get('date') for r in self.races),{'2022-10-21':3,'2026-10-21':25})
  def test_foreign_keys(self):
    ids={r['race_id'] for r in self.races}
    self.assertTrue(all(r['race_id'] in ids for r in self.runners))
    self.assertEqual(len({(r['race_id'],r['horse_id']) for r in self.runners}),len(self.runners))
  def test_neck_and_nonfinishers(self):
    self.assertEqual(ra.normalise({'margin_lengths_numeric':'0.01'})['margin_lengths_numeric'],0.01)
    self.assertTrue(any(r.get('status')=='fell' for r in self.runners))
    self.assertTrue(any(r.get('status')=='non_runner' for r in self.runners))
    self.assertTrue(any(r.get('status')=='pulled_up' for r in self.runners))
  def test_old_original_untouched(self):
    seed=sqlite3.connect('file:'+str(ROOT/'seed/original_racing_history.sqlite')+'?mode=ro',uri=True)
    try:self.assertEqual(seed.execute('select count(*) from races').fetchone()[0],20)
    finally:seed.close()
  def test_standards_not_approved(self):
    self.assertEqual(self.c.execute('select count(*) from recovery_audit where standards_eligible != 0').fetchone()[0],0)
  def test_exports(self):
    out=ROOT/'data/exports'
    for fn,size in [('races_all.csv',28),('runners_all.csv',242),('coverage_calendar.csv',1765)]:
      with (out/fn).open(encoding='utf-8-sig',newline='') as f:self.assertEqual(len(list(csv.DictReader(f))),size)
if __name__=='__main__':unittest.main(verbosity=2)
