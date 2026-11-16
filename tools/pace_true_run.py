#!/usr/bin/env python3
r"""
Race pace / true-run labels for FurlongIQ (v1).

Reads Racing TV sectionals (data/sectionals.sqlite) and the figure cache
(data/site_cache.sqlite) in read-only mode, then writes a `pace` table into
the figure cache. Never writes to sectionals.sqlite or racing_history.sqlite.

Signals, in order:
  1) Finishing-speed % from sectionals (winner / leaders, last ~2f vs race
     average - Racing TV's finishing_speed_pct). Bands are calibrated per
     code and distance from the data's own distribution.
  2) Field-wide figure check: each runner's fig vs the median of its other
     runs. If the field as a whole ran well below (or above) its norm, the
     race is marked slow-run / suspect-fast.
  3) Comment keywords are applied later by the website as a weak fallback.

Usage (from the Speeds folder):
    python tools\pace_true_run.py
    python tools\pace_true_run.py --force
"""
from __future__ import annotations

import argparse, json, math, os, re, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "site_cache.sqlite"
SECTIONALS = DATA / "sectionals.sqlite"

SLOW_FIELD = -10.0
FAST_FIELD = 10.0

# Display labels stored as short keys.
# true = True run (honest / even / strong pace)
# steady = Steady (slowish early)
# slow = Slow-run (sprint finish)


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def norm_course(name: str) -> str:
    """Sandown Park/Sandown, Fontwell Park/Fontwell, Market Rasen/MarketRasen -> same key."""
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    words = [w for w in re.split(r"[^a-z]+", n) if w and w not in ("park", "the", "downs", "city", "racecourse", "aw")]
    return "".join(words)


def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def hhmm(t) -> str:
    s = str(t or "").strip().lower().replace(".", ":")
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        ap = m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return f"{h:02d}{mi:02d}"
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 4:
        return digits[-4:]
    if len(digits) == 3:
        return "0" + digits
    return digits


def code_of(code, surface=None) -> str:
    c = str(code or "").strip()
    cl = c.lower()
    if c in {"Hurdle", "Chase", "NHF", "Flat", "AW"}:
        return "NHF" if c == "NHF" else c
    if "chase" in cl:
        return "Chase"
    if "hurdle" in cl:
        return "Hurdle"
    if "nhf" in cl or "bumper" in cl or "national hunt flat" in cl:
        return "NHF"
    surf = str(surface or "").lower()
    if c == "AW" or cl == "aw" or surf.startswith("aw") or "all weather" in surf or "all-weather" in surf:
        return "AW"
    return "Flat"


def dist_f_of(yards, text=None, fallback=None) -> float | None:
    if yards not in (None, ""):
        try:
            y = float(yards)
            if y > 0:
                return round(y / 220.0, 2)
        except (TypeError, ValueError):
            pass
    s = str(text or "").lower()
    m = re.search(r"(?:(\d+)\s*m)?\s*(?:(\d+)\s*f)?\s*(?:(\d+)\s*y)?", s.replace("½", " 1/2"))
    if m and any(m.groups()):
        mi = int(m.group(1) or 0)
        fu = int(m.group(2) or 0)
        ya = int(m.group(3) or 0)
        if mi or fu or ya:
            return round(mi * 8 + fu + ya / 220.0, 2)
    if fallback not in (None, ""):
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return None
    return None


def dist_band(code: str, dist_f: float | None) -> str:
    f = dist_f if dist_f is not None else 8.0
    if code in {"Hurdle", "Chase", "NHF"}:
        if f <= 17:
            return "short"
        if f <= 21:
            return "mid"
        if f <= 25:
            return "long"
        return "staying"
    if f <= 6.5:
        return "sprint"
    if f <= 8.5:
        return "mile"
    if f <= 12.5:
        return "mid"
    return "long"


