"""Scrape today's UK & Irish racecards from Sporting Life into data\\cards.sqlite.

Usage:  python tools\\sl_cards.py            (today)
        python tools\\sl_cards.py --date 2026-11-17
        python tools\\sl_cards.py --all-countries   (keep FR/USA etc too)

Polite: >=3s between requests, retries on 5xx / network errors.
Each run replaces that date's cards (re-run any time for non-runners / odds).
"""
import argparse, datetime as dt, json, os, re, sqlite3, sys, time
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "cards.sqlite")
BASE = "https://www.sportinglife.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UKIRE = {"ENG", "SCO", "WAL", "IRE", "NI", "GB", "UK"}
DELAY = 3.0
_last = [0.0]
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)          # (IRE) (GB) (FR) (USA)
    return re.sub(r"[^a-z0-9]", "", s)


def get_json(path, tries=4):
    url = path if path.startswith("http") else BASE + path
    for i in range(tries):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.get(url, timeout=30)
            if r.status_code >= 500 or r.status_code == 429:
                raise IOError(f"HTTP {r.status_code}")
            r.raise_for_status()
            m = NEXT_RE.search(r.text)
            if not m:
                raise IOError("no __NEXT_DATA__ on page")
            return json.loads(m.group(1))["props"]["pageProps"], r.url
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"   retry {i+1} for {url}: {e}")
            time.sleep(5 * (i + 1))


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings(meeting_id INTEGER PRIMARY KEY, date TEXT, course TEXT,
  country TEXT, going TEXT, surface TEXT, weather TEXT);
