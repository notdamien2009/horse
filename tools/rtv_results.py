#!/usr/bin/env python3
"""
Racing TV results backfill  ->  data/racing_history.sqlite

Adds GB + IRE race results (including per-runner close-up comments) from the
public Racing TV API into the same database as the Sporting Life history,
using the same races/runners JSON field names.

  day list : https://api.racingtv.com/racing/results/list/{YYYY-MM-DD}
  results  : https://api.racingtv.com/racing/results/{date}/{track}/{HHMM}

Existing Sporting Life rows are never updated or deleted. New rows are tagged
source='rtv' and use race_id values like 'rtv:509502' so they cannot collide.
Races already present (match on date + course + off time) are skipped.

A timestamped copy of racing_history.sqlite is made before the first write
of each run.

Usage:
  python tools/rtv_results.py
  python tools/rtv_results.py --start 2023-12-01 --end 2026-11-15 --delay 3
  python tools/rtv_results.py --test-day 2024-01-04
  python tools/rtv_results.py --status
"""
from __future__ import print_function

import argparse
import csv
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "racing_history.sqlite")
WORK_DIR = os.path.join(ROOT, "data", "rtv_results_backfill")
STOP_FILE = os.path.join(WORK_DIR, "STOP")
LOG_FILE = os.path.join(WORK_DIR, "collector.log")
MISSING_FILE = os.path.join(WORK_DIR, "MISSING_DATES.csv")
API = "https://api.racingtv.com/"
MIN_DELAY = 1.0
DEFAULT_START = "2023-12-01"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Requested-With": "racingtv-web/5.6.0",
    "Origin": "https://www.racingtv.com",
    "Referer": "https://www.racingtv.com/",
}

STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS rtv_results_days(
  race_date TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'pending',
  meetings INTEGER,
  listed INTEGER,
  saved INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  missing INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  updated_at TEXT);