def ro_connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        pass
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def percentiles(vals: list[float], ps: list[float]) -> list[float]:
    if not vals:
        return [math.nan] * len(ps)
    xs = sorted(vals)
    n = len(xs)
    out = []
    for p in ps:
        if n == 1:
            out.append(xs[0])
            continue
        i = (p / 100.0) * (n - 1)
        lo = int(math.floor(i))
        hi = int(math.ceil(i))
        if lo == hi:
            out.append(xs[lo])
        else:
            t = i - lo
            out.append(xs[lo] * (1 - t) + xs[hi] * t)
    return out


def load_sectionals() -> tuple[list[dict], dict, dict]:
    """Return race-level sectional stats, bands, and a coverage signature. Never writes."""
    empty = [], {}, {"present": 0, "n_races": 0, "max_date": "", "n_fsp": 0}
    if not SECTIONALS.is_file():
        log("No data/sectionals.sqlite - pace will use the field-figure check only.")
        return empty
    try:
        con = ro_connect(SECTIONALS)
    except sqlite3.Error as e:
        log(f"Could not open sectionals.sqlite read-only ({e}); continuing without sectionals.")
        return empty
    try:
        if not table_exists(con, "rtv_races") or not table_exists(con, "rtv_runners"):
            log("sectionals.sqlite has no rtv_races/rtv_runners yet.")
            return empty
        cov = con.execute(
            "SELECT COUNT(*) n, MAX(race_date) mx, SUM(COALESCE(has_sectionals,0)) sec FROM rtv_races"
        ).fetchone()
        sig = {"present": 1, "n_races": int(cov["n"] or 0), "max_date": str(cov["mx"] or ""), "n_fsp": 0}
        # Winner FSP, plus average of the first three with a figure as a backup.
        rows = con.execute(
            """
            SELECT r.rtv_race_id, r.race_date, r.course, r.off_time, r.race_type,
                   r.distance_yards, r.distance_text, r.has_sectionals,
                   u.horse_name, u.finish_position, u.finishing_speed_pct
            FROM rtv_races r
            LEFT JOIN rtv_runners u ON u.rtv_race_id = r.rtv_race_id
            WHERE u.finishing_speed_pct IS NOT NULL
              AND u.finishing_speed_pct BETWEEN 80 AND 130
            """
        ).fetchall()
        # Horses in each race (for matching form runs) - short query on names/positions only.
        names = con.execute(
            "SELECT rtv_race_id, horse_name, finish_position FROM rtv_runners"
        ).fetchall()
    finally:
        con.close()

    horses: dict[int, list[str]] = {}
    winners: dict[int, str] = {}
    for r in names:
        rid = int(r["rtv_race_id"])
        horses.setdefault(rid, []).append(norm_name(r["horse_name"]))
        if r["finish_position"] == 1 and rid not in winners:
            winners[rid] = norm_name(r["horse_name"])

    by: dict[int, dict] = {}
    fsp_lists: dict[int, list[tuple[int, float]]] = {}
    for r in rows:
        rid = int(r["rtv_race_id"])
        rec = by.get(rid)
        if rec is None:
            rec = {
                "rtv_race_id": rid,
                "date": str(r["race_date"] or "")[:10],
                "course": r["course"] or "",
                "course_norm": norm_course(r["course"] or ""),
                "off_hhmm": hhmm(r["off_time"]),
                "code": code_of(r["race_type"]),
                "dist_f": dist_f_of(r["distance_yards"], r["distance_text"]),
                "has_sectionals": int(r["has_sectionals"] or 0),
                "horses": horses.get(rid, []),
                "winner": winners.get(rid, ""),
                "fsp": None,
            }
            by[rid] = rec
        pos = r["finish_position"]
        fsp = r["finishing_speed_pct"]
        if fsp is None:
            continue
        try:
            pos_n = int(pos) if pos is not None else 99
        except (TypeError, ValueError):
            pos_n = 99
        fsp_lists.setdefault(rid, []).append((pos_n, float(fsp)))

    for rid, rec in by.items():
        lst = sorted(fsp_lists.get(rid, []), key=lambda x: x[0])
        win = next((v for p, v in lst if p == 1), None)
        if win is None and lst:
            # Leaders: first up to 3 finishers with an FSP.
            lead = [v for p, v in lst if p <= 3][:3] or [lst[0][1]]
            win = sum(lead) / len(lead)
        rec["fsp"] = round(win, 2) if win is not None else None

    races = [r for r in by.values() if r.get("fsp") is not None]
    sig["n_fsp"] = len(races)

    # Calibrate bands per code + distance from winner/leader FSP.
    groups: dict[tuple[str, str], list[float]] = {}
    all_fsp: list[float] = []
    for r in races:
        if r["fsp"] is None:
            continue
        all_fsp.append(r["fsp"])
        groups.setdefault((r["code"] or "Flat", dist_band(r["code"] or "Flat", r["dist_f"])), []).append(r["fsp"])
    bands = {}
    p30, p50, p70, p80 = percentiles(all_fsp, [30, 50, 70, 80])
    bands["*|*"] = {"n": len(all_fsp), "p30": p30, "p50": p50, "p70": p70, "p80": p80}
    for key, xs in groups.items():
        a, b, c, d = percentiles(xs, [30, 50, 70, 80])
        bands[f"{key[0]}|{key[1]}"] = {"n": len(xs), "p30": a, "p50": b, "p70": c, "p80": d}
    log(
        f"Sectionals: {sig['n_races']:,} races (to {sig['max_date']}), "
        f"{len(races):,} with a finishing-speed %; median winner FSP {p50:.1f}%"
    )
    return races, bands, sig


