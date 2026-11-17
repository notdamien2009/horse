#!/usr/bin/env python3
r"""
FurlongIQ sectionals v12.

Reads (read-only):  data\sectionals.sqlite, data\speed_v4\speed_figures.csv,
                    data\speed_v4\distance_corrections.csv (winning times / exact yards),
                    data\site_cache.sqlite (figs), data\rbd_prices.csv.gz (backtest only)
Writes:             data\sectionals_v12\*  and the `pace` table (+ meta keys) in
                    data\site_cache.sqlite (same columns pace_true_run.py uses).
Never touches racing_history.sqlite, .env, Supabase or the website code.
Winning times follow v4's three-way rule (RBD / Racing TV results / sectionals).

What it does
  1. Joins Racing TV sectional races/runners to speed_v4 figure races/runners
     (date + course + off time, then horse overlap for time changes) and reports
     the match rate.
  2. Builds per-section par times for every course + code/surface + trip from
     sound races (winner with full, sane sections), on Racing TV exact yards.
     Rail-moved races stay in the same standard; extra yards go into the first
     section and are adjusted pro-rata. Going is v4's going allowance.
     Also writes section-by-section and full-race figures from those standards.
  3. Race pace profile: the early pace set by the leader and the late speed of
     the principals, each against its section par -> Fast-early / True / Steady /
     Slow, plus each runner's finishing speed % and its finishing speed vs par.
  4. Figure adjustment: how far figures in each pace shape / run style ran from
     the horses' usual level -> understated / overstated flags and an adjusted
     figure per run.
  5. Point-in-time horse history features and a held-out-year backtest against
     the current win-% conditional logit. Only features that hold up on the
     validation year are adopted; the held-out test year is reported honestly.

Usage (from the Speeds folder):
    py -3 tools\sectionals_v12.py               full run
    py -3 tools\sectionals_v12.py --no-backtest  pace + outputs only
    py -3 tools\sectionals_v12.py --pace-only    rebuild the site pace table from
                                                 the cached race pace file (fast)
    py -3 tools\sectionals_v12.py --start 2026-09-01 --end 2026-10-31 --no-write
                                                 small slice test, writes nothing
                                                 to site_cache
"""
from __future__ import annotations

import argparse, json, math, re, sqlite3, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TOOLS = ROOT / "tools"
SECT = DATA / "sectionals.sqlite"
CACHE = DATA / "site_cache.sqlite"
FIGCSV = DATA / "speed_v4" / "speed_figures.csv"
V4CORR = DATA / "speed_v4" / "distance_corrections.csv"
OUT = DATA / "sectionals_v12"
SECT_FIGS_OUT = OUT / "section_figures.csv.gz"
RACE_PACE = OUT / "race_pace.csv.gz"
RUNNERS_OUT = OUT / "runner_sectionals.csv.gz"
PARS_OUT = OUT / "section_pars.csv"
SHAPE_PARS_OUT = OUT / "shape_pars.csv"
HORSE_OUT = OUT / "horse_sectional_features.csv.gz"
ADJ_OUT = OUT / "figure_adjustments.csv"
JOIN_OUT = OUT / "join_report.txt"
ADOPT_OUT = OUT / "adopted_features.json"
BACKTEST_OUT = OUT / "backtest.json"
SUMMARY_OUT = OUT / "summary.txt"
SETTINGS_OUT = OUT / "settings.json"

sys.path.insert(0, str(TOOLS))

FURLONG = 220.0
MIN_PAR_N = 20          # sound races needed before a course/trip par is used on its own
JUMPS = {"Hurdle", "Chase", "NHF"}
LATE_F = {"Flat": 2, "AW": 2, "Hurdle": 3, "Chase": 3, "NHF": 3}
AW_COURSE_KEYS = {"wolverhampton", "chelmsford", "dundalk"}          # AW-only tracks
MIXED_AW_KEYS = {"newcastle", "southwell", "lingfield", "kempton"}  # AW + turf


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# --------------------------------------------------------------------------- keys
def join_key(name) -> str:
    """Course key for joining: 'Kempton Park', 'Kempton (AW)', 'Chelmsford City' -> same."""
    s = re.sub(r"\(.*?\)", "", str(name or "").lower())
    s = re.sub(r"[^a-z]", "", s)
    for a, b in (("bangorondee", "bangor"), ("stratforduponavon", "stratford"), ("stratfordonavon", "stratford")):
        s = s.replace(a, b)
    for suf in ("racecourse", "park", "city", "downs", "bridge"):
        if s.endswith(suf) and len(s) > len(suf) + 3:
            s = s[: -len(suf)]
    return s


def site_course_norm(name) -> str:
    """Exactly pace_true_run.norm_course, so the site's lookup keeps working."""
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    words = [w for w in re.split(r"[^a-z]+", n) if w and w not in ("park", "the", "downs", "city", "racecourse", "aw")]
    return "".join(words)


def horse_key(s) -> str:
    """Same as predict_today/pace_true_run norm_name (no spaces, no country suffix)."""
    s = str(s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def hhmm(t) -> str:
    s = str(t or "").strip().lower().replace(".", ":")
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}{int(m.group(2)):02d}"
    d = re.sub(r"\D", "", s)
    return d[-4:].zfill(4) if d else ""


def mins(h: str) -> int | None:
    if not h or len(h) != 4 or not h.isdigit():
        return None
    return int(h[:2]) * 60 + int(h[2:])


GOING_TABLE = [
    ("soft to heavy", 5.5), ("yielding to soft", 4.5), ("good to yielding", 3.5),
    ("good to soft", 4.0), ("good to firm", 2.0), ("firm to good", 1.5),
    ("heavy", 6.0), ("soft", 5.0), ("yielding", 4.0), ("good", 3.0), ("firm", 1.0),
]
AW_GOING_RE = re.compile(r"standard|polytrack|tapeta|fibresand", re.I)


def going_n(g) -> float:
    s = str(g or "").lower().split("(")[0]
    for k, v in GOING_TABLE:
        if k in s:
            return v
    return float("nan")


def dist_band(fam: str, f: float) -> str:
    if fam in JUMPS:
        return "short" if f <= 17 else "mid" if f <= 21 else "long" if f <= 25 else "staying"
    return "sprint" if f <= 6.5 else "mile" if f <= 8.5 else "mid" if f <= 12.5 else "long"


def ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        con.execute("PRAGMA query_only=ON")
    except sqlite3.Error:
        pass
    return con


# ----------------------------------------------------------------- load sectionals
def load_sectionals(start: str | None, end: str | None):
    if not SECT.is_file():
        fail(f"Missing {SECT}")
    t0 = time.time()
    con = ro(SECT)
    where, args = "", []
    if start or end:
        where = " WHERE race_date BETWEEN ? AND ?"
        args = [start or "1900-01-01", end or "2999-12-31"]
    R = pd.read_sql(
        "SELECT rtv_race_id, race_date, course, country, off_time, race_name, title_full, race_type, "
        "race_class, distance_text, distance_yards, going, runner_count, winner_time_s, has_sectionals "
        "FROM rtv_races" + where, con, params=args)
    ids = "SELECT rtv_race_id FROM rtv_races" + where
    U = pd.read_sql(
        "SELECT rtv_race_id, rtv_runner_id, horse_name, finish_position, finishing_speed_pct, total_time_s, n_sections "
        f"FROM rtv_runners WHERE rtv_race_id IN ({ids})", con, params=args)
    S = pd.read_sql(
        "SELECT rtv_race_id, rtv_runner_id, sector_number, sector_time, position "
        f"FROM rtv_sectionals WHERE rtv_race_id IN ({ids})", con, params=args)
    con.close()
    log(f"  sectionals.sqlite: {len(R):,} races, {len(U):,} runners, {len(S):,} section rows ({time.time()-t0:.0f}s)")
    return R, U, S


def race_family(R: pd.DataFrame) -> pd.Series:
    rt = R["race_type"].fillna("").astype(str).str.lower()
    title = (R["title_full"].fillna("") + " " + R["race_name"].fillna("")).str.lower()
    fam = np.where(rt.str.contains("chase") | (rt.eq("") & title.str.contains("chase")), "Chase",
          np.where(rt.str.contains("hurdle") | (rt.eq("") & title.str.contains("hurdle")), "Hurdle",
          np.where(rt.str.contains("bumper") | rt.str.contains("nhf") |
                   (rt.eq("") & title.str.contains("bumper|national hunt flat|nh flat")), "NHF", "Flat")))
    fam = pd.Series(fam, index=R.index)
    ck = R["course"].map(join_key)
    aw_title = title.str.contains(r"\(all weather\)|\(aw\)|polytrack|tapeta|fibresand|all-weather")
    turf_title = title.str.contains(r"\(turf\)")
    aw_going = R["going"].fillna("").str.contains(AW_GOING_RE)
    is_aw = (fam == "Flat") & (aw_title | aw_going | ck.isin(AW_COURSE_KEYS) | (ck.isin(MIXED_AW_KEYS) & ~turf_title & aw_going))
    fam[is_aw] = "AW"
    return fam