CREATE TABLE IF NOT EXISTS rtv_results_queue(
  rtv_race_id INTEGER PRIMARY KEY,
  race_date TEXT NOT NULL,
  track_slug TEXT NOT NULL,
  off_hhmm TEXT NOT NULL,
  course TEXT,
  off_time TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  sl_match_id TEXT,
  saved_race_id TEXT,
  updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_rtv_res_q_day ON rtv_results_queue(race_date, status);
"""

MARGIN_SYMS = {
    "nose": 0.05, "nse": 0.05, "ns": 0.05, "n": 0.05,
    "short head": 0.10, "sht-hd": 0.10, "sht hd": 0.10, "shd": 0.10, "short-head": 0.10,
    "head": 0.20, "hd": 0.20,
    "short neck": 0.25, "snk": 0.25, "sht-nk": 0.25,
    "neck": 0.30, "nk": 0.30,
    "dead heat": 0.00, "dht": 0.00, "dh": 0.00,
    "dist": 30.0, "distance": 30.0, "dst": 30.0,
}
CASUALTY = {
    "F": "fell", "PU": "pulled_up", "UR": "unseated", "BD": "brought_down",
    "SU": "slipped_up", "RO": "ran_out", "REF": "refused", "CO": "carried_out",
    "DSQ": "disqualified", "RR": "refused_to_race", "LFT": "left_at_start",
    "P": "pulled_up", "U": "unseated", "B": "brought_down",
}


def yesterday():
    return (dt.date.today() - dt.timedelta(days=1)).isoformat()


def now_local():
    return dt.datetime.now().isoformat(timespec="seconds")


def now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _ensure_work_dir():
    os.makedirs(WORK_DIR, exist_ok=True)


def log(*a):
    line = now_local() + " " + " ".join(str(x) for x in a)
    try:
        print(line, flush=True)
    except Exception:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    try:
        _ensure_work_dir()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class Blocked(Exception):
    pass


def fnum(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x))
    return float(m.group()) if m else None


def parse_time_s(s):
    """'1m, 58.7s' / '1m 28.36s' / '38.98s' / '4m 33s' -> seconds"""
    if not s:
        return None
    m = re.match(r"\s*(?:(\d+)m,?\s*)?(?:(\d+(?:\.\d+)?)s)?\s*$", str(s).strip(), re.I)
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)


def format_winning_time(s):
    """Normalise RTV '2m, 37.18s' to SL-style '2m 37.18s'."""
    if not s:
        return None
    t = re.sub(r"\s*,\s*", " ", str(s).strip())
    t = re.sub(r"\s+", " ", t)
    return t or None


def parse_distance(title_full):
    """'... 4YO+ 2m 1f 24y Winner: ...' -> ('2m 1f 24y', yards)"""
    if not title_full:
        return None, None
    head = title_full.split(" Winner")[0]
    m = re.search(r"(?:(\d+)m)?\s*(?:(\d+)f)?\s*(?:(\d+)y)?\s*$", head.strip())
    if not m or not any(m.groups()):
        return None, None
    mi, fu, ya = (int(g) if g else 0 for g in m.groups())
    raw = m.group(0).strip()
    return raw or None, mi * 1760 + fu * 220 + ya


def parse_class(title_full):
    m = re.search(r"\(Class\s+(\d)\)", title_full or "", re.I)
    return m.group(1) if m else None


def parse_surface(title_full):
    t = title_full or ""
    if re.search(r"\(All\s*Weather\)", t, re.I) or re.search(r"\(AllWeather\)", t, re.I):
        return "AW"
    if re.search(r"\(Polytrack\)", t, re.I):
        return "AW"
    if re.search(r"\(Tapeta\)", t, re.I):
        return "AW"
    if re.search(r"\(Fibresand\)", t, re.I):
        return "AW"
    if re.search(r"\(Dirt\)", t, re.I):
        return "Dirt"
    if re.search(r"\(Turf\)", t, re.I):
        return "Turf"
    return None


def parse_prize(title_full):
    m = re.search(r"Winner:\s*([£€$]\s*[0-9,]+)", title_full or "")
    return m.group(1).replace(" ", "") if m else None


def parse_race_type(rt):
    t = re.sub(r"\s+", "_", (rt or "").strip().lower())
    if t in ("nh_flat", "nhflat", "bumper"):
        return "nh_flat"
    return t or None


def hhmm_from_iso(sts):
    if not sts or "T" not in sts:
        return None
    return sts.split("T")[1][:5]


def norm_course(name):
    """'Sandown Park'/'Sandown', 'Epsom Downs'/'Epsom', 'The Curragh'/'Curragh' -> same key."""
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    words = [w for w in re.split(r"[^a-z]+", n) if w and w not in ("park", "the", "downs", "city", "racecourse", "aw")]
    return "".join(words)


def weight_lb(w):
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*$", str(w or ""))
    return int(m.group(1)) * 14 + int(m.group(2)) if m else None


def clean_headgear(text):
    if not text:
        return ""
    s = re.sub(r"<sup>(.*?)</sup>", r"\1", str(text), flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def parse_margin(s):
    """Return (display, lengths_float) from RTV between_distance ('2 1/2 l', 'Head')."""
    if s is None:
        return None, None
    raw = str(s).strip()
    if not raw:
        return None, None
    t = raw.lower().replace("lengths", "l").replace("length", "l")
    t = t.replace("\u00a0", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*\.\s*$", "", t)
    t_nol = re.sub(r"\s*l\s*$", "", t).strip()
    key = t_nol.replace("-", " ")
    if key in MARGIN_SYMS:
        val = MARGIN_SYMS[key]
        pretty = {"nose": "nse", "nse": "nse", "ns": "nse", "n": "nse",
                  "short head": "shd", "sht hd": "shd", "sht-hd": "shd", "shd": "shd", "short-head": "shd",
                  "head": "hd", "hd": "hd",
                  "short neck": "snk", "snk": "snk", "sht-nk": "snk",
                  "neck": "nk", "nk": "nk",
                  "dead heat": "dht", "dht": "dht", "dh": "dht",
                  "dist": "dist", "distance": "dist", "dst": "dist"}.get(key, raw)
        return pretty, val
    # e.g. '2 1/2', '1 3/4', '3/4', '6.5', '2'
    t_nol = t_nol.replace("¼", " 1/4").replace("½", " 1/2").replace("¾", " 3/4")
    t_nol = re.sub(r"\s+", " ", t_nol).strip()
    m = re.match(r"^(?:(\d+)\s+)?(?:(\d+)\s*/\s*(\d+))?$", t_nol)
    if m and (m.group(1) or m.group(2)):
        whole = int(m.group(1) or 0)
        num = int(m.group(2) or 0)
        den = int(m.group(3) or 1)
        if den == 0:
            return raw, None
        val = whole + (num / den if num else 0)
        pretty = ""
        if whole:
            pretty += str(whole)
        if num:
            frac = { (1,4): "¼", (1,2): "½", (3,4): "¾" }.get((num, den), "%s/%s" % (num, den))
            pretty += (("" if not whole else "") and "") + (frac if not whole else frac)
            if whole:
                pretty = str(whole) + frac
        return pretty or raw, val
    m2 = re.match(r"^(\d+(?:\.\d+)?)$", t_nol)
    if m2:
        val = float(m2.group(1))
        if val.is_integer():
            return str(int(val)), val
        return m2.group(1), val
    return raw, None


def runner_status(ru):
    st = ((ru.get("status") or {}).get("state") or "").lower()
    finish_text = (ru.get("finish_text") or "").strip()
    pos = ru.get("amended_position") if ru.get("amended_position") is not None else ru.get("finish_position")
    if st == "scratched" or (not finish_text and pos is None and st != "casualty"):
        return "non_runner", "NR", None
    if finish_text and not re.search(r"\d", finish_text):
        code = re.sub(r"[^A-Za-z]", "", finish_text).upper()
        if code in CASUALTY:
            return CASUALTY[code], code, pos if isinstance(pos, int) else None
        if st == "casualty" and code:
            return CASUALTY.get(code, code.lower()), code, pos if isinstance(pos, int) else None
    if pos is not None:
        try:
            return "finished", str(int(pos)), int(pos)
        except (TypeError, ValueError):
            return "finished", finish_text or str(pos), None
    if finish_text:
        return "finished", finish_text, None
    return st or "unknown", finish_text or None, None


class Client:
    def __init__(self, delay):
        self.delay = max(MIN_DELAY, float(delay))
        self.last = 0.0
        self.blocks = 0
        self.errors = 0

    def get(self, path):
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        req = urllib.request.Request(API + path, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read() if hasattr(e, "read") else b""
        except Exception as e:
            self.errors += 1
            return -1, {"_error": repr(e)}
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict) and isinstance(data.get("meta"), dict):
            status = data["meta"].get("status", status) or status
        if status in (403, 429):
            self.blocks += 1
            log("HTTP %s on %s (block count %s)" % (status, path, self.blocks))
            if self.blocks >= 3:
                raise Blocked("HTTP %s x%s" % (status, self.blocks))
            time.sleep(60 * self.blocks)
            return status, data
        if status >= 500 or data is None:
            self.errors += 1
        else:
            self.blocks = 0
            self.errors = 0
        return status, data


def connect(db, create_core=False):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = sqlite3.connect(db, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=OFF")
    if create_core:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS races (
          race_id TEXT PRIMARY KEY, race_date TEXT NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runners (
          race_id TEXT NOT NULL, horse_id TEXT NOT NULL, data TEXT NOT NULL,
          PRIMARY KEY (race_id, horse_id));
        """)
    ensure_schema(con)
    return con