CREATE TABLE IF NOT EXISTS races(race_id INTEGER PRIMARY KEY, meeting_id INTEGER, date TEXT, time TEXT,
  course TEXT, name TEXT, race_class TEXT, distance TEXT, going TEXT, age_band TEXT, surface TEXT,
  handicap INTEGER, ride_count INTEGER, stage TEXT, betting_forecast TEXT, verdict TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS runners(ride_id INTEGER PRIMARY KEY, race_id INTEGER, date TEXT,
  cloth INTEGER, draw INTEGER, status TEXT, horse TEXT, horse_norm TEXT, sl_horse_id INTEGER,
  age INTEGER, sex TEXT, weight TEXT, weight_lb INTEGER, official_rating INTEGER, jockey TEXT,
  jockey_claim INTEGER, trainer TEXT, owner TEXT, headgear TEXT, form TEXT, last_ran_days INTEGER,
  odds TEXT, forecast_odds TEXT, runs INTEGER, wins INTEGER, places INTEGER, silk TEXT, commentary TEXT);
CREATE TABLE IF NOT EXISTS prev_runs(ride_id INTEGER, horse_norm TEXT, n INTEGER, sl_race_id INTEGER,
  date TEXT, course TEXT, distance TEXT, run_type TEXT, going TEXT, race_class TEXT, position INTEGER,
  outcome TEXT, runners INTEGER, weight TEXT, bha INTEGER, odds TEXT, comment TEXT);
CREATE INDEX IF NOT EXISTS ix_run_race ON runners(race_id);
CREATE INDEX IF NOT EXISTS ix_prev_ride ON prev_runs(ride_id);
CREATE TABLE IF NOT EXISTS scrape_log(date TEXT, ts TEXT, meetings INTEGER, races INTEGER, runners INTEGER);
"""


def wt_lb(w):
    m = re.match(r"(\d+)-(\d+)", w or "")
    return int(m.group(1)) * 14 + int(m.group(2)) if m else None


def parse_forecast(s):
    out = {}
    for name, odds in re.findall(r"([^,(]+?)\s*\(([^)]+)\)", s or ""):
        out[norm_name(name)] = odds.strip()
    return out


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--all-countries", action="store_true")
    a = ap.parse_args()
    date = a.date
    print(f"Sporting Life racecards for {date}")
    pp, final = get_json(f"/racing/racecards/{date}")
    meetings = [m for m in pp.get("meetings", []) if m["meeting_summary"].get("date") == date]
    if not meetings:
        got = {m["meeting_summary"].get("date") for m in pp.get("meetings", [])}
        print(f"No cards for {date} on Sporting Life yet (site returned {sorted(got)}). "
              "Cards for tomorrow usually appear after declarations.")
        return 1
    if not a.all_countries:
        meetings = [m for m in meetings
                    if m["meeting_summary"]["course"]["country"].get("short_name", "").upper() in UKIRE]
    print(f"{len(meetings)} UK/IRE meetings: " +
          ", ".join(m["meeting_summary"]["course"]["name"] for m in meetings))

    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    # replace this date
    olds = [r[0] for r in con.execute("SELECT ride_id FROM runners WHERE date=?", (date,))]
    con.executemany("DELETE FROM prev_runs WHERE ride_id=?", [(x,) for x in olds])
    for t in ("runners", "races", "meetings"):
        con.execute(f"DELETE FROM {t} WHERE date=?", (date,))

    n_r = n_run = 0
    for m in meetings:
        ms = m["meeting_summary"]
        mid = ms["meeting_reference"]["id"]
        course = ms["course"]["name"]
        con.execute("INSERT OR REPLACE INTO meetings VALUES(?,?,?,?,?,?,?)",
                    (mid, date, course, ms["course"]["country"].get("short_name"), ms.get("going"),
                     ms.get("surface_summary"), ms.get("weather")))
        for rs in m.get("races", []):
            rid = rs["race_summary_reference"]["id"]
            url = f"/racing/racecards/{date}/{slug(course)}/racecard/{rid}/{slug(rs.get('name'))}"
            print(f"  {rs.get('time')} {course}  {rs.get('name','')[:60]}")
            try:
                rp, _ = get_json(url)
                race = rp["race"]
            except Exception as e:
                print(f"   !! failed: {e}")
                race = {"race_summary": rs, "rides": []}
            s = race.get("race_summary", rs)
            fc = race.get("betting_forecast") or ""
            fcd = parse_forecast(fc)
            con.execute("INSERT OR REPLACE INTO races VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, mid, date, s.get("time"), course, s.get("name"), s.get("race_class"),
                         s.get("distance"), s.get("going"), s.get("age"),
                         (s.get("course_surface") or {}).get("surface"), int(bool(s.get("has_handicap"))),
                         s.get("ride_count"), s.get("race_stage"), fc, s.get("verdict_text"), BASE + url))
            n_r += 1
            for rd in race.get("rides", []):
                h = rd.get("horse", {})
                hn = norm_name(h.get("name"))
                st = (rd.get("horse_lifetime_stats") or [{}])[0]
                hg = "".join(x.get("symbol", "") for x in rd.get("headgear") or [])
                hg1 = any(x.get("count") == 1 for x in rd.get("headgear") or [])
                ride_id = rd["ride_reference"]["id"]
                con.execute("INSERT OR REPLACE INTO runners VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (ride_id, rid, date, rd.get("cloth_number"), rd.get("draw_number"),
                             rd.get("ride_status"), h.get("name"), hn, (h.get("horse_reference") or {}).get("id"),
                             h.get("age"), (h.get("sex") or {}).get("type"), rd.get("handicap"),
                             wt_lb(rd.get("handicap")), rd.get("official_rating"),
                             (rd.get("jockey") or {}).get("name"), rd.get("jockey_claim"),
                             (rd.get("trainer") or {}).get("name"), (rd.get("owner") or {}).get("name"),
                             hg + ("1" if hg1 else ""), (h.get("formsummary") or {}).get("display_text"),
                             h.get("last_ran_days"), (rd.get("betting") or {}).get("current_odds"),
                             fcd.get(hn), _int(st.get("run_count")), _int(st.get("win_count")),
                             _int(st.get("place_count")), rd.get("silk_filename"), rd.get("commentary")))
                n_run += 1
                for i, p in enumerate(h.get("previous_results") or []):
                    cas = (p.get("casualty") or {}).get("reason")
                    con.execute("INSERT INTO prev_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (ride_id, hn, i, p.get("race_id"), p.get("date"), p.get("course_name"),
                                 p.get("distance"), p.get("run_type"), p.get("going"), p.get("race_class"),
                                 p.get("position"), cas, p.get("runner_count"), p.get("weight"), p.get("bha"),
                                 p.get("odds"), p.get("ride_description")))
        con.commit()
    con.execute("INSERT INTO scrape_log VALUES(?,?,?,?,?)",
                (date, dt.datetime.now().isoformat(timespec="seconds"), len(meetings), n_r, n_run))
    con.commit()
    con.close()
    print(f"Saved {len(meetings)} meetings, {n_r} races, {n_run} runners -> {DB}")
    return 0


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