# ------------------------------------------------------------ runner-level metrics
def runner_metrics(R: pd.DataFrame, U: pd.DataFrame, S: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    info = {}
    R = R.copy()
    R["fam"] = race_family(R)
    R["dist_y"] = pd.to_numeric(R["distance_yards"], errors="coerce")
    S = S.sort_values(["rtv_race_id", "rtv_runner_id", "sector_number"], kind="mergesort").reset_index(drop=True)
    S["sector_time"] = pd.to_numeric(S["sector_time"], errors="coerce")
    keys = ["rtv_race_id", "rtv_runner_id"]
    g = S.groupby(keys, sort=False)
    agg = g.agg(nsec=("sector_number", "size"), smin=("sector_number", "min"), smax=("sector_number", "max"),
                tsum=("sector_time", "sum"), tnull=("sector_time", lambda s: int(s.isna().sum()))).reset_index()
    S = S.merge(agg[keys + ["nsec"]], on=keys, how="left")
    S = S.merge(R[["rtv_race_id", "fam", "dist_y"]], on="rtv_race_id", how="left")
    S["L"] = S["fam"].map(LATE_F).fillna(2).astype(int)
    S["kend"] = S["nsec"] - 1 - S["sector_number"]
    S["cum"] = S.groupby(keys, sort=False)["sector_time"].cumsum()
    # Sanity of non-first sections (each a furlong): 8-22 yards/second.
    sp = FURLONG / S["sector_time"]
    bad = (S["sector_number"] > 0) & ((sp < 8.0) | (sp > 22.0) | S["sector_time"].isna())
    nbad = bad.groupby([S["rtv_race_id"], S["rtv_runner_id"]]).sum().rename("nbad").reset_index()
    late = S[S["kend"] < S["L"]].groupby(keys)["sector_time"].sum().rename("late_t").reset_index()
    bnd = S[S["kend"] == S["L"]][keys + ["cum", "position"]].rename(columns={"cum": "early_t", "position": "early_pos"})
    S["sidx"] = np.maximum(0, np.round(S["nsec"] * 0.3).astype(int) - 1)
    sty = S[S["sector_number"] == S["sidx"]][keys + ["position"]].rename(columns={"position": "style_pos"})
    last1 = S[S["kend"] == 0][keys + ["sector_time"]].rename(columns={"sector_time": "last1_t"})
    M = (agg.merge(nbad, on=keys, how="left").merge(late, on=keys, how="left")
            .merge(bnd, on=keys, how="left").merge(sty, on=keys, how="left").merge(last1, on=keys, how="left"))
    M = M.merge(U, on=keys, how="left")
    M = M.merge(R[["rtv_race_id", "fam", "dist_y"]], on="rtv_race_id", how="left")
    M["L"] = M["fam"].map(LATE_F).fillna(2).astype(int)
    M["first_len"] = M["dist_y"] - FURLONG * (M["nsec"] - 1)
    M["contig"] = (M["smin"] == 0) & (M["smax"] == M["nsec"] - 1) & (M["tnull"] == 0)
    M["sane"] = (M["contig"] & (M["nbad"].fillna(1) == 0) & M["first_len"].between(20, 460)
                 & (M["nsec"] >= M["L"] + 2) & M["dist_y"].notna())
    tot = M["total_time_s"].where(M["total_time_s"].notna(), M["tsum"])
    M["tsum_gap"] = (M["tsum"] - M["total_time_s"]).abs()
    M.loc[M["total_time_s"].notna() & (M["tsum_gap"] > 1.0), "sane"] = False
    M["total_t"] = M["tsum"]
    M["overall_v"] = M["dist_y"] / M["total_t"]
    M["late_d"] = FURLONG * M["L"]
    M["early_d"] = M["dist_y"] - M["late_d"]
    M["late_v"] = M["late_d"] / M["late_t"]
    M["early_v"] = M["early_d"] / M["early_t"]
    M["late_rel"] = M["late_v"] / M["overall_v"]
    M["fin_speed_pct"] = 100.0 * M["late_rel"]
    M.loc[~M["sane"], ["late_rel", "fin_speed_pct", "early_v", "late_v"]] = np.nan
    # field size with sections at the style point -> run-style percentile (0 = led, 1 = last)
    race_max = M[M["sane"]].groupby("rtv_race_id")["nsec"].max().rename("race_nsec")
    M = M.merge(race_max, on="rtv_race_id", how="left")
    M["full"] = M["sane"] & (M["nsec"] == M["race_nsec"])
    nfield = M[M["full"]].groupby("rtv_race_id").size().rename("n_full")
    M = M.merge(nfield, on="rtv_race_id", how="left")
    M["style_pct"] = np.where(M["full"] & (M["n_full"] > 1), (M["style_pos"] - 1) / (M["n_full"] - 1), np.nan)
    M["style_pct"] = M["style_pct"].clip(0, 1)
    M["early_pct"] = np.where(M["full"] & (M["n_full"] > 1), (M["early_pos"] - 1) / (M["n_full"] - 1), np.nan)
    M["early_pct"] = pd.Series(M["early_pct"]).clip(0, 1)
    info["runners_with_sections"] = int(len(M))
    info["runners_sane"] = int(M["sane"].sum())
    info["first_len_q"] = [float(x) for x in M["first_len"].quantile([0.01, 0.05, 0.5, 0.95, 0.99]).round(1)]
    ok = M["sane"] & M["finishing_speed_pct"].between(70, 140)
    if ok.sum() > 100:
        info["fsp_corr_vs_rtv"] = float(np.corrcoef(M.loc[ok, "fin_speed_pct"], M.loc[ok, "finishing_speed_pct"])[0, 1])
        info["fsp_mean_diff_vs_rtv"] = float((M.loc[ok, "fin_speed_pct"] - M.loc[ok, "finishing_speed_pct"]).mean())
    log(f"  runner metrics: {info['runners_sane']:,}/{info['runners_with_sections']:,} runners with sane sections ({time.time()-t0:.0f}s)")
    return M, info, R, S


# ---------------------------------------------------------------- race shape + pars
def race_shape(R: pd.DataFrame, M: pd.DataFrame) -> pd.DataFrame:
    F = M[M["full"]].copy()
    F["fp"] = pd.to_numeric(F["finish_position"], errors="coerce")
    F = F.sort_values(["rtv_race_id", "fp"], na_position="last")
    ref = F[F["fp"].notna()].groupby("rtv_race_id").head(1)[["rtv_race_id", "overall_v", "total_t", "fp", "horse_name"]]
    ref = ref.rename(columns={"overall_v": "ref_v", "total_t": "ref_t", "fp": "ref_pos", "horse_name": "ref_horse"})
    top3 = F[F["fp"].notna() & (F["fp"] <= 3)].groupby("rtv_race_id")["late_rel"].mean().rename("L")
    lead = F.groupby("rtv_race_id").agg(lead_early_t=("early_t", "min"), early_d=("early_d", "first"),
                                        n_full=("rtv_runner_id", "size"))
    out = R.merge(ref, on="rtv_race_id", how="left").merge(top3, on="rtv_race_id", how="left").merge(lead, on="rtv_race_id", how="left")
    out["E"] = (out["early_d"] / out["lead_early_t"]) / out["ref_v"]
    out["fl"] = (out["dist_y"] / FURLONG).round().astype("Int64")
    out["ck"] = out["course"].map(join_key)
    out["gn"] = np.where(out["fam"] == "AW", np.nan, out["going"].map(going_n))
    out["band"] = [dist_band(f, (d or 0) / FURLONG) if pd.notna(d) else "" for f, d in zip(out["fam"], out["dist_y"])]
    out["sound"] = (out["n_full"].fillna(0) >= 4) & out["ref_v"].notna() & out["E"].between(0.8, 1.3) & out["L"].between(0.8, 1.3)
    return out


def going_slopes(X: pd.DataFrame, col: str) -> dict:
    """Within-course/trip slope of a shape ratio on the measured going allowance (sec/furlong)."""
    out = {}
    for fam, g in X[X["sound"] & X["gxc"].notna()].groupby("fam"):
        k = g["ck"] + "|" + g["fl"].astype(str)
        y = g[col] - g.groupby(k)[col].transform("mean")
        x = g["gxc"] - g.groupby(k)["gxc"].transform("mean")
        den = float((x * x).sum())
        out[fam] = float((x * y).sum() / den) if den > 0 else 0.0
    return out


def add_going(X: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """gxc = going allowance (speed_v4, s/f) minus the code's typical value. Races without one
    get it estimated from the official going (turf) or the typical value (0)."""
    X = X.copy()
    info = {}
    X["ga"] = pd.to_numeric(X.get("ga"), errors="coerce")
    X["gxc"] = np.nan
    for fam, g in X.groupby("fam"):
        c = float(g.loc[g["sound"] & g["ga"].notna(), "ga"].median()) if g["ga"].notna().any() else 0.0
        v = g["ga"] - c
        fit = g[g["ga"].notna() & g["gn"].notna()]
        if len(fit) > 200 and fit["gn"].std() > 0:
            slope, icpt = np.polyfit(fit["gn"], fit["ga"] - c, 1)
            v = v.fillna(icpt + slope * g["gn"])
        X.loc[g.index, "gxc"] = v.fillna(0.0).clip(-1.5, 3.0)
        info[fam] = {"typical_ga": round(c, 3), "share_measured": round(float(g["ga"].notna().mean()), 3)}
    return X, info


LEVELS = [("course_trip", ["ck", "fam", "fl"]), ("course_band", ["ck", "fam", "band"]),
          ("all_trip", ["fam", "fl"]), ("all_band", ["fam", "band"]), ("code", ["fam"])]


def build_shape_pars(X: pd.DataFrame, fit_mask: pd.Series | None = None):
    """Par E and L for every race, going-adjusted, pooled when a combo is sparse."""
    X = X.copy()
    base = X["sound"] if fit_mask is None else (X["sound"] & fit_mask)
    slopes = {c: going_slopes(X[base], c) for c in ("E", "L")}
    for c in ("E", "L"):
        b = X["fam"].map(slopes[c]).fillna(0.0)
        X[f"{c}_b"] = b
        X[f"{c}_r"] = X[c] - b * X["gxc"]
    X["par_level"] = ""
    X["par_n"] = 0
    X["parE_r"] = np.nan
    X["parL_r"] = np.nan
    tables = []
    for name, cols in LEVELS:
        t = X[base].groupby(cols).agg(n=("E_r", "size"), pE=("E_r", "median"), pL=("L_r", "median")).reset_index()
        t = t[t["n"] >= (MIN_PAR_N if name != "code" else 1)]
        tt = t.copy(); tt["level"] = name; tables.append(tt)
        need = X["par_level"] == ""
        m = X.loc[need, cols].merge(t, on=cols, how="left")
        hit = m["n"].notna().to_numpy()
        idx = X.index[need][hit]
        X.loc[idx, "parE_r"] = m.loc[hit, "pE"].to_numpy()
        X.loc[idx, "parL_r"] = m.loc[hit, "pL"].to_numpy()
        X.loc[idx, "par_n"] = m.loc[hit, "n"].astype(int).to_numpy()
        X.loc[idx, "par_level"] = name
    X["parE"] = X["parE_r"] + X["E_b"] * X["gxc"]
    X["parL"] = X["parL_r"] + X["L_b"] * X["gxc"]
    X["e_dev"] = 100.0 * (X["E"] / X["parE"] - 1.0)
    X["l_dev"] = 100.0 * (X["L"] / X["parL"] - 1.0)
    X["pi"] = X["e_dev"] - X["l_dev"]
    X["pooled"] = ~X["par_level"].isin(["course_trip", "course_band"])
    return X, slopes, pd.concat(tables, ignore_index=True)


def section_pars(R2: pd.DataFrame, M: pd.DataFrame, S: pd.DataFrame) -> pd.DataFrame:
    """Per-section par times (winner, sound races) per course + code/surface + trip.

    One standard per (course, code/surface, rounded trip). Rail moves stay in that
    standard. The first section carries the extra/fewer yards and is normalised to
    the median first-section length before the par is taken; later sections are a
    furlong. Pars are going-neutral using v4 going allowances (seconds / furlong).
    """
    keep = ["rtv_race_id", "ck", "fl", "gxc"]
    if "ga" in R2.columns:
        keep.append("ga")
    if "dist_y" in R2.columns:
        keep.append("dist_y")
    snd = R2[R2["sound"]][keep]
    win = M[M["full"]].merge(snd, on="rtv_race_id")
    win = win[pd.to_numeric(win["finish_position"], errors="coerce") == 1].copy()
    cols = ["rtv_race_id", "rtv_runner_id", "ck", "fl", "gxc", "overall_v", "first_len", "nsec", "fam"]
    if "ga" in win.columns:
        cols.append("ga")
    if "dist_y" in win.columns:
        cols.append("dist_y")
    win = win[[c for c in cols if c in win.columns]]
    base = win.groupby(["ck", "fam", "fl"], as_index=False).agg(
        base_yards=("dist_y", "median") if "dist_y" in win.columns else ("first_len", "median"),
        base_first_len=("first_len", "median"),
        n_races=("rtv_race_id", "nunique"),
    )
    if "dist_y" not in win.columns:
        base["base_yards"] = base["base_first_len"]  # shouldn't happen
    drop = [c for c in win.columns if c in S.columns and c not in ("rtv_race_id", "rtv_runner_id")]
    s = S.drop(columns=drop).merge(win, on=["rtv_race_id", "rtv_runner_id"])
    # always keep the first section (rail-move yards live there) plus the last 12 furlongs
    s = s[(s["kend"] < 12) | (s["sector_number"] == 0)].copy()
    s = s.merge(base, on=["ck", "fam", "fl"], how="left")
    s["sec_len"] = np.where(s["sector_number"] == 0, s["first_len"], FURLONG)
    s["base_len"] = np.where(s["sector_number"] == 0, s["base_first_len"], FURLONG)
    s["time_at_base"] = np.where(
        (s["sector_number"] == 0) & s["first_len"].notna() & (s["first_len"] > 0) & s["base_first_len"].notna(),
        s["sector_time"] * (s["base_first_len"] / s["first_len"]),
        s["sector_time"],
    )
    ga = pd.to_numeric(s["ga"], errors="coerce") if "ga" in s.columns else pd.Series(np.nan, index=s.index)
    s["t_adj"] = s["time_at_base"] - ga.fillna(0.0) * (s["base_len"] / FURLONG)
    grp = ["ck", "fam", "fl", "kend", "sector_number"]
    p = s.groupby(grp, as_index=False).agg(
        n=("t_adj", "size"),
        par_time_s=("t_adj", "median"),
        base_len_y=("base_len", "median"),
        base_first_len=("base_first_len", "median"),
        base_yards=("base_yards", "median"),
        n_races=("rtv_race_id", "nunique"),
    )
    # also keep a relative-speed par for the existing shape / finishing-speed work
    s["rel"] = np.where(s["sec_len"] > 0, (s["sec_len"] / s["sector_time"]) / s["overall_v"], np.nan)
    rel = s.groupby(grp, as_index=False).agg(par_rel_speed=("rel", "median"))
    p = p.merge(rel, on=grp, how="left")
    p["section"] = np.where(p["sector_number"] == 0, "first section (includes rail-move yards)",
                   np.where(p["kend"] == 0, "final furlong",
                            "furlong " + (p["kend"] + 1).astype(str) + " from home"))
    p["low_sample"] = p["n"] < MIN_PAR_N
    return p.rename(columns={"ck": "course", "fam": "code", "fl": "furlongs"})


def section_figures(X: pd.DataFrame, M: pd.DataFrame, S: pd.DataFrame, SP: pd.DataFrame,
                    F: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Section-by-section and full-race figures from exact-distance section pars.

    expected = par_at_base * (this_length / base_length) + v4_going * (this_length / 220).
    Full-race figure uses the sum of those expected section times vs the runner's
    sectional total; the winner also gets a figure vs v4's chosen official time.
    """
    try:
        import speedfig_v3 as _v3
        base_fig = float(_v3.BASE_FIG)
    except Exception:
        base_fig = 100.0
    pars = SP.rename(columns={"course": "ck", "code": "fam", "furlongs": "fl"})
    need = ["ck", "fam", "fl", "kend", "sector_number", "par_time_s", "base_len_y"]
    if any(c not in pars.columns for c in need):
        return pd.DataFrame(), pd.DataFrame()
    race_keys = X[["rtv_race_id", "ck", "fl", "fam"]].drop_duplicates("rtv_race_id") if "fam" in X.columns else X[["rtv_race_id", "ck", "fl"]].drop_duplicates("rtv_race_id")
    if "fam" not in race_keys.columns and "fam" in M.columns:
        race_keys = race_keys.merge(M[["rtv_race_id", "fam"]].drop_duplicates("rtv_race_id"), on="rtv_race_id", how="left")
    if "ga" in X.columns:
        race_keys = race_keys.merge(X[["rtv_race_id", "ga"]].drop_duplicates("rtv_race_id"), on="rtv_race_id", how="left")
    if "race_id" in X.columns:
        race_keys = race_keys.merge(X[["rtv_race_id", "race_id"]].drop_duplicates("rtv_race_id"), on="rtv_race_id", how="left")

    mm = M.merge(race_keys, on="rtv_race_id", how="left", suffixes=("", "_x"))
    for c in ("fam", "ck", "fl"):
        if c + "_x" in mm.columns:
            mm[c] = mm[c].where(mm[c].notna(), mm[c + "_x"]) if c in mm.columns else mm[c + "_x"]
    mm_cols = ["rtv_race_id", "rtv_runner_id", "ck", "fl", "fam", "first_len", "full", "sane",
               "horse_name", "total_t", "finish_position"] + [c for c in ("ga", "race_id") if c in mm.columns]
    mm_cols = [c for c in mm_cols if c in mm.columns]
    drop = [c for c in mm_cols if c in S.columns and c not in ("rtv_race_id", "rtv_runner_id")]
    s = S.drop(columns=drop).merge(mm[mm_cols], on=["rtv_race_id", "rtv_runner_id"], how="left")
    s = s[s["sane"].fillna(False) & s["full"].fillna(False)].copy()
    s["sec_len"] = np.where(s["sector_number"] == 0, s["first_len"], FURLONG)
    s = s.merge(pars[need], on=["ck", "fam", "fl", "kend", "sector_number"], how="left")
    # first-section rows use sector_number==0, which may also have kend >= 12 and still be in pars
    ga = pd.to_numeric(s["ga"], errors="coerce") if "ga" in s.columns else pd.Series(0.0, index=s.index)
    scale = np.where(s["base_len_y"].notna() & (s["base_len_y"] > 0), s["sec_len"] / s["base_len_y"], 1.0)
    s["expected_s"] = s["par_time_s"] * scale + ga.fillna(0.0) * (s["sec_len"] / FURLONG)

    # v4 runner context: lbs/sec, weights, chosen official time
    fcols = [c for c in ("race_id", "hk", "lbs_per_sec", "weight_lb", "base_wt", "eff_wt", "win_time", "horse_id") if c in F.columns]
    if "hk" not in s.columns:
        s["hk"] = s["horse_name"].map(horse_key)
    if fcols and "race_id" in s.columns:
        s = s.merge(F[fcols].drop_duplicates([c for c in ("race_id", "hk") if c in fcols]),
                    on=[c for c in ("race_id", "hk") if c in fcols], how="left")
    # official chosen time from v4 corrections (three-way rule), if not already on F
    if V4CORR.is_file() and "race_id" in s.columns:
        try:
            dc = pd.read_csv(V4CORR, usecols=lambda c: c in {"race_id", "win_time_used", "time_src", "time_flag", "exact_yards"})
            s = s.merge(dc.drop_duplicates("race_id"), on="race_id", how="left")
        except Exception:
            pass
    lbps = pd.to_numeric(s["lbs_per_sec"], errors="coerce") if "lbs_per_sec" in s.columns else pd.Series(np.nan, index=s.index)
    s["section_fig"] = (s["expected_s"] - s["sector_time"]) * lbps

    # full-race from summed section pars vs sectional total
    gcols = ["rtv_race_id", "rtv_runner_id"]
    tot = s.groupby(gcols, as_index=False).agg(
        expected_total_s=("expected_s", "sum"),
        sections_scored=("expected_s", "count"),
        nsec=("sector_number", "size"),
        sect_time_sum=("sector_time", "sum"),
    )
    meta = s.drop_duplicates(gcols)[gcols + [c for c in (
        "race_id", "horse_name", "horse_id", "hk", "finish_position", "total_t", "ga",
        "lbs_per_sec", "weight_lb", "base_wt", "eff_wt", "win_time", "win_time_used",
        "time_src", "first_len", "full", "sane") if c in s.columns]]
    tot = tot.merge(meta, on=gcols, how="left")
    tot_t = tot["total_t"].where(tot["total_t"].notna(), tot["sect_time_sum"])
    lbps_r = pd.to_numeric(tot["lbs_per_sec"], errors="coerce") if "lbs_per_sec" in tot.columns else pd.Series(np.nan, index=tot.index)
    tot["sect_fig"] = base_fig + (tot["expected_total_s"] - tot_t) * lbps_r
    if "eff_wt" in tot.columns and "base_wt" in tot.columns:
        tot["sect_fig_weighted"] = tot["sect_fig"] + (pd.to_numeric(tot["eff_wt"], errors="coerce") - pd.to_numeric(tot["base_wt"], errors="coerce"))
    elif "weight_lb" in tot.columns and "base_wt" in tot.columns:
        tot["sect_fig_weighted"] = tot["sect_fig"] + (pd.to_numeric(tot["weight_lb"], errors="coerce") - pd.to_numeric(tot["base_wt"], errors="coerce"))
    else:
        tot["sect_fig_weighted"] = tot["sect_fig"]
    # winner vs v4 chosen official time (same expected total)
    official = pd.to_numeric(tot["win_time_used"], errors="coerce") if "win_time_used" in tot.columns else pd.Series(np.nan, index=tot.index)
    if official.isna().all() and "win_time" in tot.columns:
        official = pd.to_numeric(tot["win_time"], errors="coerce")
    is_win = pd.to_numeric(tot["finish_position"], errors="coerce") == 1
    tot["sect_fig_official"] = np.where(is_win & official.notna(),
                                        base_fig + (tot["expected_total_s"] - official) * lbps_r,
                                        np.nan)

    long_cols = [c for c in (
        "race_id", "rtv_race_id", "horse_name", "horse_id", "finish_position",
        "sector_number", "kend", "sec_len", "base_len_y", "sector_time", "par_time_s",
        "expected_s", "section_fig", "ga", "time_src") if c in s.columns]
    return s[long_cols], tot


# ------------------------------------------------------------------ figure joins
FIG_COLS = ["race_id", "date", "off_time", "course_raw", "course", "surface", "code", "dist_f", "going", "class",
            "horse", "age", "offr", "place", "weighted_fig", "fig_2yo_weighted", "horse_norm", "yob", "horse_id",
            "going_allowance_spf", "lbs_per_sec", "win_time", "std_time", "weight_lb", "base_wt", "eff_wt",
            "lbs_per_length"]


def load_figs() -> pd.DataFrame:
    if not FIGCSV.is_file():
        fail(f"Missing {FIGCSV}. Run BUILD_MASTER.bat (or tools\\speedfig_v4.py) first.")
    t0 = time.time()
    F = pd.read_csv(FIGCSV, usecols=lambda c: c in FIG_COLS, low_memory=False)
    F["date"] = F["date"].astype(str).str[:10]
    src = F["course_raw"] if "course_raw" in F.columns else F["course"]
    cmap = {c: join_key(c) for c in src.dropna().unique()}
    F["ck"] = src.map(cmap).fillna("")
    tmap = {t: hhmm(t) for t in F["off_time"].dropna().unique()}
    F["hh"] = F["off_time"].map(tmap).fillna("")
    F["hk"] = F["horse"].map(horse_key)
    F["is_j"] = F["code"].astype(str).isin(JUMPS) | F["code"].astype(str).str.contains("Hurdle|Chase|NHF", case=False)
    log(f"  speed_v4 figures: {len(F):,} runs in {F['race_id'].nunique():,} races, {F['date'].min()} to {F['date'].max()} ({time.time()-t0:.0f}s)")
    return F


def join_races(X: pd.DataFrame, M: pd.DataFrame, F: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """rtv_race_id -> fig race_id. Exact date+course+time, then best horse overlap on the day."""
    FR = F.groupby("race_id").agg(date=("date", "first"), ck=("ck", "first"), hh=("hh", "first")).reset_index()
    fh = F.groupby("race_id")["hk"].apply(lambda s: frozenset(s)).to_dict()
    rh = M.assign(hk=M["horse_name"].map(horse_key)).groupby("rtv_race_id")["hk"].apply(lambda s: frozenset(s)).to_dict()

    def overlap(rid, fid) -> float:
        a, b = rh.get(rid, frozenset()), fh.get(fid, frozenset())
        if not a or not b:
            return 0.0
        return len(a & b) / min(len(a), len(b))

    lo, hi = FR["date"].min(), FR["date"].max()
    base = X[["rtv_race_id", "race_date", "ck", "off_time", "has_sectionals", "country"]].copy()
    base["hh"] = base["off_time"].map(hhmm)
    base["in_range"] = base["race_date"].between(lo, hi)
    by_key: dict[tuple, list[str]] = {}
    for fid, d, c, h in FR[["race_id", "date", "ck", "hh"]].itertuples(index=False):
        by_key.setdefault((d, c, h), []).append(fid)
    by_day: dict[tuple, list[tuple[str, str]]] = {}
    for fid, d, c, h in FR[["race_id", "date", "ck", "hh"]].itertuples(index=False):
        by_day.setdefault((d, c), []).append((fid, h))
    match, how, ov = {}, {}, {}
    used: dict[str, tuple[int, float]] = {}
    # pass 1: exact time
    for rid, d, c, h in base[["rtv_race_id", "race_date", "ck", "hh"]].itertuples(index=False):
        cands = by_key.get((d, c, h)) or []
        if not cands:
            continue
        best = max(cands, key=lambda f: overlap(rid, f))
        o = overlap(rid, best)
        if rh.get(rid) and o < 0.3:
            continue          # same time but different horses: leave for pass 2
        match[rid], how[rid], ov[rid] = best, "exact", o
        used[best] = (rid, o)
    # pass 2: same day + course, unmatched, best horse overlap (handles time changes / clock drift)
    for rid, d, c, h in base[["rtv_race_id", "race_date", "ck", "hh"]].itertuples(index=False):
        if rid in match:
            continue
        best, bo = None, 0.0
        for fid, fh_ in by_day.get((d, c)) or []:
            if fid in used:
                continue
            o = overlap(rid, fid)
            if o > bo:
                best, bo = fid, o
        if best is not None and bo >= 0.5:
            match[rid], how[rid], ov[rid] = best, "horses", bo
            used[best] = (rid, bo)
    base["race_id"] = base["rtv_race_id"].map(match)
    base["join_how"] = base["rtv_race_id"].map(how).fillna("")
    base["join_overlap"] = base["rtv_race_id"].map(ov)
    days_with_figs = set(zip(FR["date"], FR["ck"]))
    base["meeting_in_figs"] = [(d, c) in days_with_figs for d, c in zip(base["race_date"], base["ck"])]
    rep = {}
    sub = base[base["in_range"] & (base["has_sectionals"] == 1)]
    rep["sect_races_in_fig_range"] = int(len(sub))
    rep["sect_races_matched"] = int(sub["race_id"].notna().sum())
    rep["sect_match_rate"] = float(sub["race_id"].notna().mean()) if len(sub) else float("nan")
    sm = sub[sub["meeting_in_figs"]]
    rep["sect_races_meeting_in_figs"] = int(len(sm))
    rep["sect_match_rate_meeting_in_figs"] = float(sm["race_id"].notna().mean()) if len(sm) else float("nan")
    rep["by_how"] = {k: int(v) for k, v in sub["join_how"].value_counts().items()}
    rep["by_country"] = {k: float(v) for k, v in sub.groupby("country")["race_id"].apply(lambda s: s.notna().mean()).items()}
    rep["low_overlap_exact"] = int(((sub["join_how"] == "exact") & (sub["join_overlap"] < 0.6)).sum())
    miss = sm[sm["race_id"].isna()]
    rep["unmatched_examples"] = miss.head(12)[["race_date", "ck", "off_time"]].astype(str).values.tolist()
    return base, rep


def join_runners(M: pd.DataFrame, races: pd.DataFrame, F: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    m = M.merge(races[["rtv_race_id", "race_id"]], on="rtv_race_id", how="left")
    m["hk"] = m["horse_name"].map(horse_key)
    f = F[["race_id", "hk", "horse_id", "horse_norm", "place", "weighted_fig"]].drop_duplicates(["race_id", "hk"])
    j = m.merge(f, on=["race_id", "hk"], how="left")
    # fallback: same race, same finishing position, first 4 letters agree (spelling variants)
    need = j["race_id"].notna() & j["horse_id"].isna() & j["finish_position"].notna()
    if need.any():
        taken = set(zip(j.loc[j["horse_id"].notna(), "race_id"], j.loc[j["horse_id"].notna(), "hk"]))
        fp = F[["race_id", "place", "hk", "horse_id", "horse_norm", "weighted_fig"]].copy()
        fp = fp[[(r, h) not in taken for r, h in zip(fp["race_id"], fp["hk"])]]
        fp = fp.drop_duplicates(["race_id", "place"], keep=False)
        k = j.loc[need, ["race_id", "finish_position", "hk"]].reset_index()
        k = k.merge(fp.rename(columns={"place": "finish_position", "hk": "hk_f"}), on=["race_id", "finish_position"], how="inner")
        k = k[k["hk"].str[:4] == k["hk_f"].str[:4]]
        for c in ("horse_id", "horse_norm", "weighted_fig"):
            j.loc[k["index"].to_numpy(), c] = k[c].to_numpy()
        j.loc[k["index"].to_numpy(), "place"] = k["finish_position"].to_numpy()
    inr = j["race_id"].notna()
    fin = inr & j["finish_position"].notna()
    rep = {
        "runners_in_matched_races": int(inr.sum()),
        "runner_match_rate": float(j.loc[inr, "horse_id"].notna().mean()) if inr.any() else float("nan"),
        "finisher_match_rate": float(j.loc[fin, "horse_id"].notna().mean()) if fin.any() else float("nan"),
        "sane_runner_match_rate": float(j.loc[inr & j["sane"], "horse_id"].notna().mean()) if (inr & j["sane"]).any() else float("nan"),
        "position_agreement": float((pd.to_numeric(j.loc[fin & j["horse_id"].notna(), "place"], errors="coerce") ==
                                     j.loc[fin & j["horse_id"].notna(), "finish_position"]).mean()) if fin.any() else float("nan"),
    }
    return j, rep


def field_deviation(F: pd.DataFrame) -> pd.Series:
    """Each figure minus the horse's leave-one-out mean in the same code group (needs 3+ other runs)."""
    fig = pd.to_numeric(F["weighted_fig"], errors="coerce")
    key = F["horse_id"].astype(str) + "|" + F["is_j"].astype(str)
    ok = fig.notna()
    s = fig.where(ok, 0.0).groupby(key).transform("sum")
    n = ok.astype(int).groupby(key).transform("sum")
    loo = (s - fig) / (n - 1)
    return (fig - loo).where(ok & (n - 1 >= 3))


# ------------------------------------------------------------ labels + adjustments
STY_BINS = [-0.01, 0.2, 0.45, 0.7, 1.01]
STY_LABELS = ["front", "prom", "mid", "rear"]
PLATEAU = range(3, 9)       # PI deciles treated as "truly run" reference
SHRINK_N = 300.0
ADJ_CAP = 10.0
FLAG_LB = 4.0               # adjustment (lb) at which a run is flagged understated / overstated


GRP_NAME = {"F": "Turf Flat", "A": "All-weather", "J": "Jumps"}


def grp_of(fam: pd.Series) -> pd.Series:
    return pd.Series(np.where(fam.isin(list(JUMPS)), "J", np.where(fam == "AW", "A", "F")), index=fam.index)


MEET_K = 3.0


def meeting_offsets(X: pd.DataFrame) -> pd.DataFrame:
    """Sectional 'going allowance': wind / ground that the going figure misses shows up as every race
    at a meeting finishing slower (or quicker) than par. Remove a shrunk leave-one-out meeting mean."""
    X = X.copy()
    ok = X["e_dev"].notna() & X["l_dev"].notna() & (X["n_full"].fillna(0) >= 2)
    key = X["race_date"].astype(str) + "|" + X["ck"].astype(str) + "|" + grp_of(X["fam"])
    for c in ("e_dev", "l_dev"):
        v = X[c].clip(-10, 10).where(ok)
        ssum = v.fillna(0).groupby(key).transform("sum")
        n = v.notna().groupby(key).transform("sum")
        loo_n = n - ok.astype(int)
        loo = (ssum - v.fillna(0)) / loo_n.where(loo_n > 0)
        off = (loo * loo_n / (loo_n + MEET_K)).fillna(0.0)
        X[f"{c}_meet"] = off.where(ok, 0.0)
        X[f"{c}_raw"] = X[c]
        X[c] = X[c] - X[f"{c}_meet"]
    X["pi"] = X["e_dev"] - X["l_dev"]
    return X


def pace_settings(X: pd.DataFrame) -> dict:
    """PI percentiles (label thresholds) and decile edges per group, from sound races."""
    out = {}
    for g, d in X[X["sound"] & X["pi"].notna()].groupby(grp_of(X["fam"])):
        q = d["pi"].quantile([i / 10 for i in range(1, 10)]).tolist()
        out[g] = {"p10": float(d["pi"].quantile(0.10)), "p30": float(d["pi"].quantile(0.30)),
                  "p90": float(d["pi"].quantile(0.90)), "deciles": [float(x) for x in q], "n": int(len(d))}
    return out


def label_races(X: pd.DataFrame, st: dict) -> pd.DataFrame:
    X = X.copy()
    X["grp"] = grp_of(X["fam"])
    X["labelable"] = X["pi"].notna() & (X["n_full"].fillna(0) >= 2) & X["parE"].notna()
    prof = np.full(len(X), "", dtype=object)
    pib = np.full(len(X), -1)
    for g, s in st.items():
        m = (X["grp"] == g) & X["labelable"]
        pi = X.loc[m, "pi"]
        p = np.where(pi <= s["p10"], "Slow", np.where(pi <= s["p30"], "Steady", np.where(pi >= s["p90"], "Fast-early", "True")))
        prof[m.to_numpy()] = p
        pib[m.to_numpy()] = np.searchsorted(np.array(s["deciles"]), pi.to_numpy(), side="right")
    X["profile"] = prof
    X["pi_bin"] = pib
    return X


def fit_adjust(RJ: pd.DataFrame, mask: pd.Series | None = None) -> pd.DataFrame:
    """Mean figure deviation by pace decile x run style, relative to truly-run races."""
    d = RJ[RJ["dev"].notna() & (RJ["pi_bin"] >= 0) & RJ["sound"]]
    if mask is not None:
        d = d[mask.reindex(d.index).fillna(False)]
    rows = []
    for g, dg in d.groupby("grp"):
        for sty in STY_LABELS + ["all"]:
            ds = dg if sty == "all" else dg[dg["sty"] == sty]
            if ds.empty:
                continue
            ref = ds.loc[ds["pi_bin"].isin(list(PLATEAU)), "dev"].mean()
            cell = ds.groupby("pi_bin")["dev"].agg(["mean", "size"])
            for b, r in cell.iterrows():
                raw = ref - r["mean"]
                adj = float(np.clip(raw * r["size"] / (r["size"] + SHRINK_N), -ADJ_CAP, ADJ_CAP))
                rows.append({"grp": g, "sty": sty, "pi_bin": int(b), "n": int(r["size"]), "mean_dev": float(r["mean"]),
                             "ref_dev": float(ref), "adj": round(adj, 2)})
    return pd.DataFrame(rows)


def apply_adjust(RJ: pd.DataFrame, tab: pd.DataFrame) -> pd.Series:
    t = tab.set_index(["grp", "sty", "pi_bin"])["adj"]
    sty = RJ["sty"].astype(object).where(RJ["sty"].notna(), "all")
    k1 = list(zip(RJ["grp"], sty, RJ["pi_bin"]))
    k2 = list(zip(RJ["grp"], ["all"] * len(RJ), RJ["pi_bin"]))
    a = pd.Series([t.get(a_, t.get(b_, np.nan)) for a_, b_ in zip(k1, k2)], index=RJ.index, dtype=float)
    return a.where(RJ["pi_bin"] >= 0)


def race_adjust(X: pd.DataFrame, tab: pd.DataFrame) -> pd.Series:
    t = tab[tab["sty"] == "all"].set_index(["grp", "pi_bin"])["adj"]
    return pd.Series([t.get((g, b), np.nan) if b >= 0 else np.nan for g, b in zip(X["grp"], X["pi_bin"])], index=X.index)


# ------------------------------------------------------------------ core pipeline
def compute(start: str | None = None, end: str | None = None, adj_before: str | None = None) -> dict:
    t0 = time.time()
    log("Step 1/5  Loading sectionals and figures (read-only)...")
    R, U, S = load_sectionals(start, end)
    M, minfo, R, S = runner_metrics(R, U, S)
    F = load_figs()
    if "hk" not in F.columns and "horse" in F.columns:
        F["hk"] = F["horse"].map(horse_key)
    log("Step 2/5  Race pace shape...")
    X = race_shape(R, M)
    log("Step 3/5  Joining to speed_v4 figures...")
    races, jrep = join_races(X, M, F)
    J, rrep = join_runners(M, races, F)
    X = X.merge(races[["rtv_race_id", "race_id", "join_how", "join_overlap"]], on="rtv_race_id", how="left")
    log(f"  sectional races matched to a figure race: {jrep['sect_match_rate_meeting_in_figs']:.2%} "
        f"(of races whose meeting is in the figures); finishers matched: {rrep['finisher_match_rate']:.3%}")
    ga = pd.to_numeric(F["going_allowance_spf"], errors="coerce").groupby(F["race_id"]).median() if "going_allowance_spf" in F.columns else pd.Series(dtype=float)
    X["ga"] = X["race_id"].map(ga)
    X, ginfo = add_going(X)
    X, slopes, par_tables = build_shape_pars(X)
    X = meeting_offsets(X)
    SP = section_pars(X, M, S)
    log("  section pars on exact yards (extra rail-move distance in the first section)")
    SF, SFr = section_figures(X, M, S, SP, F)
    log(f"  section figures: {len(SF):,} runner-sections, {len(SFr):,} runner full-race figures")
    del S
    st = pace_settings(X)
    X = label_races(X, st)
    log("Step 4/5  Figure adjustments by pace shape and run style...")
    F["dev"] = field_deviation(F)
    fd = F.groupby("race_id")["dev"].agg(["median", "count"]).rename(columns={"median": "field_def_v12", "count": "n_dev"})
    X = X.merge(fd, left_on="race_id", right_index=True, how="left")
    RJ = J.drop(columns=["fam"]).merge(
        X[["rtv_race_id", "race_date", "course", "off_time", "fam", "grp", "sound", "pi", "pi_bin", "profile",
           "parL", "l_dev", "e_dev", "l_dev_meet", "pooled", "par_level"]], on="rtv_race_id", how="left")
    RJ = RJ.merge(F[["race_id", "hk", "dev"]].drop_duplicates(["race_id", "hk"]), on=["race_id", "hk"], how="left")
    RJ["sty"] = pd.cut(RJ["style_pct"], STY_BINS, labels=STY_LABELS).astype(object)
    RJ["fsp_vs_par"] = 100.0 * (RJ["late_rel"] / RJ["parL"] - 1.0) - RJ["l_dev_meet"].fillna(0.0)
    mask = (RJ["race_date"] < adj_before) if adj_before else None
    tab = fit_adjust(RJ, mask)
    RJ["adj"] = apply_adjust(RJ, tab)
    X["race_adj"] = race_adjust(X, tab)
    RJ["fig"] = pd.to_numeric(RJ["weighted_fig"], errors="coerce")
    RJ["fig_adj"] = RJ["fig"] + RJ["adj"].fillna(0.0)
    RJ["fig_flag"] = np.where(RJ["adj"] >= FLAG_LB, "understated", np.where(RJ["adj"] <= -FLAG_LB, "overstated", ""))
    RJ["unreliable"] = ((RJ["adj"].abs() >= FLAG_LB) | (RJ["profile"] == "Slow")).astype(int)
    log(f"  done in {time.time()-t0:.0f}s")
    if len(SFr):
        RJ = RJ.merge(SFr[["rtv_race_id", "rtv_runner_id", "sect_fig", "sect_fig_weighted", "sect_fig_official",
                            "expected_total_s"]].drop_duplicates(["rtv_race_id", "rtv_runner_id"]),
                      on=["rtv_race_id", "rtv_runner_id"], how="left")
    return {"X": X, "RJ": RJ, "F": F, "SP": SP, "SF": SF, "SFr": SFr, "par_tables": par_tables, "slopes": slopes, "settings": st,
            "adj_table": tab, "join": jrep, "runner_join": rrep, "minfo": minfo, "going": ginfo}


# ------------------------------------------------------------------- site pace
SITE_LABEL = {"Slow": "slow", "Steady": "steady", "True": "true", "Fast-early": "true"}
PROFILE_TEXT = {"Slow": "Slow-run (sprint finish)", "Steady": "Steady early, quicker finish",
                "True": "Truly run", "Fast-early": "Fast early (strong pace, tested stamina)"}


def race_pace_table(X: pd.DataFrame, RJ: pd.DataFrame) -> pd.DataFrame:
    lab = X[X["profile"] != ""].copy()
    win = RJ[pd.to_numeric(RJ["finish_position"], errors="coerce") == 1].drop_duplicates("rtv_race_id")
    lab = lab.merge(win[["rtv_race_id", "fin_speed_pct", "finishing_speed_pct"]], on="rtv_race_id", how="left")
    hs = RJ.groupby("rtv_race_id")["hk"].apply(lambda s: ",".join(dict.fromkeys(h for h in s if h))).rename("horses_sec")
    lab = lab.merge(hs, on="rtv_race_id", how="left")
    lab["win_fsp"] = lab["finishing_speed_pct"].where(lab["finishing_speed_pct"].between(70, 140), lab["fin_speed_pct"])
    lab["label"] = lab["profile"].map(SITE_LABEL)
    lab["fig_rel_sec"] = np.where((lab["profile"] == "Slow") | (lab["race_adj"] >= 4.0), "low",
                                  np.where(lab["race_adj"] <= -3.0, "suspect", "ok"))

    def reason(r) -> str:
        e, l = r["e_dev"], r["l_dev"]
        bits = [f"{PROFILE_TEXT[r['profile']]}: early pace {abs(e):.1f}% {'quicker' if e >= 0 else 'slower'} than the course par, "
                f"finish {abs(l):.1f}% {'quicker' if l >= 0 else 'slower'} than par"]
        if pd.notna(r["win_fsp"]):
            bits.append(f"winner's finishing speed {r['win_fsp']:.0f}%")
        if pd.notna(r["race_adj"]) and r["race_adj"] >= 2.0:
            bits.append(f"figures likely understated by about {r['race_adj']:.0f} lb")
        elif pd.notna(r["race_adj"]) and r["race_adj"] <= -2.0:
            bits.append(f"figures may flatter by about {abs(r['race_adj']):.0f} lb")
        s = "; ".join(bits)
        lm = r.get("l_dev_meet")
        if pd.notna(lm) and abs(lm) >= 2.0:
            s += (f" (the whole meeting finished about {abs(lm):.0f}% {'slower' if lm < 0 else 'quicker'} than par, "
                  "likely wind or ground, and that is allowed for)")
        if r["pooled"]:
            s += " (few races at this course/trip, par pooled)"
        return s

    lab["reason_sec"] = [reason(r) for _, r in lab.iterrows()]
    lab["course_norm"] = lab["course"].map(site_course_norm)
    lab["off_hhmm"] = lab["off_time"].map(hhmm)
    lab["dist_f"] = (lab["dist_y"] / FURLONG).round(2)
    cols = ["rtv_race_id", "race_id", "race_date", "course", "course_norm", "off_hhmm", "dist_f", "fam", "profile", "label",
            "fig_rel_sec", "pi", "e_dev", "l_dev", "e_dev_meet", "l_dev_meet", "race_adj", "win_fsp", "par_level", "par_n", "pooled", "n_full",
            "going", "reason_sec", "horses_sec"]
    return lab[cols].rename(columns={"race_date": "date", "fam": "code"})


def build_pace_rows(rp: pd.DataFrame, field_races: list[dict]) -> list[dict]:
    import pace_true_run as ptr
    by_fig = {str(r["race_id"]): r for r in rp.to_dict("records") if isinstance(r.get("race_id"), str) and r["race_id"]}
    used = set()
    out = []
    for f in field_races:
        s = by_fig.get(str(f.get("fig_race_id") or ""))
        if s is None:
            row = ptr.combine(None, f, {})
            if row["label"] != "unknown" or row["field_def"] is not None:
                out.append(row)
            continue
        used.add(s["rtv_race_id"])
        out.append(v12_row(s, f))
    for s in rp.to_dict("records"):
        if s["rtv_race_id"] not in used:
            out.append(v12_row(s, None))
    return out


def v12_row(s: dict, f: dict | None) -> dict:
    fd = (f or {}).get("field_def")
    field_fast = fd is not None and fd >= 10.0
    field_slow = fd is not None and fd <= -10.0
    prof = s["profile"]
    if s["fig_rel_sec"] == "low":
        rel = "low"
    elif field_fast or s["fig_rel_sec"] == "suspect":
        rel = "suspect"
    elif field_slow and prof not in ("True", "Fast-early"):
        rel = "low"
    else:
        rel = "ok"
    reason = s["reason_sec"]
    if fd is not None:
        reason += f"; field ran {abs(fd):.0f} {'below' if fd < 0 else 'above'} their usual"
    horses = []
    for h in list((f or {}).get("horses") or []) + str(s.get("horses_sec") or "").split(","):
        if h and h not in horses:
            horses.append(h)
    return {
        "date": str(s["date"])[:10],
        "course_norm": (f or {}).get("course_norm") or s["course_norm"],
        "course": (f or {}).get("course") or s["course"],
        "off_hhmm": s["off_hhmm"] or (f or {}).get("off_hhmm") or "",
        "dist_f": s["dist_f"] if pd.notna(s["dist_f"]) else (f or {}).get("dist_f"),
        "code": s["code"],
        "label": s["label"],
        "fig_rel": rel,
        "reason": reason,
        "source": "mixed" if fd is not None else "sectionals",
        "fsp": None if pd.isna(s["win_fsp"]) else round(float(s["win_fsp"]), 2),
        "field_def": fd,
        "n_field": (f or {}).get("n_field") or 0,
        "horses": ",".join(horses),
        "fig_race_id": (f or {}).get("fig_race_id"),
        "rtv_race_id": int(s["rtv_race_id"]),
    }


def sec_signature() -> dict:
    con = ro(SECT)
    n, mx = con.execute("SELECT COUNT(*), MAX(race_date) FROM rtv_races").fetchone()
    con.close()
    return {"present": 1, "n_races": int(n or 0), "max_date": str(mx or "")}


def write_site_pace(rp: pd.DataFrame, force: bool = True) -> dict:
    """Rebuild site_cache.pace = v12 sectional rows + v1 field-check rows for races without sectionals."""
    import pace_true_run as ptr
    if not CACHE.is_file():
        fail(f"Missing {CACHE}. Run the figure cache first.")
    t0 = time.time()
    rp_sig = str(round(RACE_PACE.stat().st_mtime)) if RACE_PACE.is_file() else ""
    con = ro(CACHE)
    meta = dict(con.execute("SELECT k, v FROM meta").fetchall()) if ptr.table_exists(con, "meta") else {}
    has_pace = ptr.table_exists(con, "pace")
    con.close()
    fig_sig_now = {"rows": meta.get("rows") or "", "max_date": meta.get("max_date") or "", "mtime": meta.get("mtime") or ""}
    if (not force and meta.get("pace_version") == "v12" and meta.get("pace_v12_src") == rp_sig
            and meta.get("pace_figs_rows") == str(fig_sig_now["rows"]) and meta.get("pace_figs_max") == str(fig_sig_now["max_date"])
            and meta.get("pace_figs_mtime") == str(fig_sig_now["mtime"])):
        log(f"Pace cache (v12) is already up to date ({meta.get('pace_rows')} rows).")
        return {"skipped": True}
    OUT.mkdir(parents=True, exist_ok=True)
    backup = OUT / "pace_v1_backup.csv.gz"
    if has_pace and meta.get("pace_version") != "v12" and not backup.is_file():
        c = ro(CACHE)
        pd.read_sql("SELECT * FROM pace", c).to_csv(backup, index=False)
        c.close()
        log(f"  Saved the previous (v1) pace table to {backup}")
    field_races, fig_sig = ptr.load_field()
    rows = build_pace_rows(rp, field_races)
    sig = sec_signature()
    sig["n_fsp"] = int(len(rp))
    ptr.write_cache(rows, fig_sig, sig, {}, t0)
    c = sqlite3.connect(str(CACHE), timeout=30)
    c.executemany("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                  [("pace_version", "v12"), ("pace_v12_src", rp_sig),
                   ("pace_v12_built", time.strftime("%Y-%m-%d %H:%M"))])
    c.commit()
    c.close()
    n_sec = sum(1 for r in rows if r["source"] in ("sectionals", "mixed") and r.get("rtv_race_id"))
    return {"rows": len(rows), "sectional_rows": n_sec,
            "labels": {k: sum(1 for r in rows if r["label"] == k) for k in ("true", "steady", "slow", "unknown")},
            "fig_rel": {k: sum(1 for r in rows if r["fig_rel"] == k) for k in ("ok", "low", "suspect")}}


def pace_only(force: bool = False) -> None:
    """Fast path used by pace_true_run.py: rebuild the site table from the cached v12 race pace file."""
    if not RACE_PACE.is_file():
        fail(f"No {RACE_PACE}. Run SECTIONALS_V12.bat once first.")
    rp = pd.read_csv(RACE_PACE, low_memory=False)
    rp["race_id"] = rp["race_id"].where(rp["race_id"].notna(), None)
    res = write_site_pace(rp, force=force)
    if not res.get("skipped"):
        log(f"PACE READY (v12): {res['rows']:,} races - sectionals {res['sectional_rows']:,} - labels {res['labels']}")


# --------------------------------------------------------------------- backtest
LAM = 4.0
GROUPS = {
    "rel_fixed": {"replace": ["last_adj_z", "wmean_adj_z", "last_low", "last_suspect"],
                  "cols": ["last_adj2_z", "wmean_adj2_z", "last_low2", "last_suspect2"],
                  "desc": "pace-reliability shrinkage of past figures, fed by v12 pace (fixes the horse-name key so it actually applies in training)"},
    "adj_figs": {"cols": ["v_last_adj_z", "v_best3_adj_z", "v_best3_adj_gap", "v_wmean_adj_z"],
                 "desc": "pace-adjusted figures (last, best of last 3, weighted mean)"},
    "fin_speed": {"cols": ["v_fsp_z", "v_has_sec"],
                  "desc": "average finishing speed vs section par over the last 5 sectional runs"},
    "unreliable": {"cols": ["v_unrel", "v_last_slow", "v_last_fast"],
                   "desc": "share of recent runs with unreliable figures, last run slow-run / fast-early"},
    "run_style": {"cols": ["v_style_z", "v_has_style", "v_lone", "v_style_front"],
                  "desc": "run style from sectional positions (habitual leader / held up) and likely pace rivals"},
}


def _num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def v12_hist_feats(hist: list[dict], today: dict, cut: str, pt) -> dict:
    fam = pt.is_jumps(today["code"])
    pool_all = [r for r in hist if r.get("fig") is not None]
    pool_fam = [r for r in pool_all if pt.is_jumps(r["code"]) == fam]
    pool = pool_fam or pool_all
    out = {}
    if not pool:
        return out
    recent = pool[-12:]

    def a(r):
        v = r.get("v")
        adj = v.get("adj_" + cut) if v else None
        return r["fig"] + (adj if adj is not None else 0.0)

    av = [a(r) for r in recent]
    out["v_last_adj"] = av[-1]
    top3 = sorted(av, reverse=True)[:3]
    out["v_best3_adj"] = sum(top3) / len(top3)
    tail = av[-8:]
    w = [0.7 ** (len(tail) - 1 - i) for i in range(len(tail))]
    out["v_wmean_adj"] = sum(x * y for x, y in zip(w, tail)) / sum(w)
    sec = [r["v"]["fsp_vp"] for r in recent if r.get("v") and r["v"].get("fsp_vp") is not None]
    out["v_fsp"] = (sum(sec[-5:]) / len(sec[-5:])) if sec else None
    out["v_has_sec"] = 1.0 if sec else 0.0
    last10 = recent[-10:]
    out["v_unrel"] = sum(1.0 for r in last10 if r.get("v") and r["v"].get("unrel_" + cut)) / len(last10)
    lv = recent[-1].get("v") or {}
    out["v_last_slow"] = 1.0 if lv.get("profile") == "Slow" else 0.0
    out["v_last_fast"] = 1.0 if lv.get("profile") == "Fast-early" else 0.0
    sty = [r["v"]["style"] for r in hist if r.get("v") and r["v"].get("style") is not None][-5:]
    out["v_style"] = (sum(sty) / len(sty)) if sty else None
    out["v_has_style"] = 1.0 if sty else 0.0
    return {f"{k}_{cut}": v for k, v in out.items()}


def build_bt_dataset(res: dict, cuts: dict) -> tuple[pd.DataFrame, str]:
    import predict_today as pt
    import win_pct as wp
    RJ = res["RJ"]
    X = res["X"]
    # adjustments / reliability fitted only on data before each cut-off
    info: dict[tuple, dict] = {}
    pmaps = {}
    for cut, before in cuts.items():
        tab = fit_adjust(RJ, RJ["race_date"] < before)
        adj = apply_adjust(RJ, tab)
        radj = race_adjust(X, tab)
        rel_low = X["rtv_race_id"][(X["profile"] == "Slow") | (radj >= 4.0)]
        low_set = set(rel_low.tolist())
        pm = {}
        for rid, hid, hn, d, a_, fvp, sty, prof in zip(RJ["race_id"], RJ["horse_id"], RJ["horse_norm"], RJ["race_date"],
                                                      adj, RJ["fsp_vs_par"], RJ["style_pct"], RJ["profile"]):
            if not isinstance(rid, str) or not isinstance(hid, str):
                continue
            rec = info.setdefault((rid, hid), {})
            rec["adj_" + cut] = _num(a_)
            rec["unrel_" + cut] = bool((_num(a_) is not None and abs(a_) >= FLAG_LB) or prof == "Slow")
            rec["fsp_vp"] = _num(fvp)
            rec["style"] = _num(sty)
            rec["profile"] = prof if isinstance(prof, str) else ""
        rr = RJ[RJ["race_id"].notna() & RJ["horse_norm"].notna()]
        lowmask = rr["rtv_race_id"].isin(low_set)
        for d, hn, lo in zip(rr["race_date"], rr["horse_norm"], lowmask):
            pm[(str(d)[:10], str(hn))] = "low" if lo else "ok"
        pmaps[cut] = pm
    log(f"  v12 run info for {len(info):,} figure runs")
    form_model = wp.load_form_model()
    df = pt.load_csv(pt.find_csv())
    df = df[df["horse_id"].notna()]
    pace_map_old = wp.load_pace_map()   # what the current model sees (its key never matches CSV names)
    t0 = time.time()
    recs = []
    cur, hist = None, []
    rows = df.to_dict("records")
    for i, r in enumerate(rows):
        if i and i % 100000 == 0:
            log(f"    ... {i:,}/{len(rows):,} runs ({time.time()-t0:.0f}s)")
        if r["horse_id"] != cur:
            cur, hist = r["horse_id"], []
        row = pt.row_from_csv(r)
        feat = pt.features_from_hist(hist, row, fig_key="fig")
        rec = {"race_id": row["race_id"], "date": str(row["date"])[:10], "horse_id": r["horse_id"],
               "horse_norm": row["horse_norm"], "horse": row["horse"], "course": row["course"],
               "off_time": row["off_time"], "place": row["place"], "code": row["code"], "has_form": 0.0,
               "last_adj": None, "wmean_adj": None, "best3_adj": None, "last_rel": ""}
        if feat is not None:
            rec.update(feat)
            rec["has_form"] = 1.0
            la, wm, b3, lr = wp.adj_from_hist(hist, row, pace_map_old, "fig")
            rec.update({"last_adj": la, "wmean_adj": wm, "best3_adj": b3, "last_rel": lr})
            for cut in cuts:
                la, wm, b3, lr = wp.adj_from_hist(hist, row, pmaps[cut], "fig")
                rec.update({f"last_adj2_{cut}": la, f"wmean_adj2_{cut}": wm, f"last_rel2_{cut}": lr})
                rec.update(v12_hist_feats(hist, row, cut, pt))
        recs.append(rec)
        row["v"] = info.get((row["race_id"], r["horse_id"]))
        hist.append(row)
    log(f"  history features for {len(recs):,} runs in {time.time()-t0:.0f}s")
    feat = pd.DataFrame.from_records(recs)
    feat["pred"] = wp.apply_pred(feat, form_model)
    feat = wp.add_race_features(feat)
    g = feat.groupby("race_id")

    def centred(src: str, zname: str, gname: str | None = None) -> None:
        s = pd.to_numeric(feat[src], errors="coerce") if src in feat.columns else pd.Series(np.nan, index=feat.index)
        fill = s.fillna(s.groupby(feat["race_id"]).transform("median")).fillna(0.0)
        feat[zname] = fill - fill.groupby(feat["race_id"]).transform("mean")
        if gname:
            feat[gname] = fill.groupby(feat["race_id"]).transform("max") - fill

    for cut in cuts:
        centred(f"last_adj2_{cut}", f"last_adj2_z_{cut}")
        centred(f"wmean_adj2_{cut}", f"wmean_adj2_z_{cut}")
        rel = feat.get(f"last_rel2_{cut}", pd.Series("", index=feat.index)).astype(str)
        feat[f"last_low2_{cut}"] = (rel == "low").astype(float)
        feat[f"last_suspect2_{cut}"] = (rel == "suspect").astype(float)
        centred(f"v_last_adj_{cut}", f"v_last_adj_z_{cut}")
        centred(f"v_best3_adj_{cut}", f"v_best3_adj_z_{cut}", f"v_best3_adj_gap_{cut}")
        centred(f"v_wmean_adj_{cut}", f"v_wmean_adj_z_{cut}")
        centred(f"v_fsp_{cut}", f"v_fsp_z_{cut}")
        centred(f"v_style_{cut}", f"v_style_z_{cut}")
        sty = pd.to_numeric(feat.get(f"v_style_{cut}"), errors="coerce")
        front = (sty <= 0.25).astype(float)
        n_front = front.groupby(feat["race_id"]).transform("sum")
        feat[f"v_style_front_{cut}"] = front * (n_front - front)          # rivals for the lead
        mn = sty.groupby(feat["race_id"]).transform("min")
        second = sty.groupby(feat["race_id"]).transform(lambda s: s.nsmallest(2).iloc[-1] if s.notna().sum() >= 2 else np.nan)
        feat[f"v_lone_{cut}"] = ((sty == mn) & (second - sty >= 0.15)).astype(float)
        for c in ("v_has_sec", "v_unrel", "v_last_slow", "v_last_fast", "v_has_style"):
            feat[f"{c}_{cut}"] = pd.to_numeric(feat.get(f"{c}_{cut}"), errors="coerce").fillna(0.0)
    # eligible races: 2+ runners and a recorded winner
    size = g["race_id"].transform("size")
    haswin = (feat["place"] == 1).groupby(feat["race_id"]).transform("any")
    feat = feat[(size >= 2) & haswin].sort_values(["race_id"], kind="mergesort").reset_index(drop=True)
    return feat, form_model


def _design(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
    return np.column_stack([pd.to_numeric(df[c], errors="coerce").fillna(0.0).to_numpy(float) if c in df.columns
                            else np.zeros(len(df)) for c in cols])


def _race_index(race: np.ndarray):
    starts = np.flatnonzero(np.r_[True, race[1:] != race[:-1]])
    ridx = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(race)]))
    return starts, ridx


