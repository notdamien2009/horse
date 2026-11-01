#!/usr/bin/env python3
"""Reject non-Sporting Life source records and report the source breakdown."""
import collections
import json
import sqlite3
import sys
from pathlib import Path

def audit(db):
    c=sqlite3.connect(str(db))
    groups={}
    for table in ('races','runners'):
        counts=collections.Counter()
        for (raw,) in c.execute('SELECT data FROM '+table):
            obj=json.loads(raw)
            counts[obj.get('source','<missing>')]+=1
        groups[table]=dict(counts)
    c.close()
    print(json.dumps(groups,indent=2))
    for counts in groups.values():
        if any(k!='sportinglife' for k in counts):
            raise SystemExit('Source audit FAILED: non-Sporting Life records detected')
    return groups
if __name__=='__main__':audit(Path(sys.argv[1]))
