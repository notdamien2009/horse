"""Regression checks on 2022 synthetic fixture and multi-run resume."""
from pathlib import Path
from tempfile import TemporaryDirectory
from sl_history import db_open, collect, numeric_margin, parse_index
from argparse import Namespace


def args(base, cap):
    return Namespace(export_only=False,live=False,html_dir=Path('demo_pages'),
        from_date=None,to_date=None,date='2022-10-21',
        max_days=1,max_races=cap,delay=4.0,retry_errors=False,refresh_index=False,
        database=base/'history.sqlite',output_dir=base/'exports',auto_export_limit=1000)


def test():
    assert numeric_margin('nse') is None
    with TemporaryDirectory() as d:
        root=Path(d)
        a=args(root,1)
        assert collect(a)==0
        db=db_open(a.database)
        assert db.execute('SELECT COUNT(*) FROM races').fetchone()[0]==1
        assert db.execute("SELECT COUNT(*) FROM race_queue WHERE status='pending'").fetchone()[0]==1
        db.close()
        assert collect(a)==0
        db=db_open(a.database)
        assert db.execute('SELECT COUNT(*) FROM races').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM runners').fetchone()[0]==4
        assert db.execute("SELECT COUNT(*) FROM race_queue WHERE status='parsed'").fetchone()[0]==2
        db.close()
        assert collect(a)==0
        db=db_open(a.database)
        assert db.execute('SELECT COUNT(*) FROM races').fetchone()[0]==2
        assert db.execute('SELECT COUNT(*) FROM runners').fetchone()[0]==4
        db.close()
        assert (root/'exports'/'daily_coverage.csv').is_file()
        assert (root/'exports'/'runners_all.csv').is_file()
        # A read/export-only run must release its database handle too.
        export_args = args(root, 1)
        export_args.export_only = True
        assert collect(export_args) == 0
        # Windows will reject this rename with WinError 32 if any DB handle
        # from collect, export or this regression test is still open.
        db_path = a.database
        moved = root/'history-released.sqlite'
        db_path.rename(moved)
        moved.rename(db_path)
        # Error paths must release connections (no source directory).
        bad_args = args(root/'other', 1)
        bad_args.html_dir = root/'missing_pages'
        bad_args.date = '2022-10-22'
        assert collect(bad_args) == 0
        renamed_bad = bad_args.database.with_name('moved.sqlite')
        bad_args.database.rename(renamed_bad)
        renamed_bad.rename(bad_args.database)
    print('PASS: resume, exports, error handling, and database handles released before Windows cleanup')

if __name__=='__main__':
    test()