def ensure_schema(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(races)")]
    if cols and "source" not in cols:
        con.execute("ALTER TABLE races ADD COLUMN source TEXT DEFAULT 'sportinglife'")
        log("added races.source column (existing rows default to 'sportinglife')")
    con.executescript(STATE_SCHEMA)
    con.execute("CREATE INDEX IF NOT EXISTS ix_races_date ON races(race_date)")
    con.commit()


def backup_db(db):
    """Timestamped copy of the sqlite file (and WAL/SHM if present) next to it."""
    if not os.path.exists(db):
        return None
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(os.path.dirname(os.path.abspath(db)),
                        "racing_history.backup-%s.sqlite" % ts)
    log("backing up database to %s" % dest)
    shutil.copy2(db, dest)
    for suffix in ("-wal", "-shm"):
        side = db + suffix
        if os.path.exists(side):
            shutil.copy2(side, dest + suffix)
    log("backup done (%s bytes)" % os.path.getsize(dest))
    return dest


def load_existing_index(con):
    """Map (date, norm_course, HH:MM) -> race_id for skip matching."""
    idx = {}
    n = 0
    for race_id, race_date, data in con.execute("SELECT race_id, race_date, data FROM races"):
        n += 1
        try:
            j = json.loads(data)
        except Exception:
            continue
        date = j.get("date") or race_date
        track = norm_course(j.get("track"))
        for tf in (j.get("scheduled_time"), j.get("actual_off_time")):
            if tf:
                key = (date, track, str(tf)[:5])
                idx.setdefault(key, str(race_id))
    return idx, n


def lookup_existing(idx, date, course, off_time):
    if not off_time:
        return None
    base = (date, norm_course(course), off_time[:5])
    sid = idx.get(base)
    if sid:
        return sid
    try:
        hh, mm = map(int, off_time[:5].split(":"))
    except Exception:
        return None
    for delta in (1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 10, -10, 15, -15):
        t = hh * 60 + mm + delta
        if t < 0 or t >= 24 * 60:
            continue
        sid = idx.get((date, norm_course(course), "%02d:%02d" % (t // 60, t % 60)))
        if sid:
            return sid
    return None


def append_missing(row):
    _ensure_work_dir()
    exists = os.path.exists(MISSING_FILE)
    with open(MISSING_FILE, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["logged_at", "race_date", "course", "off_time", "rtv_race_id", "reason"])
        if not exists:
            w.writeheader()
        w.writerow(row)


def list_day(con, cli, date, countries):
    st, d = cli.get("racing/results/list/%s" % date)
    if st != 200 or not isinstance(d, dict):
        raise RuntimeError("day list %s -> HTTP %s" % (date, st))
    meetings = 0
    races = 0
    for m in d.get("meetings") or []:
        tr = m.get("track") or {}
        cc = ((tr.get("country_code") or {}).get("racing") or "").upper()
        if cc not in countries:
            continue
        meetings += 1
        slug = (tr.get("slug") or "").strip("/")
        course = tr.get("name")
        for r in m.get("completed_races") or []:
            sts = r.get("start_time_scheduled") or ""
            off = hhmm_from_iso(sts)
            if not off:
                continue
            races += 1
            con.execute(
                """INSERT INTO rtv_results_queue(rtv_race_id,race_date,track_slug,off_hhmm,course,off_time,status,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(rtv_race_id) DO UPDATE SET
                     race_date=excluded.race_date, track_slug=excluded.track_slug,
                     off_hhmm=excluded.off_hhmm, course=excluded.course, off_time=excluded.off_time,
                     updated_at=excluded.updated_at
                   WHERE rtv_results_queue.status IN ('pending','error')""",
                (r["id"], date, slug, off.replace(":", ""), course, off, "pending", now_local()),
            )
    con.execute(
        """INSERT INTO rtv_results_days(race_date,status,meetings,listed,updated_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(race_date) DO UPDATE SET
             status=CASE WHEN rtv_results_days.status='done' THEN rtv_results_days.status ELSE 'listed' END,
             meetings=excluded.meetings, listed=excluded.listed, updated_at=excluded.updated_at""",
        (date, "listed", meetings, races, now_local()),
    )
    con.commit()
    return meetings, races


def build_race_records(date, slug, off_hhmm, payload):
    race = (payload or {}).get("race") or {}
    if not race:
        raise ValueError("no race object in results payload")
    meeting = race.get("meeting") or {}
    track = (meeting.get("track") or {})
    course = track.get("name") or ""
    title_full = race.get("title_full") or race.get("title") or ""
    dist_raw, yards = parse_distance(title_full)
    win_raw = format_winning_time(race.get("win_time_formatted"))
    win_s = parse_time_s(win_raw)
    scheduled = hhmm_from_iso(race.get("start_time_scheduled")) or (
        "%s:%s" % (off_hhmm[:2], off_hhmm[2:]) if off_hhmm and len(off_hhmm) >= 4 else None
    )
    actual_off = hhmm_from_iso(race.get("started_at"))
    rtv_id = race.get("id")
    race_id = "rtv:%s" % rtv_id
    url = "https://www.racingtv.com/results/%s/%s/%s" % (date, slug, scheduled or off_hhmm)
    runners_in = list(race.get("runners") or [])

    parsed = []
    for ru in runners_in:
        status, status_raw, pos = runner_status(ru)
        hid_src = ((ru.get("horse") or {}).get("id"))
        horse_id = "rtv:%s" % hid_src if hid_src is not None else "rtv-runner:%s" % ru.get("id")
        margin_disp, margin_num = parse_margin(ru.get("between_distance"))
        if status == "finished" and pos == 1:
            margin_disp, margin_num = None, 0.0
        odds = ((ru.get("starting_price") or {}).get("fractional") or "") or None
        if odds and ru.get("starting_price_favorite") == 1 and not str(odds).lower().endswith("f"):
            odds = str(odds) + "f"
        wt = ru.get("format_weight")
        comment = ru.get("close_up_comment") or None
        if comment:
            comment = comment.strip() or None
        horse = ru.get("horse_name") or (ru.get("horse") or {}).get("name")
        rec = {
            "date": date,
            "race_id": race_id,
            "track": course,
            "horse_id": str(horse_id),
            "horse": horse,
            "position": pos,
            "status": status,
            "status_raw": status_raw,
            "saddlecloth": ru.get("cloth_number"),
            "draw": ru.get("barrier_number"),
            "margin_from_preceding": margin_disp,
            "age": ru.get("age"),
            "weight_raw": wt,
            "weight_lb": weight_lb(wt),
            "odds_raw": odds,
            "trainer": ru.get("trainer_name") or (ru.get("trainer") or {}).get("name"),
            "jockey": ru.get("jockey_name") or (ru.get("jockey") or {}).get("name"),
            "comment": comment,
            "comment_raw": comment,
            "runner_text_raw": None,
            "url": url,
            "identity_source": "rtv",
            "margin_lengths_numeric": margin_num,
            "cumulative_beaten_lengths": None,
            "win_dist_from_winner": None,
            "legacy_win_time_plus_dist": None,
            "time_adjustment_method": None,
            "source": "rtv",
            "extracted_at_utc": now_utc(),
            "headgear": clean_headgear(ru.get("equipment_text")) or None,
            "timeform_rating": ru.get("timeform_original_rating"),
            "rtv_runner_id": ru.get("id"),
        }
        bits = []
        if rec["saddlecloth"] is not None:
            bits.append(str(rec["saddlecloth"]))
        if rec.get("draw") not in (None, "", 0) and rec["status"] != "non_runner":
            bits.append("(%s)" % rec["draw"])
        if horse:
            bits.append(horse)
        if wt:
            bits.append(wt)
        if rec["age"] is not None:
            bits.append("Age: %s" % rec["age"])
        if rec["trainer"]:
            bits.append("T: %s" % rec["trainer"])
        if rec["jockey"]:
            bits.append("J: %s" % rec["jockey"])
        if comment:
            bits.append(comment)
        rec["runner_text_raw"] = " ".join(bits)
        parsed.append(rec)

    # Cumulative beaten distances along finishing order
    finishers = [r for r in parsed if r["status"] == "finished" and r["position"] is not None]
    finishers.sort(key=lambda r: r["position"])
    cum = 0.0
    ok_margins = True
    for i, r in enumerate(finishers):
        if i == 0:
            r["margin_lengths_numeric"] = 0.0
            r["cumulative_beaten_lengths"] = 0.0
            r["win_dist_from_winner"] = 0.0
        else:
            inc = r["margin_lengths_numeric"]
            if inc is None:
                ok_margins = False
                inc = 0.0
            cum += inc
            r["cumulative_beaten_lengths"] = cum
            r["win_dist_from_winner"] = cum
        if win_s is not None and r["cumulative_beaten_lengths"] is not None:
            r["legacy_win_time_plus_dist"] = round(win_s + r["cumulative_beaten_lengths"], 4)
            r["time_adjustment_method"] = "legacy_numeric_margin_added_to_seconds"

    finishers_n = len(finishers)
    nonfinish = sum(1 for r in parsed if r["status"] not in ("finished", "non_runner"))
    nonrun = sum(1 for r in parsed if r["status"] == "non_runner")
    actual = finishers_n + nonfinish
    declared = len(parsed)
    comments_n = sum(1 for r in parsed if r["comment"])
    flags = []
    if not win_s:
        flags.append("winning_time_missing")
    if not ok_margins and finishers_n > 1:
        flags.append("unconverted_symbolic_margins")
    if actual and comments_n < finishers_n:
        flags.append("comments_incomplete")
    qa_status = "ok" if not flags else "review"
    standards = bool(win_s) and (ok_margins or finishers_n <= 1)

    race_rec = {
        "date": date,
        "race_id": race_id,
        "track": course,
        "race_name": race.get("title") or "",
        "scheduled_time": scheduled,
        "actual_off_time": actual_off,
        "distance_raw": dist_raw,
        "distance_yards": yards,
        "class": parse_class(title_full),
        "going": race.get("track_condition") or meeting.get("track_condition"),
        "surface": parse_surface(title_full),
        "race_type": parse_race_type(race.get("race_type")),
        "declared_runners": declared,
        "winning_time_raw": win_raw,
        "winning_time_seconds": win_s,
        "status": "weighed_in" if ((race.get("status") or {}).get("state") == "resulted") else ((race.get("status") or {}).get("state") or "weighed_in"),
        "url": url,
        "warnings": "",
        "actual_runners": actual,
        "source": "rtv",
        "course_configuration": "",
        "extracted_at_utc": now_utc(),
        "finishers_captured": finishers_n,
        "nonfinishers_captured": nonfinish,
        "nonrunners_captured": nonrun,
        "qa_status": qa_status,
        "qa_flags": "|".join(flags),
        "standards_input_allowed": standards,
        "prize_raw": parse_prize(title_full),
        "rtv_race_id": rtv_id,
        "title_full": title_full,
    }
    return race_id, race_rec, parsed


def save_race(con, race_id, race_rec, runners, date):
    con.execute(
        "INSERT INTO races(race_id, race_date, data, source) VALUES(?,?,?,?)",
        (race_id, date, json.dumps(race_rec, separators=(",", ":"), ensure_ascii=False), "rtv"),
    )
    for ru in runners:
        con.execute(
            "INSERT INTO runners(race_id, horse_id, data) VALUES(?,?,?)",
            (race_id, ru["horse_id"], json.dumps(ru, separators=(",", ":"), ensure_ascii=False)),
        )


def process_race(con, cli, row, existing, backup_state):
    rtv_id, date, slug, hhmm, course, off_time = row
    saved_id = "rtv:%s" % rtv_id
    already = con.execute("SELECT 1 FROM races WHERE race_id=?", (saved_id,)).fetchone()
    match = lookup_existing(existing, date, course, off_time)
    if already or (match and not str(match).startswith("rtv:")):
        sid = saved_id if already else match
        con.execute(
            "UPDATE rtv_results_queue SET status='skipped', sl_match_id=?, saved_race_id=?, last_error=NULL, updated_at=? WHERE rtv_race_id=?",
            (match, sid, now_local(), rtv_id),
        )
        con.commit()
        return "skipped", "already %s" % sid
    if match and str(match).startswith("rtv:"):
        con.execute(
            "UPDATE rtv_results_queue SET status='skipped', saved_race_id=?, last_error=NULL, updated_at=? WHERE rtv_race_id=?",
            (match, now_local(), rtv_id),
        )
        con.commit()
        return "skipped", "already %s" % match

    st, d = cli.get("racing/results/%s/%s/%s" % (date, slug, hhmm))
    if st != 200 or not isinstance(d, dict) or not (d.get("race")):
        reason = "HTTP %s" % st
        if isinstance(d, dict) and d.get("_error"):
            reason = str(d.get("_error"))
        con.execute(
            """UPDATE rtv_results_queue SET attempts=attempts+1, last_error=?, updated_at=?,
               status=CASE WHEN attempts+1>=3 THEN 'error' ELSE 'pending' END WHERE rtv_race_id=?""",
            (reason, now_local(), rtv_id),
        )
        con.commit()
        if con.execute("SELECT status FROM rtv_results_queue WHERE rtv_race_id=?", (rtv_id,)).fetchone()[0] == "error":
            append_missing({"logged_at": now_local(), "race_date": date, "course": course or "",
                            "off_time": off_time or "", "rtv_race_id": rtv_id, "reason": reason})
        return "error", reason

    try:
        race_id, race_rec, runners = build_race_records(date, slug, hhmm, d)
    except Exception as e:
        reason = "parse: %s" % e
        con.execute(
            "UPDATE rtv_results_queue SET attempts=attempts+1, last_error=?, status='error', updated_at=? WHERE rtv_race_id=?",
            (reason, now_local(), rtv_id),
        )
        con.commit()
        append_missing({"logged_at": now_local(), "race_date": date, "course": course or "",
                        "off_time": off_time or "", "rtv_race_id": rtv_id, "reason": reason})
        return "error", reason

    if not backup_state["done"]:
        backup_db(backup_state["db"])
        backup_state["done"] = True

    try:
        save_race(con, race_id, race_rec, runners, date)
        con.execute(
            "UPDATE rtv_results_queue SET status='saved', attempts=attempts+1, last_error=NULL, saved_race_id=?, updated_at=? WHERE rtv_race_id=?",
            (race_id, now_local(), rtv_id),
        )
        con.commit()
    except Exception as e:
        con.rollback()
        reason = "save: %s" % e
        con.execute(
            "UPDATE rtv_results_queue SET attempts=attempts+1, last_error=?, status='error', updated_at=? WHERE rtv_race_id=?",
            (reason, now_local(), rtv_id),
        )
        con.commit()
        append_missing({"logged_at": now_local(), "race_date": date, "course": course or "",
                        "off_time": off_time or "", "rtv_race_id": rtv_id, "reason": reason})
        return "error", reason

    # Keep the in-memory skip index up to date for later same-day duplicates
    for tf in (race_rec.get("scheduled_time"), race_rec.get("actual_off_time")):
        tf = str(tf)[:5] if tf not in (None, "") else None
        if tf and ":" in tf:
            existing.setdefault((date, norm_course(course), tf), race_id)
    n_cmt = sum(1 for r in runners if r.get("comment"))
    return "saved", "runners=%s comments=%s" % (len(runners), n_cmt)


def finish_day(con, date):
    pending = con.execute(
        "SELECT COUNT(*) FROM rtv_results_queue WHERE race_date=? AND status='pending'", (date,)
    ).fetchone()[0]
    if pending:
        return pending
    saved, skipped, missing = con.execute(
        """SELECT
             SUM(CASE WHEN status='saved' THEN 1 ELSE 0 END),
             SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END),
             SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)
           FROM rtv_results_queue WHERE race_date=?""",
        (date,),
    ).fetchone()
    con.execute(
        "UPDATE rtv_results_days SET status='done', saved=?, skipped=?, missing=?, last_error=NULL, updated_at=? WHERE race_date=?",
        (saved or 0, skipped or 0, missing or 0, now_local(), date),
    )
    con.commit()
    return 0


def run_day(con, cli, date, countries, existing, backup_state, deadline=None, verbose=True):
    row = con.execute("SELECT status FROM rtv_results_days WHERE race_date=?", (date,)).fetchone()
    if row is None or row[0] in ("pending",) or (
        row[0] != "done" and con.execute(
            "SELECT COUNT(*) FROM rtv_results_queue WHERE race_date=?", (date,)
        ).fetchone()[0] == 0
    ):
        try:
            m, r = list_day(con, cli, date, countries)
        except Exception as e:
            log("%s: day list failed: %s — logging and continuing" % (date, e))
            con.execute(
                """INSERT INTO rtv_results_days(race_date,status,last_error,updated_at) VALUES(?,?,?,?)
                   ON CONFLICT(race_date) DO UPDATE SET status='error', last_error=excluded.last_error, updated_at=excluded.updated_at""",
                (date, "error", str(e), now_local()),
            )
            con.commit()
            append_missing({"logged_at": now_local(), "race_date": date, "course": "", "off_time": "",
                            "rtv_race_id": "", "reason": "day_list: %s" % e})
            return True
        if verbose:
            log("%s: %s GB/IRE meetings, %s races listed" % (date, m, r))
        if r == 0:
            con.execute(
                "UPDATE rtv_results_days SET status='done', saved=0, skipped=0, missing=0, last_error=?, updated_at=? WHERE race_date=?",
                ("NO_RACING", now_local(), date),
            )
            con.commit()
            return True
    rows = con.execute(
        """SELECT rtv_race_id,race_date,track_slug,off_hhmm,course,off_time
           FROM rtv_results_queue WHERE race_date=? AND status='pending' ORDER BY off_hhmm""",
        (date,),
    ).fetchall()
    for row in rows:
        if deadline and time.time() > deadline:
            return False
        if os.path.exists(STOP_FILE):
            return False
        try:
            status, info = process_race(con, cli, row, existing, backup_state)
        except Blocked:
            raise
        except Exception as e:
            status, info = "error", "unexpected: %s" % e
            try:
                con.rollback()
            except Exception:
                pass
            # Do not clobber a race that was already committed as saved
            already_saved = False
            try:
                qst = con.execute("SELECT status FROM rtv_results_queue WHERE rtv_race_id=?", (row[0],)).fetchone()
                already_saved = bool(qst and qst[0] == "saved")
            except Exception:
                already_saved = False
            if already_saved:
                status, info = "saved", "saved (post-write warning: %s)" % e
            else:
                append_missing({"logged_at": now_local(), "race_date": date, "course": row[4] or "",
                                "off_time": row[5] or "", "rtv_race_id": row[0], "reason": info})
                try:
                    con.execute(
                        "UPDATE rtv_results_queue SET status='error', last_error=?, attempts=attempts+1, updated_at=? WHERE rtv_race_id=?",
                        (info, now_local(), row[0]),
                    )
                    con.commit()
                except Exception:
                    pass
        if verbose:
            log("  %s %s %s -> %s %s" % (row[1], row[4] or row[2], row[5], status, info))
        if cli.errors >= 10:
            log("10 consecutive request errors — will keep going after a short pause")
            time.sleep(30)
            cli.errors = 0
    finish_day(con, date)
    return True


def daterange(a, b):
    d = dt.date.fromisoformat(a)
    e = dt.date.fromisoformat(b)
    while d <= e:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def tail_log(n=15):
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except Exception:
        return []


def missing_count():
    if not os.path.exists(MISSING_FILE):
        return 0
    try:
        with open(MISSING_FILE, "r", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        return max(0, len(rows) - 1) if rows else 0
    except Exception:
        return 0


def status(con):
    print("== Racing TV results backfill ==")
    try:
        for r in con.execute("PRAGMA database_list").fetchall():
            if r[1] == "main":
                print("database :", r[2] or "(memory)")
                break
    except Exception:
        pass
    cols = [r[1] for r in con.execute("PRAGMA table_info(races)")]
    if "source" in cols:
        print("-- races by source --")
        for src, c, mn, mx in con.execute(
            "SELECT COALESCE(source,'sportinglife'), COUNT(*), MIN(race_date), MAX(race_date) FROM races GROUP BY COALESCE(source,'sportinglife')"
        ):
            print("  %-14s %7d   %s .. %s" % (src, c, mn, mx))
    else:
        n = con.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        print("  races (no source column yet):", n)
    total = con.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    runners = con.execute("SELECT COUNT(*) FROM runners").fetchone()[0]
    print("  total races   :", total)
    print("  total runners :", runners)
    rtv_n = 0
    latest_rtv = None
    if "source" in cols:
        row = con.execute("SELECT COUNT(*), MIN(race_date), MAX(race_date) FROM races WHERE source='rtv'").fetchone()
        rtv_n, _, latest_rtv = row
    print("  RTV races saved :", rtv_n)
    print("  latest RTV date :", latest_rtv or "(none yet)")
    latest_any = con.execute("SELECT MAX(race_date) FROM races").fetchone()[0]
    print("  latest any date :", latest_any)
    print("-- backfill days --")
    try:
        for st, c, mn, mx in con.execute("SELECT status,COUNT(*),MIN(race_date),MAX(race_date) FROM rtv_results_days GROUP BY status"):
            print("  %s  %d  %s .. %s" % (st, c, mn, mx))
        row = con.execute("SELECT SUM(saved),SUM(skipped),SUM(missing) FROM rtv_results_days").fetchone()
        print("  saved=%s  skipped=%s  missing_races_in_days=%s" % row)
    except sqlite3.Error:
        print("  (no rtv_results_days yet)")
    print("-- queue --")
    try:
        for st, c in con.execute("SELECT status,COUNT(*) FROM rtv_results_queue GROUP BY status"):
            print("  %s  %d" % (st, c))
    except sqlite3.Error:
        print("  (no rtv_results_queue yet)")
    mc = missing_count()
    print("  MISSING_DATES.csv rows :", mc)
    print("  missing file :", MISSING_FILE)
    print("-- last log lines --")
    lines = tail_log(15)
    if not lines:
        print("  (no log yet)", LOG_FILE)
    else:
        for ln in lines:
            print("  " + ln)


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Racing TV results backfill into racing_history.sqlite")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=None, help="inclusive end date (default: yesterday)")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests (min 1)")
    ap.add_argument("--countries", default="GBR,IRE")
    ap.add_argument("--max-runtime-minutes", type=float, default=0)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--test-day", metavar="YYYY-MM-DD")
    ap.add_argument("--create-core", action="store_true", help="create empty races/runners tables (for tests)")
    args = ap.parse_args(argv)

    _ensure_work_dir()
    end = args.end or yesterday()
    countries = {c.strip().upper() for c in args.countries.split(",") if c.strip()}

    if not os.path.exists(args.db) and not args.create_core and not args.test_day:
        print("Database not found:", args.db)
        print("This script writes into data\\racing_history.sqlite (the Sporting Life history).")
        return 1

    con = connect(args.db, create_core=args.create_core or (args.test_day and not os.path.exists(args.db)))

    if args.status:
        status(con)
        return 0

    backup_state = {"done": False, "db": args.db}
    log("loading existing race index (to skip races already saved)...")
    existing, n_exist = load_existing_index(con)
    log("indexed %s existing races (%s time keys)" % (n_exist, len(existing)))

    cli = Client(args.delay)

    if args.test_day:
        # Re-queue pending work for that day, but do not delete already-saved rtv races.
        con.execute("UPDATE rtv_results_queue SET status='pending', attempts=0, last_error=NULL WHERE race_date=? AND status!='saved' AND status!='skipped'", (args.test_day,))
        con.execute("DELETE FROM rtv_results_days WHERE race_date=?", (args.test_day,))
        con.commit()
        log("test-day %s delay=%ss" % (args.test_day, cli.delay))
        run_day(con, cli, args.test_day, countries, existing, backup_state)
        drow = con.execute("SELECT status,meetings,listed,saved,skipped,missing FROM rtv_results_days WHERE race_date=?", (args.test_day,)).fetchone()
        log("test-day result: %s" % (drow,))
        # sample comment
        sample = con.execute(
            "SELECT r.race_id, r.data FROM races r WHERE r.source='rtv' AND r.race_date=? LIMIT 1",
            (args.test_day,),
        ).fetchone()
        if sample:
            rd = json.loads(sample[1])
            ru = con.execute("SELECT data FROM runners WHERE race_id=? LIMIT 3", (sample[0],)).fetchall()
            log("sample race: %s %s %s %s" % (rd.get("track"), rd.get("scheduled_time"), rd.get("race_name"), rd.get("winning_time_raw")))
            for (blob,) in ru:
                j = json.loads(blob)
                if j.get("comment"):
                    log("sample comment: %s — %s" % (j.get("horse"), j.get("comment")))
                    break
        status(con)
        return 0

    deadline = time.time() + args.max_runtime_minutes * 60 if args.max_runtime_minutes else None
    log("backfill %s..%s delay=%ss countries=%s" % (args.start, end, cli.delay, ",".join(sorted(countries))))
    try:
        for date in daterange(args.start, end):
            row = con.execute("SELECT status FROM rtv_results_days WHERE race_date=?", (date,)).fetchone()
            if row and row[0] == "done":
                continue
            if os.path.exists(STOP_FILE):
                log("STOP file found, exiting")
                return 2
            if deadline and time.time() > deadline:
                log("time limit reached")
                return 2
            try:
                complete = run_day(con, cli, date, countries, existing, backup_state, deadline)
            except Blocked as e:
                log("BLOCKED by Racing TV (%s); stopping so we do not keep hitting the API. Resume later with the same command." % e)
                return 3
            if not complete:
                log("stopping mid-day (time limit / STOP); safe to resume")
                return 2
            drow = con.execute(
                "SELECT status,listed,saved,skipped,missing FROM rtv_results_days WHERE race_date=?", (date,)
            ).fetchone()
            if drow:
                log("%s %s: listed=%s saved=%s skipped=%s missing=%s" % (date, drow[0], drow[1], drow[2], drow[3], drow[4]))
    finally:
        con.close()
    log("range finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