def _probs(u, starts, ridx):
    mx = np.maximum.reduceat(u, starts)
    e = np.exp(np.clip(u - mx[ridx], -50, 50))
    z = np.add.reduceat(e, starts)
    return e / z[ridx]


def fit_clogit_newton(Z: np.ndarray, race: np.ndarray, y: np.ndarray, lam: float = LAM) -> np.ndarray:
    starts, ridx = _race_index(race)
    nw = np.add.reduceat(y, starts)[ridx]
    k = Z.shape[1]
    b = np.zeros(k)

    def loss(bb):
        p = _probs(Z @ bb, starts, ridx)
        return -np.log(np.clip(p[y > 0.5], 1e-15, 1)).sum() + 0.5 * lam * bb @ bb, p

    L, p = loss(b)
    for _ in range(50):
        g = Z.T @ (nw * p - y) + lam * b
        Zp = Z * (nw * p)[:, None]
        Sg = np.add.reduceat(Z * p[:, None], starts) * np.add.reduceat(y, starts)[:, None] ** 0.5
        H = Z.T @ Zp - Sg.T @ Sg + lam * np.eye(k)
        step = np.linalg.solve(H, g)
        t, ok = 1.0, False
        while t > 1e-4:
            Ln, pn = loss(b - t * step)
            if Ln <= L + 1e-9:
                ok = True
                break
            t /= 2
        if not ok:
            break
        b = b - t * step
        done = abs(L - Ln) < 1e-7 * max(1.0, abs(L))
        L, p = Ln, pn
        if done or np.max(np.abs(t * step)) < 1e-8:
            break
    return b


