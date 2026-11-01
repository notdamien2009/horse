#!/usr/bin/env python3
"""Safely checkpoint an SQLite database using SQLite's backup API.

Data collected is sourced only from Sporting Life; this module does not
contact any data provider. Use the gzip checkpoint as a GitHub Release asset.
"""
import argparse
import gzip
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

def verify(path):
    with closing(sqlite3.connect(str(path))) as conn:
        result=conn.execute('PRAGMA integrity_check').fetchone()[0]
        if result!='ok':raise RuntimeError('SQLite integrity check: '+result)
        return conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]

def save(db,archive):
    db=Path(db);archive=Path(archive);archive.parent.mkdir(parents=True,exist_ok=True)
    if not db.is_file():raise FileNotFoundError(db)
    with tempfile.TemporaryDirectory() as d:
        backup=Path(d)/'snapshot.sqlite'
        with closing(sqlite3.connect(str(db))) as source, closing(sqlite3.connect(str(backup))) as target:
            source.backup(target)
        races=verify(backup)
        temporary=archive.with_suffix(archive.suffix+'.tmp')
        with backup.open('rb') as inf,gzip.open(temporary,'wb',compresslevel=6) as out:
            import shutil;shutil.copyfileobj(inf,out)
        os.replace(temporary,archive)
    print(f'Checkpoint saved: {archive} ({races} races)')

def restore(archive,db):
    archive=Path(archive);db=Path(db);db.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        candidate=Path(d)/'candidate.sqlite'
        with gzip.open(archive,'rb') as inf,candidate.open('wb') as out:
            import shutil;shutil.copyfileobj(inf,out)
        new_count=verify(candidate)
        if db.exists():
            old_count=verify(db)
            if new_count<old_count:
                raise RuntimeError(f'Refusing to replace {old_count} races with only {new_count}')
        staged = db.with_name(db.name + '.restore-tmp')
        import shutil
        shutil.copyfile(candidate, staged)
        os.replace(staged, db)
    print(f'Restored {new_count} races to {db}')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('save','restore','verify'))
    p.add_argument('database')
    p.add_argument('archive',nargs='?')
    args=p.parse_args()
    if args.mode=='verify':print('Verified races:',verify(args.database))
    elif args.mode=='save':save(args.database,args.archive)
    else:restore(args.database,args.archive)