def fsp_label(fsp: float, code: str, dist_f: float | None, bands: dict) -> str:
    key = f"{code}|{dist_band(code, dist_f)}"
    b = bands.get(key) or bands.get("*|*") or {}
    if not b or b.get("n", 0) < 80:
        b = bands.get("*|*") or {}
    p70 = float(b.get("p70") or 107)
    p80 = float(b.get("p80") or 109)
    # Slow-run: clearly faster late than this code/trip usually finishes.
    if fsp >= max(p80, 107.0) or fsp >= p80 + 0.4:
        return "slow"
    # Steady: high side of typical, but not a full sprint-finish race.
    if fsp >= max(p70, 105.0):
        return "steady"
    return "true"


def load_field() -> tuple[list[dict], dict]:
    """Field-wide figure deficit for every race in the figure cache."""
    if not CACHE.is_file():
        fail(f"Missing {CACHE}. Run npm run figures first.")
    con = ro_connect(CACHE)
    try:
        if not table_exists(con, "figs"):
            fail("site_cache.sqlite has no figs table.")
        meta = dict(con.execute("SELECT k, v FROM meta").fetchall()) if table_exists(con, "meta") else {}
        cols = {r[1] for r in con.execute("PRAGMA table_info(figs)")}
        need = ["race_id", "date", "course", "code", "dist_f", "horse_norm", "fig"]
        have = [c for c in need if c in cols]
        extra = [c for c in ("time", "surface", "horse") if c in cols]
        rows = con.execute("SELECT " + ", ".join(have + extra) + " FROM figs").fetchall()
        sig = {
            "rows": meta.get("rows") or str(len(rows)),
            "max_date": meta.get("max_date") or "",
            "mtime": meta.get("mtime") or "",
        }
    finally:
        con.close()

    # Group by horse for typical (median of other runs), then by race.
    by_horse: dict[str, list[tuple[int, float]]] = {}
    recs = []
    for i, r in enumerate(rows):
        fig = r["fig"]
        try:
            fig_n = float(fig) if fig is not None and fig != "" else None
        except (TypeError, ValueError):
            fig_n = None
        recs.append(r)
        if fig_n is None:
            continue
        by_horse.setdefault(r["horse_norm"] or "", []).append((i, fig_n))

    typ = [None] * len(recs)
    for hn, items in by_horse.items():
        if not hn or len(items) < 3:
            continue
        vals = [v for _, v in items]
        for k, (i, v) in enumerate(items):
            others = vals[:k] + vals[k + 1 :]
            typ[i] = sorted(others)[len(others) // 2] if len(others) >= 2 else None

    races: dict[str, dict] = {}
    for i, r in enumerate(recs):
        rid = str(r["race_id"] or "")
        if not rid:
            continue
        rec = races.get(rid)
        if rec is None:
            surface = r["surface"] if "surface" in r.keys() else None
            rec = {
                "fig_race_id": rid,
                "date": str(r["date"] or "")[:10],
                "course": r["course"] or "",
                "course_norm": norm_course(r["course"] or ""),
                "off_hhmm": hhmm(r["time"] if "time" in r.keys() else ""),
                "code": code_of(r["code"], surface),
                "dist_f": dist_f_of(None, None, r["dist_f"]),
                "horses": [],
                "defs": [],
            }
            races[rid] = rec
        hn = r["horse_norm"] or norm_name(r["horse"] if "horse" in r.keys() else "")
        if hn and hn not in rec["horses"]:
            rec["horses"].append(hn)
        if typ[i] is not None and r["fig"] is not None:
            try:
                rec["defs"].append(float(r["fig"]) - typ[i])
            except (TypeError, ValueError):
                pass

    out = []
    for rec in races.values():
        defs = rec.pop("defs")
        rec["n_field"] = len(defs)
        rec["field_def"] = round(sorted(defs)[len(defs) // 2], 1) if len(defs) >= 3 else None
        out.append(rec)
    n_slow = sum(1 for r in out if r["field_def"] is not None and r["field_def"] <= SLOW_FIELD)
    n_fast = sum(1 for r in out if r["field_def"] is not None and r["field_def"] >= FAST_FIELD)
    log(
        f"Field check: {len(out):,} figure races, "
        f"{n_slow:,} slow-field (<= {SLOW_FIELD:.0f}), {n_fast:,} fast-field (>= {FAST_FIELD:.0f})"
    )
    return out, sig


def match_key(date, course_norm, hh, code, dist_f):
    return (date, course_norm, hh, code, None if dist_f is None else round(float(dist_f) * 2) / 2)


def combine(sec: dict | None, field: dict | None, bands: dict) -> dict:
    date = (sec or field or {}).get("date") or ""
    course = (field or sec or {}).get("course") or ""
    course_norm = (field or sec or {}).get("course_norm") or norm_course(course)
    hh = (sec or field or {}).get("off_hhmm") or (field or {}).get("off_hhmm") or ""
    code = (sec or field or {}).get("code") or "Flat"
    dist_f = (sec or field or {}).get("dist_f")
    fsp = sec.get("fsp") if sec else None
    field_def = field.get("field_def") if field else None
    n_field = (field or {}).get("n_field") or 0
    horses = []
    for src in (field, sec):
        for h in (src or {}).get("horses") or []:
            if h and h not in horses:
                horses.append(h)

    sec_lab = fsp_label(fsp, code, dist_f, bands) if fsp is not None else None
    field_slow = field_def is not None and field_def <= SLOW_FIELD
    field_fast = field_def is not None and field_def >= FAST_FIELD

    # Pace label: sectionals first, then the field check.
    # Field-slow with no sectionals = Slow-run. Field-slow with a true/strong
    # sectional stays Steady (they went a genuine gallop and still ran below
    # their usual - a tough race, not a sprint finish).
    if sec_lab == "slow" or (sec_lab is None and field_slow):
        label = "slow"
    elif sec_lab == "steady" or (sec_lab == "true" and field_slow):
        label = "steady"
    elif sec_lab == "true":
        label = "true"
    elif field_fast:
        label = "true"
    else:
        label = "unknown"

    # Reliability:
    # - Slow-run / sprint finish (sectionals) → Low (pace-affected)
    # - Field well below and no true/strong sectional → Low
    # - Field well below but sectionals say true/strong → OK (ran slow on merit)
    # - Field well above → Suspect high (soft standard)
    # - Steady from FSP only, field normal → OK
    if field_fast:
        fig_rel = "suspect"
    elif sec_lab == "slow":
        fig_rel = "low"
    elif field_slow and sec_lab != "true":
        fig_rel = "low"
    else:
        fig_rel = "ok"

    bits = []
    if field_def is not None:
        vs = "below" if field_def < 0 else "above"
        bits.append(f"Field ran {abs(field_def):.0f} {vs} their usual")
    if fsp is not None:
        tag = "sprint" if (sec_lab == "slow" or (fsp or 0) >= 107) else ("steady" if sec_lab == "steady" else "even")
        bits.append(f"finish {fsp:.0f}% ({tag})")
    if not bits:
        bits.append("Not enough pace or field evidence")
    reason = "; ".join(bits)

    if sec is not None and field is not None and (fsp is not None or field_def is not None):
        source = "mixed" if (fsp is not None and field_def is not None) else ("sectionals" if fsp is not None else "field")
    elif sec is not None and fsp is not None:
        source = "sectionals"
    elif field is not None and field_def is not None:
        source = "field"
    else:
        source = "unknown"

    return {
        "date": date,
        "course_norm": course_norm,
        "course": course,
        "off_hhmm": hh,
        "dist_f": dist_f,
        "code": code,
        "label": label,
        "fig_rel": fig_rel,
        "reason": reason,
        "source": source,
        "fsp": None if fsp is None else round(float(fsp), 2),
        "field_def": field_def,
        "n_field": n_field,
        "horses": ",".join(horses),
        "fig_race_id": (field or {}).get("fig_race_id"),
        "rtv_race_id": (sec or {}).get("rtv_race_id"),
    }


def merge(sec_races: list[dict], field_races: list[dict], bands: dict) -> list[dict]:
    # Index sectionals for matching.
    by_time: dict[tuple, list[dict]] = {}
    by_dist: dict[tuple, list[dict]] = {}
    for s in sec_races:
        by_time.setdefault((s["date"], s["course_norm"], s["off_hhmm"]), []).append(s)
        df = None if s["dist_f"] is None else round(float(s["dist_f"]) * 2) / 2
        by_dist.setdefault((s["date"], s["course_norm"], s["code"], df), []).append(s)

    used = set()
    out = []
    unmatched_field = 0
    for f in field_races:
        hit = None
        cand = by_time.get((f["date"], f["course_norm"], f["off_hhmm"]) ) or []
        if len(cand) == 1:
            hit = cand[0]
        elif len(cand) > 1:
            # Same time (rare) - prefer shared horses or closest trip.
            hit = pick_match(cand, f)
        if hit is None:
            df = None if f["dist_f"] is None else round(float(f["dist_f"]) * 2) / 2
            cand = by_dist.get((f["date"], f["course_norm"], f["code"], df)) or []
            if not cand and df is not None:
                # nearest trip within 0.6f, unique
                close = []
                for (d, c, code, sdf), lst in by_dist.items():
                    if d == f["date"] and c == f["course_norm"] and code == f["code"] and sdf is not None:
                        if abs(sdf - df) <= 0.6:
                            close.extend(lst)
                cand = close
            if len(cand) == 1:
                hit = cand[0]
            elif len(cand) > 1:
                hit = pick_match(cand, f)
        if hit is not None:
            used.add(hit["rtv_race_id"])
        row = combine(hit, f, bands)
        # Keep unknown rows only when we have some handle (field or time) so
        # the site can still look them up; skip empty shells.
        if row["label"] != "unknown" or row["field_def"] is not None or row["fsp"] is not None:
            out.append(row)
        else:
            unmatched_field += 1
        if hit is None:
            unmatched_field += 0

    extra = 0
    for s in sec_races:
        if s["rtv_race_id"] in used:
            continue
        row = combine(s, None, bands)
        if row["label"] != "unknown" or row["fsp"] is not None:
            out.append(row)
            extra += 1
    log(f"Merged {len(out):,} pace rows (sectionals-only races added: {extra:,})")
    return out


def pick_match(cand: list[dict], field: dict) -> dict | None:
    fh = set(field.get("horses") or [])
    if fh:
        scored = []
        for c in cand:
            sh = set(c.get("horses") or [])
            scored.append((len(fh & sh), c))
        scored.sort(key=lambda x: -x[0])
        if scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return scored[0][1]
    # Closest trip
    fd = field.get("dist_f")
    if fd is not None:
        cand = sorted(cand, key=lambda c: abs((c.get("dist_f") or fd) - fd))
        return cand[0]
    return cand[0] if len(cand) == 1 else None


def existing_sig(con: sqlite3.Connection) -> dict:
    if not table_exists(con, "meta"):
        return {}
    meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
    return {
        "figs_rows": meta.get("pace_figs_rows") or "",
        "figs_max": meta.get("pace_figs_max") or "",
        "figs_mtime": meta.get("pace_figs_mtime") or "",
        "sec_n": meta.get("pace_sec_n") or "",
        "sec_max": meta.get("pace_sec_max") or "",
        "sec_fsp": meta.get("pace_sec_fsp") or "",
    }


def write_cache(rows: list[dict], fig_sig: dict, sec_sig: dict, bands: dict, t0: float) -> None:
    if not CACHE.is_file():
        fail(f"Missing {CACHE}")
    con = sqlite3.connect(str(CACHE), timeout=30)
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pace (
              date TEXT NOT NULL,
              course_norm TEXT NOT NULL,
              course TEXT,
              off_hhmm TEXT,
              dist_f REAL,
              code TEXT,
              label TEXT,
              fig_rel TEXT,
              reason TEXT,
              source TEXT,
              fsp REAL,
              field_def REAL,
              n_field INTEGER,
              horses TEXT,
              fig_race_id TEXT,
              rtv_race_id INTEGER
            )
            """
        )
        con.execute("DROP INDEX IF EXISTS ix_pace_date_course")
        con.execute("CREATE INDEX ix_pace_date_course ON pace(date, course_norm)")
        con.execute("DELETE FROM pace")
        con.executemany(
            """
            INSERT INTO pace (
              date, course_norm, course, off_hhmm, dist_f, code, label, fig_rel,
              reason, source, fsp, field_def, n_field, horses, fig_race_id, rtv_race_id
            ) VALUES (
              :date, :course_norm, :course, :off_hhmm, :dist_f, :code, :label, :fig_rel,
              :reason, :source, :fsp, :field_def, :n_field, :horses, :fig_race_id, :rtv_race_id
            )
            """,
            rows,
        )
        if not table_exists(con, "meta"):
            con.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
        counts = {
            "true": 0, "steady": 0, "slow": 0, "unknown": 0,
            "ok": 0, "low": 0, "suspect": 0,
            "sectionals": 0, "field": 0, "mixed": 0,
        }
        for r in rows:
            counts[r["label"]] = counts.get(r["label"], 0) + 1
            counts[r["fig_rel"]] = counts.get(r["fig_rel"], 0) + 1
            src = r["source"]
            if src in counts:
                counts[src] += 1
            elif src:
                counts[src] = counts.get(src, 0) + 1
        meta = {
            "pace_built": time.strftime("%Y-%m-%d %H:%M"),
            "pace_rows": str(len(rows)),
            "pace_figs_rows": str(fig_sig.get("rows") or ""),
            "pace_figs_max": str(fig_sig.get("max_date") or ""),
            "pace_figs_mtime": str(fig_sig.get("mtime") or ""),
            "pace_sec_n": str(sec_sig.get("n_races") or 0),
            "pace_sec_max": str(sec_sig.get("max_date") or ""),
            "pace_sec_fsp": str(sec_sig.get("n_fsp") or 0),
            "pace_n_true": str(counts.get("true") or 0),
            "pace_n_steady": str(counts.get("steady") or 0),
            "pace_n_slow": str(counts.get("slow") or 0),
            "pace_n_unknown": str(counts.get("unknown") or 0),
            "pace_n_low": str(counts.get("low") or 0),
            "pace_n_suspect": str(counts.get("suspect") or 0),
            "pace_n_sec_src": str((counts.get("sectionals") or 0) + (counts.get("mixed") or 0)),
            "pace_n_field_src": str((counts.get("field") or 0) + (counts.get("mixed") or 0)),
            "pace_bands": json.dumps({k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in bands.items()}, separators=(",", ":")),
        }
        con.executemany("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", meta.items())
        con.commit()
    finally:
        con.close()
    log(
        f"Wrote {len(rows):,} pace rows to site_cache.sqlite in {time.time()-t0:.0f}s  "
        f"(true {counts['true']:,} - steady {counts['steady']:,} - slow {counts['slow']:,} - "
        f"low-rel {counts['low']:,} - suspect {counts['suspect']:,})"
    )


def lookup_fontwell(rows: list[dict]) -> None:
    hits = [r for r in rows if r["date"] == "2026-10-21" and "fontwell" in (r["course_norm"] or "")]
    if not hits:
        log("Fontwell 21 Oct 26: no pace rows (unexpected if figures are loaded).")
        return
    log("Fontwell 21 Oct 26 pace:")
    for r in sorted(hits, key=lambda x: x.get("off_hhmm") or ""):
        mark = "  <-- Uncle Al 16:17" if r.get("off_hhmm") == "1617" else ""
        log(
            f"  {r['off_hhmm'] or '?'} {r['code']} {r.get('dist_f')}f  {r['label']}/{r['fig_rel']}  "
            f"{r['reason']}  [{r['source']}]{mark}"
        )


def should_skip(fig_sig: dict, sec_sig: dict, force: bool) -> bool:
    if force or not CACHE.is_file():
        return False
    try:
        con = ro_connect(CACHE)
        try:
            if not table_exists(con, "pace"):
                return False
            n = con.execute("SELECT COUNT(*) FROM pace").fetchone()[0]
            if not n:
                return False
            have = existing_sig(con)
        finally:
            con.close()
    except sqlite3.Error:
        return False
    same = (
        have.get("figs_rows") == str(fig_sig.get("rows") or "")
        and have.get("figs_max") == str(fig_sig.get("max_date") or "")
        and have.get("figs_mtime") == str(fig_sig.get("mtime") or "")
        and have.get("sec_n") == str(sec_sig.get("n_races") or 0)
        and have.get("sec_max") == str(sec_sig.get("max_date") or "")
        and have.get("sec_fsp") == str(sec_sig.get("n_fsp") or 0)
    )
    if same:
        log(f"Pace cache is already up to date ({n:,} rows). Use --force to rebuild.")
        return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Build race pace / true-run labels into site_cache.sqlite.")
    parser.add_argument("--force", action="store_true", help="Rebuild even if inputs have not changed.")
    args = parser.parse_args()
    t0 = time.time()

    sec_races, bands, sec_sig = load_sectionals()
    # Peek at cache meta first so we can skip the heavier field pass when possible.
    fig_sig_preview = {}
    if CACHE.is_file():
        try:
            con = ro_connect(CACHE)
            try:
                if table_exists(con, "meta"):
                    meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
                    fig_sig_preview = {"rows": meta.get("rows") or "", "max_date": meta.get("max_date") or "", "mtime": meta.get("mtime") or ""}
            finally:
                con.close()
        except sqlite3.Error:
            fig_sig_preview = {}
    if fig_sig_preview and should_skip(fig_sig_preview, sec_sig, args.force):
        return

    field_races, fig_sig = load_field()
    rows = merge(sec_races, field_races, bands)
    write_cache(rows, fig_sig, sec_sig, bands, t0)
    lookup_fontwell(rows)
    n_sec = sum(1 for r in rows if r["source"] in {"sectionals", "mixed"})
    n_field = sum(1 for r in rows if r["source"] in {"field", "mixed"})
    n_sec_only = sum(1 for r in rows if r["source"] == "sectionals")
    n_field_only = sum(1 for r in rows if r["source"] == "field")
    n_mixed = sum(1 for r in rows if r["source"] == "mixed")
    log(
        f"PACE READY: {len(rows):,} races - sectionals {n_sec:,} ({n_sec_only:,} only, {n_mixed:,} mixed) - "
        f"field {n_field:,} ({n_field_only:,} only) in {time.time()-t0:.0f}s"
    )


if __name__ == "__main__":
    main()