def fit_eval(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> dict:
    Xtr = _design(train, cols)
    mean, std = Xtr.mean(axis=0), Xtr.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    ytr = (train["place"] == 1).to_numpy(float)
    b = fit_clogit_newton((Xtr - mean) / std, train["race_id"].to_numpy(), ytr)
    Xte = (_design(test, cols) - mean) / std
    race = test["race_id"].to_numpy()
    starts, ridx = _race_index(race)
    p = _probs(Xte @ b, starts, ridx)
    y = (test["place"] == 1).to_numpy()
    nll_run = np.where(y, -np.log(np.clip(p, 1e-15, 1)), 0.0)
    race_nll = np.add.reduceat(nll_run, starts) / np.maximum(np.add.reduceat(y.astype(float), starts), 1)
    return {"p": p, "race_nll": race_nll, "coef": dict(zip(cols, [float(x) for x in b])), "mean": mean, "std": std}


def top_pick(test: pd.DataFrame, p: np.ndarray) -> float:
    t = test[["race_id", "place"]].copy()
    t["p"] = p
    mx = t.groupby("race_id")["p"].transform("max")
    hit = t[t["p"] >= mx - 1e-12].groupby("race_id")["place"].apply(lambda s: (s == 1).any())
    return float(hit.mean())


def cols_for(base: list[str], groups: list[str], cut: str) -> list[str]:
    cols = list(base)
    for gname in groups:
        gdef = GROUPS[gname]
        for rc in gdef.get("replace", []):
            if rc in cols:
                cols.remove(rc)
        cols += [f"{c}_{cut}" for c in gdef["cols"]]
    return cols


def paired(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    d = a - b            # positive = b better (lower loss)
    return float(d.mean()), float(d.std(ddof=1) / math.sqrt(len(d)))


def backtest(res: dict) -> dict:
    import predict_today as pt
    import win_pct as wp
    base_cols = list(wp.FEATURES)
    src = pt.MODEL_PATH if pt.MODEL_PATH.is_file() else pt.BUNDLE_PATH
    test_start = None
    try:
        test_start = json.loads(src.read_text(encoding="utf-8")).get("test_start")
    except Exception:
        pass
    df_dates = res["F"]["date"]
    if not test_start:
        test_start = str(pd.Timestamp(df_dates.max()) - pd.DateOffset(years=1))[:10]
    val_start = str(pd.Timestamp(test_start) - pd.DateOffset(years=1))[:10]
    log(f"Step 5/5  Backtest: train < {val_start}, validation {val_start} to {test_start}, held-out test from {test_start}")
    feat, _ = build_bt_dataset(res, {"s": val_start, "t": test_start})
    tr1 = feat[feat["date"] < val_start]
    va = feat[(feat["date"] >= val_start) & (feat["date"] < test_start)]
    log(f"  selection: {tr1['race_id'].nunique():,} train races, {va['race_id'].nunique():,} validation races")
    sel = {}
    base_v = fit_eval(tr1, va, base_cols)
    sel["baseline"] = {"val_nll": float(base_v["race_nll"].mean()), "val_top": top_pick(va, base_v["p"])}
    single = {}
    for gname in GROUPS:
        r = fit_eval(tr1, va, cols_for(base_cols, [gname], "s"))
        m, se = paired(base_v["race_nll"], r["race_nll"])
        single[gname] = {"val_gain": m, "val_se": se, "val_top": top_pick(va, r["p"])}
        log(f"    {gname:<11} validation log-loss gain {m:+.4f} (se {se:.4f}), top pick {single[gname]['val_top']:.2%} vs {sel['baseline']['val_top']:.2%}")
    adopted: list[str] = []
    cur = base_v
    for gname in sorted(GROUPS, key=lambda k: -single[k]["val_gain"]):
        if single[gname]["val_gain"] <= 0:
            continue
        r = fit_eval(tr1, va, cols_for(base_cols, adopted + [gname], "s"))
        m, se = paired(cur["race_nll"], r["race_nll"])
        keep = m > max(2.0 * se, 0.0005)
        log(f"    add {gname:<11} on top of {adopted or ['baseline']}: gain {m:+.4f} (se {se:.4f}) -> {'ADOPT' if keep else 'drop'}")
        single[gname]["stepwise_gain"], single[gname]["stepwise_se"], single[gname]["adopted"] = m, se, bool(keep)
        if keep:
            adopted.append(gname)
            cur = r
    # held-out test year: refit on everything before test_start
    tr2 = feat[feat["date"] < test_start]
    te = feat[feat["date"] >= test_start].copy()
    log(f"  test: {tr2['race_id'].nunique():,} train races, {te['race_id'].nunique():,} held-out races")
    b = fit_eval(tr2, te, base_cols)
    out = {"test_start": test_start, "val_start": val_start, "adopted": adopted, "selection": sel, "groups": single,
           "n_train_races": int(tr2["race_id"].nunique()), "n_test_races": int(te["race_id"].nunique()),
           "n_val_races": int(va["race_id"].nunique())}
    models = {"baseline": b}
    if adopted:
        models["v12"] = fit_eval(tr2, te, cols_for(base_cols, adopted, "t"))
    for gname in GROUPS:
        r = fit_eval(tr2, te, cols_for(base_cols, [gname], "t"))
        m, se = paired(b["race_nll"], r["race_nll"])
        single[gname]["test_gain_alone"], single[gname]["test_se_alone"] = m, se
    prices = wp.load_eval_prices()
    # win_pct.attach_prices keys on the CSV's horse_norm, which keeps spaces ("a bear affair") while the
    # price file is keyed without them, so only one-word names matched (~29% of runners). Use the
    # no-space key on both sides here.
    te_p = wp.attach_prices(te.assign(horse_norm=te["horse"].map(horse_key)), prices)
    has_sec = (te["v_has_sec_t"] > 0).groupby(te["race_id"]).transform("mean") >= 0.5
    starts, _ = _race_index(te["race_id"].to_numpy())
    race_has_sec = has_sec.to_numpy()[starts]
    ev = {}
    for name, mdl in models.items():
        t = te_p.copy()
        t["p"] = mdl["p"]
        ev[name] = {
            "nll": float(mdl["race_nll"].mean()),
            "nll_sec_races": float(mdl["race_nll"][race_has_sec].mean()) if race_has_sec.any() else None,
            "top": top_pick(te, mdl["p"]),
            "calibration": wp.calibration(t),
            "value": wp.value_report(t, "bsp"),
            "coef": mdl["coef"],
        }
    for name, mdl in models.items():
        t = te_p[["race_id", "place", "bsp"]].copy()
        t["p"] = mdl["p"]
        hits = n = 0
        agree = 0
        for rid, g in t.groupby("race_id", sort=False):
            gg = g.dropna(subset=["bsp"])
            if len(gg) < 2 or len(gg) < len(g):
                continue
            n += 1
            fav = gg["bsp"].idxmin()
            top = g["p"].idxmax()
            hits += int(g.loc[fav, "place"] == 1)
            agree += int(fav == top)
        ev[name]["fav_rate"] = hits / n if n else None
        ev[name]["fav_n"] = n
        ev[name]["top_is_fav"] = agree / n if n else None
    if "v12" in models:
        m, se = paired(b["race_nll"], models["v12"]["race_nll"])
        ev["v12_vs_baseline"] = {"gain": m, "se": se}
    # market reference: normalised 1/BSP
    bsp = pd.to_numeric(te_p["bsp"], errors="coerce")
    cover = bsp.notna().groupby(te_p["race_id"]).transform("all")
    if cover.any():
        q = (1.0 / bsp).where(cover)
        q = q / q.groupby(te_p["race_id"]).transform("sum")
        y = te_p["place"] == 1
        mk = te_p[cover & y]
        ev["market_nll_priced_races"] = float(-np.log(np.clip(q[cover & y], 1e-15, 1)).groupby(mk["race_id"]).mean().mean())
        rowmask = (cover & y).to_numpy()
        rid = te_p["race_id"].to_numpy()[rowmask]
        ev["model_nll_priced_races"] = {}
        for n, mdl in models.items():
            v = -np.log(np.clip(mdl["p"][rowmask], 1e-15, 1))
            ev["model_nll_priced_races"][n] = float(pd.Series(v).groupby(rid).mean().mean())
        ev["bsp_cov"] = float(bsp.notna().mean())
    out["eval"] = ev
    log(f"  held-out log-loss/race: baseline {ev['baseline']['nll']:.4f}" +
        (f", v12 {ev['v12']['nll']:.4f}" if "v12" in ev else " (no v12 groups adopted)"))
    return out


# ---------------------------------------------------------------------- outputs
def horse_features(res: dict) -> pd.DataFrame:
    """Latest sectional history per horse (for the site / research), from all figure runs."""
    F = res["F"][["race_id", "date", "horse_id", "horse", "hk", "weighted_fig"]].copy()
    RJ = res["RJ"][["race_id", "hk", "adj", "fsp_vs_par", "fin_speed_pct", "style_pct", "unreliable", "profile"]]
    d = F.merge(RJ.drop_duplicates(["race_id", "hk"]), on=["race_id", "hk"], how="left")
    d["fig"] = pd.to_numeric(d["weighted_fig"], errors="coerce")
    d["fig_adj"] = d["fig"] + d["adj"].fillna(0.0)
    d = d[d["horse_id"].notna()].sort_values(["horse_id", "date"], kind="mergesort")
    g = d.groupby("horse_id", sort=False)
    out = g.agg(horse=("horse", "last"), last_run=("date", "last"), runs=("date", "size"),
                sectional_runs=("fsp_vs_par", "count"))
    t12 = g.tail(12).groupby("horse_id").agg(best_adj_fig_last12=("fig_adj", "max"), best_raw_fig_last12=("fig", "max"))
    t10 = g.tail(10).groupby("horse_id")["unreliable"].apply(lambda x: int(x.fillna(0).sum())).rename("unreliable_runs_last10")
    sd = d[d["fsp_vs_par"].notna()]
    sec = sd.groupby("horse_id").tail(5).groupby("horse_id").agg(avg_fin_speed_pct_last5=("fin_speed_pct", "mean"),
                                                                  avg_fin_vs_par_last5=("fsp_vs_par", "mean"))
    sty = d[d["style_pct"].notna()].groupby("horse_id").tail(5).groupby("horse_id")["style_pct"].mean().rename("avg_run_style_last5")
    out = out.join(t12).join(t10).join(sec).join(sty).reset_index()
    return out.round(2)


def write_outputs(res: dict, rp: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rp.to_csv(RACE_PACE, index=False)
    RJ = res["RJ"]
    cols = ["race_date", "course", "off_time", "race_id", "rtv_race_id", "horse_name", "horse_id", "finish_position", "fig",
            "fin_speed_pct", "finishing_speed_pct", "fsp_vs_par", "style_pct", "early_pct", "profile", "pi", "adj", "fig_adj",
            "fig_flag", "unreliable", "sane", "nsec", "sect_fig", "sect_fig_weighted", "sect_fig_official"]
    cols = [c for c in cols if c in RJ.columns]
    RJ[cols].rename(columns={"race_date": "date", "finishing_speed_pct": "rtv_fsp", "profile": "race_pace"}).to_csv(RUNNERS_OUT, index=False, float_format="%.3f")
    res["SP"].to_csv(PARS_OUT, index=False, float_format="%.4f")
    if res.get("SF") is not None and len(res["SF"]):
        res["SF"].to_csv(SECT_FIGS_OUT, index=False, float_format="%.4f")
        log(f"  section figures: {len(res['SF']):,} rows -> {SECT_FIGS_OUT.name}")
    res["par_tables"].to_csv(SHAPE_PARS_OUT, index=False, float_format="%.5f")
    res["adj_table"].to_csv(ADJ_OUT, index=False)
    t0 = time.time()
    hf = horse_features(res)
    hf.to_csv(HORSE_OUT, index=False)
    log(f"  horse history features: {len(hf):,} horses ({time.time()-t0:.0f}s)")
    SETTINGS_OUT.write_text(json.dumps({"thresholds": res["settings"], "going_slopes": res["slopes"],
                                        "going": res.get("going"), "min_par_n": MIN_PAR_N, "late_furlongs": LATE_F}, indent=2), encoding="utf-8")
    j, rj = res["join"], res["runner_join"]
    lines = [
        "Sectionals -> speed_v4 join",
        f"  sectional races in the figures' date range: {j['sect_races_in_fig_range']:,}",
        f"  matched to a figure race: {j['sect_races_matched']:,} ({j['sect_match_rate']:.2%})",
        f"  of races whose meeting is in the figures: {j['sect_match_rate_meeting_in_figs']:.2%}",
        f"  how: {j['by_how']}   by country: { {k: round(v, 4) for k, v in j['by_country'].items()} }",
        f"  runner match (all runners incl. non-runners): {rj['runner_match_rate']:.2%}",
        f"  finishers matched: {rj['finisher_match_rate']:.3%}; finishing positions agree: {rj['position_agreement']:.2%}",
        f"  examples still unmatched: {j['unmatched_examples']}",
    ]
    JOIN_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pct(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{100*x:.{d}f}%"


def write_summary(res: dict, rp: pd.DataFrame, site: dict | None, bt: dict | None, secs: float, path: Path = SUMMARY_OUT) -> str:
    X, j, rj, mi = res["X"], res["join"], res["runner_join"], res["minfo"]
    a = []
    A = a.append
    A("FurlongIQ - Sectionals v12 summary")
    A("=" * 72)
    A(f"Built {time.strftime('%Y-%m-%d %H:%M')} in {secs/60:.1f} minutes.")
    A("")
    A("Coverage")
    A("-" * 72)
    yr = X.groupby(X["race_date"].str[:4]).agg(races=("rtv_race_id", "size"), labelled=("profile", lambda s: (s != "").sum()))
    A(f"  Racing TV races: {len(X):,}; with a pace label: {(X['profile'] != '').sum():,}")
    for y, r in yr.iterrows():
        A(f"    {y}: {r['races']:,} races, {r['labelled']:,} labelled")
    A(f"  Runners with clean section times: {mi['runners_sane']:,} of {mi['runners_with_sections']:,}")
    A(f"  Our finishing speed % vs Racing TV's own figure: correlation {mi.get('fsp_corr_vs_rtv', float('nan')):.3f}")
    A("")
    A("Join to the speed figures")
    A("-" * 72)
    A(f"  {pct(j['sect_match_rate_meeting_in_figs'], 2)} of sectional races matched a figure race "
      f"({j['sect_races_matched']:,} races); finishers matched {pct(rj['finisher_match_rate'], 3)}.")
    A(f"  Finishing positions agree on {pct(rj['position_agreement'], 2)} of matched runners.")
    A("")
    A("How pace is judged")
    A("-" * 72)
    A("  For every course + code/surface + trip we build par times for each furlong from sound races")
    A("  (winner with full, clean sections, 4+ runners timed), with a going adjustment. Sparse combos")
    A(f"  (under {MIN_PAR_N} sound races) borrow the course's trip band, then all courses at that trip (flagged).")
    A("  Early pace = speed the leader set up to the last 2f (Flat) / 3f (jumps), vs par.")
    A("  Late pace  = finishing speed of the first three over that last 2f/3f, vs par.")
    A("  Pace index = early vs par minus late vs par, after removing any meeting-wide shift")
    A("  (wind / ground the going figure misses). Labels per turf Flat, all-weather and jumps:")
    for g, s in res["settings"].items():
        A(f"    {GRP_NAME[g]}: Slow <= {s['p10']:+.1f}, Steady <= {s['p30']:+.1f}, Fast-early >= {s['p90']:+.1f}, else True")
    lv = X.loc[X["profile"] != "", "par_level"].value_counts()
    A(f"  Par used: own course+trip {lv.get('course_trip', 0):,}, course trip-band {lv.get('course_band', 0):,}, "
      f"pooled {int(lv.drop(['course_trip', 'course_band'], errors='ignore').sum()):,} races")
    vc = rp["profile"].value_counts()
    A(f"  Labels: True {vc.get('True', 0):,} | Steady {vc.get('Steady', 0):,} | Slow {vc.get('Slow', 0):,} | Fast-early {vc.get('Fast-early', 0):,}")
    A("")
    A("What it means for figures (figure vs the horse's usual level, by pace)")
    A("-" * 72)
    tab = res["adj_table"]
    for g in ("F", "A", "J"):
        t = tab[(tab["grp"] == g) & (tab["sty"] == "all")].sort_values("pi_bin")
        if len(t):
            A(f"  {GRP_NAME[g]} adjustment by pace decile (0 = slowest early):  " +
              "  ".join(f"{int(r.pi_bin)}:{r.adj:+.1f}" for r in t.itertuples()))
    A("  Positive = figure likely understated (slow-run sprint finish) -> adjusted up.")
    A("  Negative = figure may flatter the horse (strongly run race) -> adjusted down a little.")
    fl = res["RJ"]["fig_flag"].value_counts()
    A(f"  Runs flagged understated: {fl.get('understated', 0):,}; overstated: {fl.get('overstated', 0):,}")
    A("")
    if site:
        A("Website pace table (data\\site_cache.sqlite -> pace)")
        A("-" * 72)
        if site.get("skipped"):
            A("  Already up to date.")
        elif site.get("not_written"):
            A("  Not written (test run).")
        else:
            A(f"  {site['rows']:,} races ({site['sectional_rows']:,} from sectionals). Labels {site['labels']}; reliability {site['fig_rel']}")
            A("  Run UPLOAD_TO_SUPABASE.bat (or UPDATE_TODAY.bat) to send it to the live site.")
        A("")
    if bt:
        ev = bt["eval"]
        A("Backtest - win % model (conditional logit), held-out year")
        A("-" * 72)
        A(f"  Train before {bt['val_start']} -> choose features on {bt['val_start']} to {bt['test_start']} ({bt['n_val_races']:,} races)")
        A(f"  -> refit before {bt['test_start']} and test on {bt['n_test_races']:,} later races (never used to choose).")
        A("")
        A(f"  {'Feature group':<12}{'val gain':>10}{'(se)':>9}{'adopted':>9}{'test gain alone':>17}")
        for gname, g in bt["groups"].items():
            A(f"  {gname:<12}{g['val_gain']:>+10.4f}{g['val_se']:>9.4f}{('yes' if g.get('adopted') else 'no'):>9}{g.get('test_gain_alone', float('nan')):>+17.4f}")
        A("  (gain = drop in log-loss per race; positive is better)")
        A("")
        b = ev["baseline"]
        A(f"  Current model: log-loss {b['nll']:.4f}, top pick wins {pct(b['top'])}")
        if "v12" in ev:
            v = ev["v12"]
            g = ev["v12_vs_baseline"]
            A(f"  v12 model:     log-loss {v['nll']:.4f}, top pick wins {pct(v['top'])}  (gain {g['gain']:+.4f}, se {g['se']:.4f})")
            if b.get("nll_sec_races") and v.get("nll_sec_races"):
                A(f"  Races where most runners have sectional history: {b['nll_sec_races']:.4f} -> {v['nll_sec_races']:.4f}")
        else:
            A("  No sectional feature group beat the current model on the validation year, so none adopted.")
        if ev["baseline"].get("fav_n"):
            A(f"  Betfair SP favourite won {pct(ev['baseline']['fav_rate'])} of {ev['baseline']['fav_n']:,} fully priced test races "
              f"(BSP matched on {pct(ev.get('bsp_cov'), 0)} of test runners).")
        if ev.get("market_nll_priced_races"):
            A(f"  For scale, Betfair SP's log-loss on the same fully priced races: {ev['market_nll_priced_races']:.4f} "
              f"(models: " + ", ".join(f"{k} {v:.4f}" for k, v in ev["model_nll_priced_races"].items()) + ")")
        A("")
        A("  Calibration (test)            current            v12")
        cal_b = {r["band"]: r for r in b["calibration"]}
        cal_v = {r["band"]: r for r in ev.get("v12", b)["calibration"]}
        for band in cal_b:
            rb, rv = cal_b[band], cal_v.get(band, {})
            fb = f"{pct(rb['pred'])}->{pct(rb['actual'])} ({rb['n']:,})" if rb["n"] else "-"
            fv = f"{pct(rv.get('pred'))}->{pct(rv.get('actual'))} ({rv.get('n', 0):,})" if rv.get("n") else "-"
            A(f"    {band:<8} {fb:>26} {fv:>26}")
        A("")
        A("  Value test: back when BSP is longer than fair odds (ROI after 2% / 5% commission)")
        for name in [k for k in ("baseline", "v12") if k in ev]:
            for r in ev[name]["value"]:
                A(f"    {name:<9} edge {r['edge']:.1f}x: {r['n']:>6,} bets, {r['wins']:>5,} wins, "
                  f"ROI {pct(r['by_comm']['2%']['roi'])} / {pct(r['by_comm']['5%']['roi'])}")
        A("")
        A(f"  Adopted feature groups: {', '.join(bt['adopted']) or 'none'} (details in adopted_features.json)")
        A("")
    sfr = res.get("SFr")
    if sfr is not None and len(sfr):
        nfig = int(sfr["sect_fig"].notna().sum()) if "sect_fig" in sfr.columns else 0
        A("")
        A("Sectional speed figures (exact-distance pars, v4 going)")
        A("-" * 72)
        A(f"  Full-race sectional figures on {nfig:,} runners. Extra rail-move yards sit in the first section and are scaled pro-rata.")
        A("  Winning times follow v4 (RBD if all three agree; Racing TV/sectionals if those two agree and RBD differs).")
    A("Files in data\\sectionals_v12")
    A("-" * 72)
    A("  race_pace.csv.gz              pace profile, early/late vs par, adjustment per race")
    A("  runner_sectionals.csv.gz      every runner: finishing speed %, vs par, run style, adjusted figure, flags")
    A("  section_pars.csv              par time for each section, per course + code/surface + trip (exact yards; first section holds rail-move yards)")
    A("  section_figures.csv.gz        section-by-section figures and the inputs for full-race sectional figures")
    A("  shape_pars.csv                early/late par ratios used (with sample sizes, pooled levels)")
    A("  figure_adjustments.csv        lb adjustment by pace decile x run style")
    A("  horse_sectional_features.csv.gz  latest per-horse history (avg finishing speed, best adjusted fig, unreliable runs)")
    A("  join_report.txt, backtest.json, adopted_features.json, settings.json")
    text = "\n".join(a) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="FurlongIQ sectionals v12")
    ap.add_argument("--figs", default=None, help="Path to speed figures csv (default data/speed_v4/speed_figures.csv)")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--no-backtest", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="Do not touch site_cache.sqlite (test runs).")
    ap.add_argument("--pace-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    global FIGCSV, V4CORR
    if args.figs:
        FIGCSV = Path(args.figs)
        if not FIGCSV.is_absolute():
            FIGCSV = ROOT / FIGCSV
        sibling = FIGCSV.parent / "distance_corrections.csv"
        if sibling.is_file():
            V4CORR = sibling
    if args.pace_only:
        pace_only(force=args.force)
        return
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    sliced = bool(args.start or args.end)
    res = compute(args.start, args.end)
    rp = race_pace_table(res["X"], res["RJ"])
    if not sliced:
        write_outputs(res, rp)
    else:
        out = OUT / "_slice"
        out.mkdir(exist_ok=True)
        rp.to_csv(out / "race_pace_slice.csv", index=False)
        res["RJ"].to_csv(out / "runners_slice.csv.gz", index=False)
    site = None
    if args.no_write or sliced:
        site = {"not_written": True}
    else:
        log("Writing the website pace table...")
        site = write_site_pace(rp, force=True)
    bt = None
    if not args.no_backtest:
        bt = backtest(res)
        clean = json.loads(json.dumps(bt, default=lambda o: None))
        if not sliced:
            BACKTEST_OUT.write_text(json.dumps(clean, indent=2), encoding="utf-8")
            ADOPT_OUT.write_text(json.dumps({
                "built": time.strftime("%Y-%m-%d %H:%M"), "adopted": bt["adopted"],
                "groups": {k: {"desc": GROUPS[k]["desc"], "columns": GROUPS[k]["cols"], **{kk: vv for kk, vv in clean["groups"][k].items()}}
                           for k in GROUPS},
                "note": "Adopted = improved validation-year log-loss by more than 2 standard errors. "
                        "win_pct.py is not changed by this script; these are the features to add when it is retrained.",
            }, indent=2), encoding="utf-8")
    text = write_summary(res, rp, site, bt, time.time() - t0,
                         (OUT / "_slice" / "summary_slice.txt") if sliced else SUMMARY_OUT)
    log("")
    log(text)


if __name__ == "__main__":
    main()
