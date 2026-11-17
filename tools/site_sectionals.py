#!/usr/bin/env python3
"""Pack last ~6 sectional runs for today's card horses into site_cache.sqlite.

A miss must not stop the daily update - the site hides the sectional panel
when this table is empty. Does not rewrite figure history.
"""
from __future__ import annotations

import csv
import gzip
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEC_DIR = ROOT / "data" / "sectionals_v12"
CARDS = ROOT / "data" / "cards.sqlite"
CACHE = ROOT / "data" / "site_cache.sqlite"
RUNNERS_CSV = SEC_DIR / "runner_sectionals.csv.gz"
SECTS_CSV = SEC_DIR / "section_figures.csv.gz"
KEEP = 6


def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def style_of(pct):
    if pct is None:
        return None
    if pct <= 0.2:
        return "front"
    if pct <= 0.45:
        return "prom"
    if pct <= 0.7:
        return "mid"
    return "rear"


def vs_par(sector_time, expected_s, par_time_s):
    par = expected_s if expected_s and expected_s > 0 else par_time_s
    if not sector_time or sector_time <= 0 or not par or par <= 0:
        return None
    return 100.0 * (par / sector_time - 1.0)


def skip(msg: str) -> None:
    print(f"site sectionals skipped: {msg}")
    sys.exit(0)


def card_horses() -> set[str]:
    if not CARDS.is_file():
        skip(f"missing {CARDS}")
    con = sqlite3.connect(f"file:{CARDS}?mode=ro", uri=True)
    norms = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT horse_norm FROM runners WHERE horse_norm IS NOT NULL AND horse_norm <> ''"
        )
    }
    con.close()
    return norms


def load_runners(norms: set[str]):
    if not RUNNERS_CSV.is_file():
        skip(f"missing {RUNNERS_CSV}")
    by: dict[str, list[dict]] = defaultdict(list)
    with gzip.open(RUNNERS_CSV, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            hn = norm_name(row.get("horse_name") or "")
            if hn and hn in norms:
                by[hn].append(row)
    kept: dict[str, list[dict]] = {}
    keys: set[tuple[str, str]] = set()
    for hn, rows in by.items():
        rows.sort(key=lambda r: (r.get("date") or "", r.get("off_time") or ""), reverse=True)
        seen: set[tuple] = set()
        out: list[dict] = []
        for r in rows:
            k = (r.get("date"), r.get("rtv_race_id") or r.get("race_id") or r.get("off_time"))
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
            if len(out) >= KEEP:
                break
        for i, r in enumerate(out, 1):
            r["_n"] = i
            r["_hn"] = hn
            keys.add((str(r.get("rtv_race_id") or ""), r.get("horse_name") or ""))
        kept[hn] = out
    return kept, keys


def load_sectors(keys: set[tuple[str, str]]):
    if not keys or not SECTS_CSV.is_file():
        return {}
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with gzip.open(SECTS_CSV, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            k = (str(row.get("rtv_race_id") or ""), row.get("horse_name") or "")
            if k not in keys:
                continue
            vs = vs_par(num(row.get("sector_time")), num(row.get("expected_s")), num(row.get("par_time_s")))
            if vs is None:
                continue
            kend = num(row.get("kend"))
            secn = num(row.get("sector_number"))
            out[k].append({
                "k": int(kend) if kend is not None else (int(secn) if secn is not None else 0),
                "i": int(secn) if secn is not None else 0,
                "vs": round(vs, 2),
            })
    for secs in out.values():
        secs.sort(key=lambda s: s["i"])
    return out


def write_cache(kept, sectors) -> None:
    if not CACHE.is_file():
        skip(f"missing {CACHE}")
    con = sqlite3.connect(CACHE)
    con.execute("DROP TABLE IF EXISTS sectionals")
    con.execute(
        """
        CREATE TABLE sectionals (
            horse_norm TEXT NOT NULL,
            date TEXT NOT NULL,
            course TEXT,
            rtv_race_id INTEGER,
            n INTEGER NOT NULL,
            pace_label TEXT,
            fin_speed_pct REAL,
            fig_adj REAL,
            fig REAL,
            run_style TEXT,
            style_pct REAL,
            sectors TEXT,
            PRIMARY KEY (horse_norm, n)
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS sectionals_horse_date_idx ON sectionals (horse_norm, date)")
    rows = []
    for hn, runs in kept.items():
        for r in runs:
            key = (str(r.get("rtv_race_id") or ""), r.get("horse_name") or "")
            secs = sectors.get(key) or []
            payload = [{"k": s["k"], "vs": s["vs"]} for s in secs]
            rtv = r.get("rtv_race_id") or None
            try:
                rtv = int(float(rtv)) if rtv not in (None, "") else None
            except ValueError:
                rtv = None
            rows.append((
                hn,
                r.get("date") or "",
                r.get("course") or "",
                rtv,
                int(r["_n"]),
                (r.get("race_pace") or "").strip() or None,
                num(r.get("fin_speed_pct")),
                num(r.get("fig_adj")),
                num(r.get("fig")),
                style_of(num(r.get("style_pct"))),
                num(r.get("style_pct")),
                json.dumps(payload, separators=(",", ":")) if payload else None,
            ))
    con.executemany(
        "INSERT OR REPLACE INTO sectionals "
        "(horse_norm, date, course, rtv_race_id, n, pace_label, fin_speed_pct, fig_adj, fig, run_style, style_pct, sectors) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    n_sec = sum(1 for r in rows if r[-1])
    print(f"sectionals: {len(rows)} runs for {len(kept)} of today's horses ({n_sec} with a sectional profile)")
    con.close()


def main() -> None:
    norms = card_horses()
    if not norms:
        skip("no runners on the current cards")
    kept, keys = load_runners(norms)
    sectors = load_sectors(keys)
    write_cache(kept, sectors)


if __name__ == "__main__":
    main()
