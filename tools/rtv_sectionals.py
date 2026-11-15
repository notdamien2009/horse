#!/usr/bin/env python3
"""
Racing TV sectionals collector  ->  data/sectionals.sqlite

Pulls per-horse, per-furlong sectional times and RaceiQ metrics for UK (GBR)
and Irish (IRE) races from the public JSON API that racingtv.com's own
results pages call (no login, no API key):

  day list   : https://api.racingtv.com/racing/results/list/{YYYY-MM-DD}
  sectionals : https://api.racingtv.com/racing/iq-results/{date}/{track}/{HHMM}/sectional
  RaceiQ     : https://api.racingtv.com/racing/iq-results/{date}/{track}/{HHMM}/metrics
  (optional) : https://api.racingtv.com/racing/results/{date}/{track}/{HHMM}   (--with-results)

Coverage (per Racing TV): GB from March 2023, Ireland from Jan 2024. Races
without tracking data return 404 or empty sectionals and are marked no_data.

Usage:
  python tools/rtv_sectionals.py --status
  python tools/rtv_sectionals.py --test-day 2024-06-15
  python tools/rtv_sectionals.py --start 2023-03-01 --end 2026-10-31 --delay 3
  python tools/rtv_sectionals.py --match-sl        (link to Sporting Life race_id, read-only)

Exit codes: 0 = range finished, 2 = stopped by time limit / STOP file (resume later),
            3 = blocked (repeated 403/429), 4 = too many errors.
Never writes to racing_history.sqlite (opened read-only for matching only).
"""
import argparse, datetime as dt, json, os, re, sqlite3, sys, time, zlib
import urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, "data", "sectionals.sqlite")
SL_DB = os.path.join(ROOT, "data", "racing_history.sqlite")
STOP_FILE = os.path.join(ROOT, "data", "sectionals_backfill", "STOP")
API = "https://api.racingtv.com/"
MIN_DELAY = 1.0
IRE_FROM = "2024-01-01"  # Irish tracking data starts Jan 2024; earlier IRE races are listed but not fetched
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Requested-With": "racingtv-web/5.6.0",
    "Origin": "https://www.racingtv.com",
    "Referer": "https://www.racingtv.com/",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS days(
  race_date TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
  meetings INTEGER, races INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS race_queue(
  rtv_race_id INTEGER PRIMARY KEY, race_date TEXT NOT NULL, track_slug TEXT NOT NULL,
  off_hhmm TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_queue_status ON race_queue(status, race_date);
CREATE TABLE IF NOT EXISTS raw_json(
  rtv_race_id INTEGER NOT NULL, endpoint TEXT NOT NULL, http_status INTEGER,
  fetched_at TEXT, json_zlib BLOB, PRIMARY KEY(rtv_race_id, endpoint));
CREATE TABLE IF NOT EXISTS rtv_races(
  rtv_race_id INTEGER PRIMARY KEY, race_date TEXT, course TEXT, course_slug TEXT,
  country TEXT, off_time TEXT, start_time_scheduled TEXT, race_name TEXT, title_full TEXT,
  race_type TEXT, race_class TEXT, distance_text TEXT, distance_yards INTEGER, going TEXT,
  runner_count INTEGER, time_index_score REAL, meeting_average_time_index REAL,
  win_time_vs_par REAL, winner_time_s REAL, sectional_count INTEGER,
  has_sectionals INTEGER, has_raceiq INTEGER, sl_race_id TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_rtv_races_date ON rtv_races(race_date, course_slug, off_time);
CREATE TABLE IF NOT EXISTS rtv_runners(
  rtv_race_id INTEGER NOT NULL, rtv_runner_id INTEGER NOT NULL, horse_name TEXT,
  cloth_number INTEGER, barrier_number INTEGER, finish_position INTEGER, finish_text TEXT,
  amended_position INTEGER, between_distance TEXT, finishing_time_s REAL,
  finishing_speed_pct REAL, total_time_s REAL, n_sections INTEGER,
  PRIMARY KEY(rtv_race_id, rtv_runner_id));
CREATE TABLE IF NOT EXISTS rtv_sectionals(
  rtv_race_id INTEGER NOT NULL, rtv_runner_id INTEGER NOT NULL, sector_number INTEGER NOT NULL,
  sector_name TEXT, sector_time REAL, cumulative_time REAL, position INTEGER,
  behind_leader REAL, pace_category TEXT, time_percentile REAL,
  PRIMARY KEY(rtv_race_id, rtv_runner_id, sector_number));
CREATE TABLE IF NOT EXISTS rtv_raceiq(
  rtv_race_id INTEGER NOT NULL, rtv_runner_id INTEGER NOT NULL, metric_group TEXT NOT NULL,
  metric TEXT NOT NULL, title TEXT, value REAL, value_text TEXT, unit TEXT, rank INTEGER,
  average REAL, percentage REAL,
  PRIMARY KEY(rtv_race_id, rtv_runner_id, metric_group, metric));
"""

def now():
    return dt.datetime.now().isoformat(timespec="seconds")

def log(*a):
    print(f"{now()} " + " ".join(str(x) for x in a), flush=True)

def fnum(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    m = re.search(r"-?\d+(?:\.\d+)?", str(x))
    return float(m.group()) if m else None

def parse_time_s(s):
    """'1m, 58.7s' / '38.98s' / '4m 33s' -> seconds"""
    if not s: return None
    m = re.match(r"\s*(?:(\d+)m,?\s*)?(?:(\d+(?:\.\d+)?)s)?\s*$", str(s))
    if not m or (m.group(1) is None and m.group(2) is None): return None
    return int(m.group(1) or 0) * 60 + float(m.group(2) or 0)

def parse_distance(title_full):
    """'... 4YO+ 2m 1f 24y Winner: ...' -> ('2m 1f 24y', yards)"""
    if not title_full: return None, None
    head = title_full.split(" Winner")[0]
    m = re.search(r"(?:(\d+)m)?\s*(?:(\d+)f)?\s*(?:(\d+)y)?\s*$", head.strip())
    if not m or not any(m.groups()): return None, None
    mi, fu, ya = (int(g) if g else 0 for g in m.groups())
    return m.group(0).strip(), mi * 1760 + fu * 220 + ya

def parse_class(title_full):
    m = re.search(r"\(Class (\d)\)", title_full or "")
    return m.group(1) if m else None

def norm_course(name):
    """'Sandown Park'/'Sandown', 'Epsom Downs'/'Epsom', 'Bangor-on-Dee'/'Bangor On Dee', 'The Curragh'/'Curragh' -> same key"""
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    words = [w for w in re.split(r"[^a-z]+", n) if w and w not in ("park", "the", "downs", "city", "racecourse", "aw")]
    return "".join(words)

class Blocked(Exception): pass

class Client:
    def __init__(self, delay):
        self.delay = max(MIN_DELAY, delay)
        self.last = 0.0
        self.blocks = 0
        self.errors = 0

    def get(self, path):
        """returns (status, parsed_json_or_None). Raises Blocked after repeated 403/429."""
        wait = self.delay - (time.time() - self.last)
        if wait > 0: time.sleep(wait)
        self.last = time.time()
        req = urllib.request.Request(API + path, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read(); status = r.status
        except urllib.error.HTTPError as e:
            status = e.code; body = e.read() if hasattr(e, "read") else b""
        except Exception as e:
            self.errors += 1
            return -1, {"_error": repr(e)}
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = None
        # API puts its own status in meta.status as well
        if isinstance(data, dict) and isinstance(data.get("meta"), dict):
            status = data["meta"].get("status", status) or status
        if status in (403, 429):
            self.blocks += 1
            log(f"HTTP {status} on {path} (block count {self.blocks})")
            if self.blocks >= 3:
                raise Blocked(f"HTTP {status} x{self.blocks}")
            time.sleep(60 * self.blocks)
            return status, data
        if status >= 500 or data is None:
            self.errors += 1
        else:
            self.blocks = 0
            self.errors = 0
        return status, data

def connect(db):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = sqlite3.connect(db, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con

def save_raw(con, race_id, endpoint, status, data):
    con.execute("INSERT OR REPLACE INTO raw_json VALUES(?,?,?,?,?)",
                (race_id, endpoint, status, now(),
                 zlib.compress(json.dumps(data, separators=(",", ":")).encode("utf-8"), 6)))

# ---------------------------------------------------------------- day listing
def list_day(con, cli, date, countries):
    st, d = cli.get(f"racing/results/list/{date}")
    if st != 200 or not isinstance(d, dict):
        raise RuntimeError(f"day list {date} -> HTTP {st}")
    meetings = 0; races = 0
    for m in d.get("meetings") or []:
        tr = m.get("track") or {}
        cc = ((tr.get("country_code") or {}).get("racing") or "").upper()
        if cc not in countries: continue
        meetings += 1
        slug = (tr.get("slug") or "").strip("/")
        for r in m.get("completed_races") or []:
            sts = r.get("start_time_scheduled") or ""
            if "T" not in sts: continue
            hhmm = sts.split("T")[1][:5]
            dist_txt, yards = parse_distance(r.get("title_full"))
            races += 1
            con.execute("""INSERT INTO rtv_races(rtv_race_id,race_date,course,course_slug,country,off_time,
                 start_time_scheduled,race_name,title_full,race_type,race_class,distance_text,distance_yards,going,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(rtv_race_id) DO UPDATE SET race_date=excluded.race_date,course=excluded.course,
                 course_slug=excluded.course_slug,country=excluded.country,off_time=excluded.off_time,
                 start_time_scheduled=excluded.start_time_scheduled,race_name=excluded.race_name,
                 title_full=excluded.title_full,race_type=excluded.race_type,race_class=excluded.race_class,
                 distance_text=excluded.distance_text,distance_yards=excluded.distance_yards,going=excluded.going""",
                (r["id"], date, tr.get("name"), slug, cc, hhmm, sts, r.get("title"), r.get("title_full"),
                 r.get("race_type"), parse_class(r.get("title_full")), dist_txt, yards,
                 r.get("track_condition") or m.get("track_condition"), now()))
            qstat = "skipped" if (cc == "IRE" and date < IRE_FROM) else "pending"
            con.execute("INSERT OR IGNORE INTO race_queue(rtv_race_id,race_date,track_slug,off_hhmm,status,updated_at) VALUES(?,?,?,?,?,?)",
                        (r["id"], date, slug, hhmm.replace(":", ""), qstat, now()))
    con.execute("""INSERT INTO days(race_date,status,meetings,races,updated_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(race_date) DO UPDATE SET status='listed',meetings=excluded.meetings,
                   races=excluded.races,updated_at=excluded.updated_at""",
                (date, "listed", meetings, races, now()))
    con.commit()
    return meetings, races

# ---------------------------------------------------------------- per race
def parse_sectional(con, race_id, d):
    race = (d or {}).get("race") or {}
    runners = race.get("runners") or []
    con.execute("DELETE FROM rtv_sectionals WHERE rtv_race_id=?", (race_id,))
    con.execute("DELETE FROM rtv_runners WHERE rtv_race_id=?", (race_id,))
    nsec_total = 0; winner_time = None
    for ru in runners:
        secs = ru.get("sectionals") or []
        tot = None
        for s in secs:
            cum = fnum(s.get("cumulative_sector_time")); beh = fnum(s.get("time_behind_leader"))
            if beh is not None and cum is not None and beh > cum + 0.01:
                beh = None  # upstream glitch seen on some Irish races (raw JSON keeps original)
            con.execute("INSERT OR REPLACE INTO rtv_sectionals VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (race_id, ru["id"], s.get("sector_number"), s.get("sector_name"),
                         fnum(s.get("sector_time")), cum,
                         s.get("sector_position"), beh,
                         s.get("sector_pace_category"), fnum(s.get("sector_time_percentile"))))
            if s.get("cumulative_sector_time") is not None:
                tot = fnum(s.get("cumulative_sector_time"))
        nsec_total += len(secs)
        if ru.get("finish_position") == 1 and tot is not None and winner_time is None:
            winner_time = tot
        con.execute("INSERT OR REPLACE INTO rtv_runners VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (race_id, ru["id"], ru.get("horse_name"), ru.get("cloth_number"), ru.get("barrier_number"),
                     ru.get("finish_position"), ru.get("finish_text"), ru.get("amended_position"),
                     None if ru.get("between_distance") is None else str(ru.get("between_distance")),
                     parse_time_s(ru.get("finishing_time")), fnum(ru.get("finishing_speed_percentage")),
                     tot, len(secs)))
    con.execute("""UPDATE rtv_races SET runner_count=?, time_index_score=?, meeting_average_time_index=?,
                   win_time_vs_par=?, winner_time_s=?, sectional_count=?, has_sectionals=?, updated_at=?
                   WHERE rtv_race_id=?""",
                (len(runners), fnum(race.get("time_index_score")), fnum(race.get("meeting_average_time_index")),
                 fnum(race.get("win_time_vs_par")), winner_time, nsec_total, 1 if nsec_total else 0, now(), race_id))
    return len(runners), nsec_total

def parse_metrics(con, race_id, d):
    con.execute("DELETE FROM rtv_raceiq WHERE rtv_race_id=?", (race_id,))
    n = 0
    for ru in (d or {}).get("runners") or []:
        for grp, metrics in (ru.get("race_iq") or {}).items():
            if not isinstance(metrics, dict): continue
            for key, m in metrics.items():
                if not isinstance(m, dict): continue
                con.execute("INSERT OR REPLACE INTO rtv_raceiq VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (race_id, ru["id"], grp, key, m.get("metric_title"), fnum(m.get("value")),
                             None if m.get("value") is None else str(m.get("value")), m.get("unit"),
                             m.get("rank"), fnum(m.get("average")), fnum(m.get("percentage"))))
                n += 1
    con.execute("UPDATE rtv_races SET has_raceiq=? WHERE rtv_race_id=?", (1 if n else 0, race_id))
    return n

def process_race(con, cli, row, with_metrics, with_results):
    race_id, date, slug, hhmm = row
    base = f"racing/iq-results/{date}/{slug}/{hhmm}"
    st, d = cli.get(base + "/sectional")
    if st == 404:
        save_raw(con, race_id, "sectional", st, d)
        con.execute("UPDATE rtv_races SET has_sectionals=0, has_raceiq=0 WHERE rtv_race_id=?", (race_id,))
        status, info = "no_data", "404"
    elif st == 200 and isinstance(d, dict):
        save_raw(con, race_id, "sectional", st, d)
        nrun, nsec = parse_sectional(con, race_id, d)
        nm = 0
        if with_metrics:
            st2, d2 = cli.get(base + "/metrics")
            if st2 == 200 and isinstance(d2, dict):
                save_raw(con, race_id, "metrics", st2, d2)
                nm = parse_metrics(con, race_id, d2)
        if with_results:
            st3, d3 = cli.get(f"racing/results/{date}/{slug}/{hhmm}")
            if st3 == 200: save_raw(con, race_id, "results", st3, d3)
        status = "done" if (nsec or nm) else "no_data"
        info = f"runners={nrun} sectors={nsec} raceiq={nm}"
    else:
        con.execute("""UPDATE race_queue SET attempts=attempts+1, last_error=?, updated_at=?,
                       status=CASE WHEN attempts+1>=3 THEN 'error' ELSE 'pending' END WHERE rtv_race_id=?""",
                    (f"HTTP {st}", now(), race_id))
        con.commit()
        return "error", f"HTTP {st}"
    con.execute("UPDATE race_queue SET status=?, attempts=attempts+1, last_error=NULL, updated_at=? WHERE rtv_race_id=?",
                (status, now(), race_id))
    con.commit()
    return status, info

def finish_day_if_complete(con, date):
    left = con.execute("SELECT COUNT(*) FROM race_queue WHERE race_date=? AND status='pending'", (date,)).fetchone()[0]
    if left == 0:
        con.execute("UPDATE days SET status='done', updated_at=? WHERE race_date=?", (now(), date))
        con.commit()
    return left

def run_day(con, cli, date, countries, with_metrics, with_results, deadline=None, verbose=True):
    if con.execute("SELECT status FROM days WHERE race_date=?", (date,)).fetchone() in (None, ("pending",)):
        m, r = list_day(con, cli, date, countries)
        if verbose: log(f"{date}: {m} GB/IRE meetings, {r} races listed")
    rows = con.execute("SELECT rtv_race_id,race_date,track_slug,off_hhmm FROM race_queue WHERE race_date=? AND status='pending' ORDER BY off_hhmm",
                       (date,)).fetchall()
    for row in rows:
        if deadline and time.time() > deadline: return False
        if os.path.exists(STOP_FILE): return False
        status, info = process_race(con, cli, row, with_metrics, with_results)
        if verbose: log(f"  {row[1]} {row[2]} {row[3]} -> {status} {info}")
        if cli.errors >= 10:
            raise RuntimeError("10 consecutive errors")
    finish_day_if_complete(con, date)
    return True

# ---------------------------------------------------------------- Sporting Life matching (read-only)
def match_sl(con, sl_db=SL_DB, verbose=True):
    if not os.path.exists(sl_db):
        if verbose: log("no racing_history.sqlite found, skipping SL match"); return 0
    try:
        sl = sqlite3.connect(f"file:{sl_db}?mode=ro", uri=True, timeout=10)
        idx = {}
        for race_id, data in sl.execute("SELECT race_id, data FROM races"):
            try: j = json.loads(data)
            except Exception: continue
            key = (j.get("date"), norm_course(j.get("track")), (j.get("scheduled_time") or "")[:5])
            idx.setdefault(key, str(race_id))
        sl.close()
    except sqlite3.Error as e:
        log(f"SL match skipped (database busy?): {e}"); return 0
    n = 0
    for rid, date, course, off in con.execute(
            "SELECT rtv_race_id,race_date,course,off_time FROM rtv_races WHERE sl_race_id IS NULL").fetchall():
        k = (date, norm_course(course), off)
        sid = idx.get(k)
        if sid is None:  # try minute +-1..5 for late time changes
            hh, mm = map(int, off.split(":"))
            for delta in (5, -5, 1, -1, 2, -2, 3, -3, 4, -4, 10, -10, 15, -15):
                t = (hh * 60 + mm + delta)
                sid = idx.get((date, norm_course(course), f"{t // 60:02d}:{t % 60:02d}"))
                if sid: break
        if sid:
            con.execute("UPDATE rtv_races SET sl_race_id=? WHERE rtv_race_id=?", (sid, rid)); n += 1
    con.commit()
    if verbose: log(f"Sporting Life match: linked {n} more races")
    return n

# ---------------------------------------------------------------- reporting
def status(con):
    q = lambda s, *a: con.execute(s, a).fetchone()
    print("== days ==")
    for st, c, mn, mx in con.execute("SELECT status,COUNT(*),MIN(race_date),MAX(race_date) FROM days GROUP BY status"):
        print(f"  {st:8s} {c:6d}  {mn} .. {mx}")
    print("== race queue ==")
    for st, c in con.execute("SELECT status,COUNT(*) FROM race_queue GROUP BY status"):
        print(f"  {st:8s} {c:7d}")
    print("== parsed ==")
    print("  races with sectionals:", q("SELECT COUNT(*) FROM rtv_races WHERE has_sectionals=1")[0])
    print("  races with RaceiQ    :", q("SELECT COUNT(*) FROM rtv_races WHERE has_raceiq=1")[0])
    print("  runners              :", q("SELECT COUNT(*) FROM rtv_runners")[0])
    print("  sectional rows       :", q("SELECT COUNT(*) FROM rtv_sectionals")[0])
    print("  RaceiQ metric rows   :", q("SELECT COUNT(*) FROM rtv_raceiq")[0])
    print("  linked to SL race_id :", q("SELECT COUNT(*) FROM rtv_races WHERE sl_race_id IS NOT NULL")[0])
    print("  by country (races / with sectionals):")
    for cc, c, s in con.execute("SELECT country,COUNT(*),SUM(has_sectionals=1) FROM rtv_races GROUP BY country"):
        print(f"    {cc}: {c} / {s}")
    last = q("SELECT MAX(race_date) FROM days WHERE status='done'")[0]
    print("  latest completed day :", last)

def progress_count(con):
    return con.execute("SELECT (SELECT COUNT(*) FROM race_queue WHERE status!='pending')+(SELECT COUNT(*) FROM days WHERE status='done')").fetchone()[0]

def test_report(con, date):
    print(f"\n==== test report {date} ====")
    rows = con.execute("""SELECT rtv_race_id,course,off_time,race_type,distance_text,runner_count,sectional_count,
                          winner_time_s,time_index_score,has_raceiq,sl_race_id FROM rtv_races WHERE race_date=? ORDER BY course,off_time""",
                       (date,)).fetchall()
    for r in rows:
        print("  %-18s %s %-8s %-11s run=%-3s secRows=%-4s winTime=%-7s TI=%-5s iq=%s sl=%s" % (r[1][:18], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]))
    # consistency check: sum of winner's sector times vs winner cumulative
    bad = 0; checked = 0
    for (rid,) in con.execute("SELECT rtv_race_id FROM rtv_races WHERE race_date=? AND has_sectionals=1", (date,)).fetchall():
        w = con.execute("SELECT rtv_runner_id,total_time_s FROM rtv_runners WHERE rtv_race_id=? AND finish_position=1 AND n_sections>0", (rid,)).fetchone()
        if not w: continue
        s = con.execute("SELECT SUM(sector_time) FROM rtv_sectionals WHERE rtv_race_id=? AND rtv_runner_id=?", (rid, w[0])).fetchone()[0]
        checked += 1
        if s is None or w[1] is None or abs(s - w[1]) > 0.3: bad += 1
    print(f"  winner sector-sum check: {checked - bad}/{checked} races within 0.3s of final cumulative time")
    ex = con.execute("""SELECT r.rtv_race_id,r.course,r.off_time,r.distance_text,r.winner_time_s,u.rtv_runner_id,u.horse_name
                        FROM rtv_races r JOIN rtv_runners u ON u.rtv_race_id=r.rtv_race_id AND u.finish_position=1
                        WHERE r.race_date=? AND r.has_sectionals=1 AND u.n_sections>0 ORDER BY (r.race_type='Flat') DESC, (r.country='GBR') DESC, r.off_time LIMIT 1""", (date,)).fetchone()
    if ex:
        print(f"\n  Sample winner: {ex[6]}  ({ex[1]} {ex[2]}, {ex[3]}, winner time {ex[4]}s)")
        for s in con.execute("SELECT sector_name,sector_time,cumulative_time,position,behind_leader,pace_category FROM rtv_sectionals WHERE rtv_race_id=? AND rtv_runner_id=? ORDER BY sector_number", (ex[0], ex[5])):
            print("    %-7s sec=%-6s cum=%-7s pos=%-3s behind=%-5s %s" % s)
        for m in con.execute("SELECT metric_group,metric,value_text,unit,rank FROM rtv_raceiq WHERE rtv_race_id=? AND rtv_runner_id=?", (ex[0], ex[5])):
            print("    RaceiQ %-12s %-24s %-8s %-10s rank %s" % m)

def daterange(a, b):
    d = dt.date.fromisoformat(a); e = dt.date.fromisoformat(b)
    while d <= e:
        yield d.isoformat(); d += dt.timedelta(days=1)

def main():
    ap = argparse.ArgumentParser(description="Racing TV sectionals collector")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--start", default="2023-03-01")
    ap.add_argument("--end", default="2026-10-31")
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between requests (min 1)")
    ap.add_argument("--countries", default="GBR,IRE")
    ap.add_argument("--no-metrics", action="store_true", help="skip RaceiQ metrics call (1 fewer request per race)")
    ap.add_argument("--with-results", action="store_true", help="also save raw results page JSON (1 extra request per race)")
    ap.add_argument("--ire-from", default="2024-01-01", help="don't fetch Irish races before this date (no data upstream)")
    ap.add_argument("--max-runtime-minutes", type=float, default=0)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--count", action="store_true", help="print a progress number (for the loop script)")
    ap.add_argument("--test-day", metavar="YYYY-MM-DD")
    ap.add_argument("--match-sl", action="store_true")
    a = ap.parse_args()
    con = connect(a.db)
    global IRE_FROM
    IRE_FROM = a.ire_from
    countries = {c.strip().upper() for c in a.countries.split(",") if c.strip()}

    if a.count:
        print(progress_count(con)); return 0
    if a.status:
        status(con); return 0
    if a.match_sl:
        match_sl(con); return 0

    cli = Client(a.delay)
    if a.test_day:
        con.execute("UPDATE race_queue SET status='pending', attempts=0 WHERE race_date=?", (a.test_day,))
        con.execute("DELETE FROM days WHERE race_date=?", (a.test_day,))
        con.commit()
        run_day(con, cli, a.test_day, countries, not a.no_metrics, a.with_results)
        match_sl(con)
        test_report(con, a.test_day)
        return 0

    deadline = time.time() + a.max_runtime_minutes * 60 if a.max_runtime_minutes else None
    log(f"backfill {a.start}..{a.end} delay={cli.delay}s metrics={not a.no_metrics}")
    try:
        for date in daterange(a.start, a.end):
            row = con.execute("SELECT status FROM days WHERE race_date=?", (date,)).fetchone()
            if row and row[0] == "done": continue
            if os.path.exists(STOP_FILE):
                log("STOP file found, exiting"); return 2
            if deadline and time.time() > deadline:
                log("time limit reached"); return 2
            try:
                complete = run_day(con, cli, date, countries, not a.no_metrics, a.with_results, deadline)
            except RuntimeError as e:
                log(f"{date}: {e}")
                if cli.errors >= 10: log("too many consecutive errors, exiting"); return 4
                continue
            if not complete:
                log("stopping mid-day (time limit / STOP)"); return 2
            r = con.execute("SELECT races FROM days WHERE race_date=?", (date,)).fetchone()
            s = con.execute("SELECT COUNT(*) FROM rtv_races WHERE race_date=? AND has_sectionals=1", (date,)).fetchone()[0]
            log(f"{date} done: {r[0] if r else 0} races, {s} with sectionals")
    except Blocked as e:
        log(f"BLOCKED by Racing TV ({e}); stopping. Try again later."); return 3
    finally:
        try: match_sl(con, verbose=False)
        except Exception as e: log(f"SL match error: {e}")
    log("range finished")
    return 0

if __name__ == "__main__":
    sys.exit(main())
