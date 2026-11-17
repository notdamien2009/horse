"""FurlongIQ speed figures v4 = v3 method + fixed data from Racing TV.

  * Exact race distance (yards) from Racing TV. RBD's rounded trip is used only when
    there is no RTV distance (flagged NO_RTV). Conflicts of more than 120y are also
    flagged (RTV_CONFLICT) and fall back to RBD, as those are almost certainly bad
    joins rather than rail moves. Rail-moved races stay in the same course / code /
    surface / trip standard (std_key). The standard time is computed at the median
    RTV yards for that key; each race is scored against an expected time at its own
    exact yards (pro-rata at that course's own seconds per yard). Recorded winning
    times are not altered.
  * Winning times, three-way: RBD is used when RBD, Racing TV results and the
    sectionals time all agree. If RBD differs but Racing TV results and sectionals
    agree with each other, their time is used. If all three disagree the race is
    flagged and the time nearer class par is kept. Racing TV results
    (racing_history.sqlite) are read live, read-only, with no hard-coded end date.
  * pace-adjusted figure column (pace_adj_fig) from data/sectionals_v12/runner_sectionals.csv.gz
    when present (BUILD_MASTER rebuilds those sectionals after this script).
Writes data/speed_v4/ (same files as speed_v3 + distance_corrections.csv + summary.txt).
speed_v3 is untouched.
"""
import argparse, sqlite3, sys, tempfile, time
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
import speedfig_v3 as v3
import sectionals_v12 as s12

ROOT = v3.default_root(); DATA = ROOT / "data"
MAX_DY, TIME_TOL, SWITCH_LB = 120.0, 1.0, 5.0
ST = {"k": 1.0, "start": None, "end": None, "races": None, "rep": {}, "k_hat": None, "rtv_results_span": None}
_orig_prepare = v3.prepare
_orig_run = v3.run
_orig_run_2yo = v3.run_2yo


def refresh(r):
    spf = r["win_time"] / r["dist_f"]
    lo = r["code"].map(lambda c: v3.PLAUSIBLE_SPF[c][0]); hi = r["code"].map(lambda c: v3.PLAUSIBLE_SPF[c][1])
    nt = r["race_skip"].isin(["NO_WINNING_TIME", "IMPLAUSIBLE_TIME", "NO_WINNER", ""])
    reason = r["race_skip"].copy(); reason[nt] = ""
    reason[nt & r["win_time"].isna()] = "NO_WINNING_TIME"
    reason[nt & (reason == "") & r["win_wt"].isna()] = "NO_WINNER"
    reason[nt & (reason == "") & ((spf < lo) | (spf > hi))] = "IMPLAUSIBLE_TIME"
    r["race_skip"] = reason
    r["sec_per_length"] = v3.LENGTH_M / (r["dist_m"] / r["win_time"])
    r["lbs_per_sec"] = r["lbs_per_length"] / r["sec_per_length"]


def snapshot_sqlite(path: Path):
    """Consistent read of a SQLite file that may have a writer (WAL).

    Prefer the backup API into a temp file; fall back to an immutable read-only
    open so we never take a write lock on the live database.
    Returns (uri, tmp_path_or_None).
    """
    path = Path(path)
    posix = path.as_posix()
    tmpdir = Path(tempfile.mkdtemp(prefix="fiq_rh_"))
    tmp = tmpdir / path.name
    try:
        src = sqlite3.connect("file:%s?mode=ro" % posix, uri=True, timeout=30)
        try:
            src.execute("PRAGMA query_only=ON")
            dst = sqlite3.connect(str(tmp))
            src.backup(dst)
            dst.close()
        finally:
            src.close()
        return "file:%s?mode=ro" % tmp.as_posix(), tmp
    except Exception as ex:
        try:
            if tmp.exists():
                tmp.unlink()
            tmpdir.rmdir()
        except Exception:
            pass
        v3.log("v4: racing_history backup failed (%s); opening immutable read-only" % ex)
        return "file:%s?mode=ro&immutable=1" % posix, None


def cleanup_snap(tmp):
    if tmp is None:
        return
    try:
        tmp.unlink(missing_ok=True)
        for extra in (str(tmp) + "-wal", str(tmp) + "-shm"):
            p = Path(extra)
            if p.exists():
                p.unlink()
        tmp.parent.rmdir()
    except Exception:
        pass


def load_rtv_results_times(start=None, end=None) -> pd.Series:
    """winning_time_seconds from Racing TV results, keyed by rtv_race_id.

    Reads whatever is currently in racing_history.sqlite (no end-date cap).
    """
    src = DATA / "racing_history.sqlite"
    if not src.is_file():
        v3.log("v4: racing_history.sqlite not found; RTV results times unavailable")
        return pd.Series(dtype=float)
    uri, tmp = snapshot_sqlite(src)
    try:
        con = sqlite3.connect(uri, uri=True)
        q = ("select race_id, race_date, "
             "json_extract(data, '$.rtv_race_id') as rtv_race_id, "
             "json_extract(data, '$.winning_time_seconds') as winning_time_seconds "
             "from races where source='rtv'")
        params = []
        if start:
            q += " and race_date >= ?"; params.append(start)
        if end:
            q += " and race_date <= ?"; params.append(end)
        df = pd.read_sql(q, con, params=params)
        con.close()
    finally:
        cleanup_snap(tmp)
    rid = pd.to_numeric(df["rtv_race_id"], errors="coerce")
    from_key = pd.to_numeric(df["race_id"].astype(str).str.replace(r"^rtv:", "", regex=True), errors="coerce")
    df["rid"] = rid.fillna(from_key)
    df["t"] = pd.to_numeric(df["winning_time_seconds"], errors="coerce")
    span = None
    if len(df):
        span = (str(df["race_date"].min()), str(df["race_date"].max()))
        ST["rtv_results_span"] = span
    df = df[df["rid"].notna() & df["t"].notna() & (df["t"] > 0)]
    s = df.drop_duplicates("rid").set_index("rid")["t"]
    s.index = s.index.astype(int)
    if span:
        v3.log("v4: Racing TV results times: {:,} races, {} to {} (live read, no end cap)".format(len(s), span[0], span[1]))
    else:
        v3.log("v4: Racing TV results times: 0 races")
    return s


def rtv_table(rn, races):
    con = sqlite3.connect("file:%s?mode=ro" % (DATA / "sectionals.sqlite").as_posix(), uri=True)
    R = pd.read_sql("select rtv_race_id, race_date, course, country, off_time, distance_yards, winner_time_s, has_sectionals from rtv_races", con)
    U = pd.read_sql("select rtv_race_id, horse_name, finish_position, total_time_s from rtv_runners", con)
    con.close()
    if ST["start"]:
        R = R[R["race_date"] >= ST["start"]]
    if ST["end"]:
        R = R[R["race_date"] <= ST["end"]]
    U = U[U["rtv_race_id"].isin(R["rtv_race_id"])]
    R = R.copy()
    R["ck"] = R["course"].map(s12.join_key)
    cmap = {c: s12.join_key(c) for c in rn["course_raw"].unique()}
    tmap = {t: s12.hhmm(t) for t in rn["off_time"].unique()}
    F = pd.DataFrame({"race_id": rn["race_id"], "date": rn["date"].dt.strftime("%Y-%m-%d"), "ck": rn["course_raw"].map(cmap),
                      "hh": rn["off_time"].map(tmap), "hk": rn["horse"].map(s12.horse_key), "horse": rn["horse"],
                      "place": rn["place"], "code": rn["race_id"].map(races["code"]), "dist_f": rn["race_id"].map(races["dist_f"])})
    F["is_j"] = F["code"] != "Flat"
    jr, rep = s12.join_races(R, U, F)
    j = jr[["rtv_race_id", "race_id"]].dropna().merge(R[["rtv_race_id", "distance_yards", "winner_time_s"]], on="rtv_race_id")
    w = U[pd.to_numeric(U["finish_position"], errors="coerce") == 1][["rtv_race_id", "total_time_s"]].dropna()
    w = w.drop_duplicates("rtv_race_id")
    j = j.merge(w, on="rtv_race_id", how="left")
    j["sect_time"] = j["winner_time_s"].where(j["winner_time_s"].notna(), j["total_time_s"])
    return j.drop_duplicates("race_id").set_index("race_id"), rep


def _agree(a, b, tol=TIME_TOL):
    return a.notna() & b.notna() & ((a - b).abs() <= tol)


def resolve_times(r):
    """Three-way winning time: RBD, Racing TV results, sectionals."""
    rbd = r["win_time_official"]
    rtv = r["rtv_results_time"]
    sec = r["sect_time"]
    src = pd.Series("RBD", index=r.index, dtype=object)
    used = rbd.copy()
    flag = pd.Series("", index=r.index, dtype=object)

    have_rbd, have_rtv, have_sec = rbd.notna(), rtv.notna(), sec.notna()
    n3 = have_rbd & have_rtv & have_sec
    a_rbd_rtv, a_rbd_sec, a_rtv_sec = _agree(rbd, rtv), _agree(rbd, sec), _agree(rtv, sec)

    all3 = n3 & a_rbd_rtv & a_rbd_sec
    src[all3] = "RBD_ALL_AGREE"
    used[all3] = rbd[all3]

    rtv_sec_vs_rbd = n3 & a_rtv_sec & ~a_rbd_rtv & ~a_rbd_sec
    src[rtv_sec_vs_rbd] = "RTV_SEC_AGREE"
    used[rtv_sec_vs_rbd] = rtv[rtv_sec_vs_rbd]

    triple_dis = n3 & ~a_rbd_rtv & ~a_rbd_sec & ~a_rtv_sec
    src[triple_dis] = "TRIPLE_DISAGREE"
    used[triple_dis] = rbd[triple_dis]
    flag[triple_dis] = "TIME_TRIPLE_DISAGREE"

    rbd_ok_partial = n3 & ~all3 & ~rtv_sec_vs_rbd & ~triple_dis & (a_rbd_rtv | a_rbd_sec)
    src[rbd_ok_partial] = "RBD_PAIR_AGREE"
    used[rbd_ok_partial] = rbd[rbd_ok_partial]

    only_rbd_rtv = have_rbd & have_rtv & ~have_sec
    src[only_rbd_rtv & a_rbd_rtv] = "RBD_RTV_AGREE"
    used[only_rbd_rtv & a_rbd_rtv] = rbd[only_rbd_rtv & a_rbd_rtv]
    src[only_rbd_rtv & ~a_rbd_rtv] = "RBD_RTV_DISAGREE"
    used[only_rbd_rtv & ~a_rbd_rtv] = rbd[only_rbd_rtv & ~a_rbd_rtv]
    flag[only_rbd_rtv & ~a_rbd_rtv] = "TIME_RBD_RTV_DISAGREE"

    only_rbd_sec = have_rbd & have_sec & ~have_rtv
    src[only_rbd_sec & a_rbd_sec] = "RBD_SEC_AGREE"
    used[only_rbd_sec & a_rbd_sec] = rbd[only_rbd_sec & a_rbd_sec]
    src[only_rbd_sec & ~a_rbd_sec] = "RBD_SEC_DISAGREE"
    used[only_rbd_sec & ~a_rbd_sec] = rbd[only_rbd_sec & ~a_rbd_sec]
    flag[only_rbd_sec & ~a_rbd_sec] = "TIME_RBD_SEC_DISAGREE"

    only_rtv_sec = ~have_rbd & have_rtv & have_sec
    src[only_rtv_sec & a_rtv_sec] = "RTV_SEC_FILL"
    used[only_rtv_sec & a_rtv_sec] = rtv[only_rtv_sec & a_rtv_sec]
    src[only_rtv_sec & ~a_rtv_sec] = "RTV_SEC_FILL_DISAGREE"
    used[only_rtv_sec & ~a_rtv_sec] = rtv[only_rtv_sec & ~a_rtv_sec].fillna(sec)
    flag[only_rtv_sec & ~a_rtv_sec] = "TIME_RTV_SEC_DISAGREE_NO_RBD"

    only_rbd = have_rbd & ~have_rtv & ~have_sec
    src[only_rbd] = "RBD"
    used[only_rbd] = rbd[only_rbd]

    only_rtv = ~have_rbd & have_rtv & ~have_sec
    src[only_rtv] = "RTV_FILL"
    used[only_rtv] = rtv[only_rtv]

    only_sec = ~have_rbd & ~have_rtv & have_sec
    src[only_sec] = "SEC_FILL"
    used[only_sec] = sec[only_sec]

    none = ~have_rbd & ~have_rtv & ~have_sec
    src[none] = "NONE"

    r["time_src"] = src
    r["time_flag"] = flag
    r["win_time"] = used
    return r


def apply_dist_to_std(races_out, official, std_col="std_time", nat_col="win_natural"):
    """Restore official times and lift the standard from base yards to exact yards."""
    races_out["win_time"] = official.reindex(races_out.index)
    ey = races_out["exact_yards"]
    by = races_out["base_yards"]
    std_base = races_out[std_col]
    extra = (ST["k"] * (ey - by) * (std_base / by)).where(ey.notna() & by.notna() & (by > 0), 0.0)
    if std_col == "std_time":
        races_out["dist_adj_s"] = extra
        races_out["std_time_base"] = std_base
        races_out["secs_per_yard"] = (std_base / by).where(by.notna() & (by > 0))
    races_out[std_col] = std_base + extra
    refresh(races_out)
    ok = races_out["race_skip"] == ""
    ga = races_out["going_allowance_spf"]
    if std_col == "std_time_2yo":
        ga = ga.fillna(0.0)
    nat = (races_out[std_col] + ga * races_out["dist_f"] - races_out["win_time"]) * races_out["lbs_per_sec"] + v3.BASE_FIG
    races_out[nat_col] = nat.where(ok)
    return races_out


def scale_to_base(races):
    official = races["win_time"].copy()
    ey, by = races["exact_yards"], races["base_yards"]
    scale = (by / ey).where(ey.notna() & by.notna() & (ey > 0), 1.0)
    work = races.copy()
    work["win_time"] = official * scale
    refresh(work)
    return work, official


def run_v4(rn, races, *args, **kw):
    work, official = scale_to_base(races)
    races_out, st, gd, cpt = _orig_run(rn, work, *args, **kw)
    races_out = apply_dist_to_std(races_out, official)
    ST["races"] = races_out
    return races_out, st, gd, cpt


def run_2yo_v4(rn, races, *args, **kw):
    work, official = scale_to_base(races)
    r2, st, cpt = _orig_run_2yo(rn, work, *args, **kw)
    if len(r2) == 0:
        return r2, st, cpt
    r2 = apply_dist_to_std(r2, official, std_col="std_time_2yo", nat_col="win_natural_2yo")
    return r2, st, cpt


def settle_disagreements(rn, r):
    """For flagged disagreements, keep RBD unless an alternative sits nearer class par by SWITCH_LB."""
    need = r["time_flag"].isin(["TIME_TRIPLE_DISAGREE", "TIME_RBD_RTV_DISAGREE", "TIME_RBD_SEC_DISAGREE"])
    if not need.any():
        return r
    v3.log("v4: class-par pass for %d winning-time disagreements" % int(need.sum()))
    try:
        r1, _, _, _ = v3.run(rn, r, iters=6, verbose=False)
    except Exception as ex:
        v3.log("v4: class-par pass skipped (%s); keeping provisional times" % ex)
        return r
    _, resid = v3.flag_suspect_times(r1)
    lbps = r1["lbs_per_sec"]

    def switch_to(mask, alt, label):
        m = mask & resid.notna() & alt.notna()
        alt_resid = resid + (r["win_time"] - alt) * lbps
        sw = m & (alt_resid.abs() + SWITCH_LB < resid.abs())
        r.loc[sw, "win_time"] = alt[sw]
        r.loc[sw, "time_src"] = label
        return int(sw.sum())

    td = r["time_flag"] == "TIME_TRIPLE_DISAGREE"
    n_sw = 0
    if td.any():
        rtv_res = resid + (r["win_time"] - r["rtv_results_time"]) * lbps
        sec_res = resid + (r["win_time"] - r["sect_time"]) * lbps
        use_rtv = r["rtv_results_time"].notna() & (r["sect_time"].isna() | (rtv_res.abs() <= sec_res.abs()))
        alt = r["rtv_results_time"].where(use_rtv, r["sect_time"])
        alt_resid = rtv_res.where(use_rtv, sec_res)
        lab = pd.Series(np.where(use_rtv, "TRIPLE_USE_RTV", "TRIPLE_USE_SEC"), index=r.index, dtype=object)
        sw = td & resid.notna() & alt.notna() & (alt_resid.abs() + SWITCH_LB < resid.abs())
        r.loc[sw, "win_time"] = alt[sw]
        r.loc[sw, "time_src"] = lab[sw]
        r.loc[td & ~sw, "time_src"] = "TRIPLE_USE_RBD"
        n_sw += int(sw.sum())
        n_keep = int((td & ~sw).sum())
        v3.log("v4: all three times disagree on %d races; used RTV/sectionals on %d, kept RBD on %d" % (int(td.sum()), int(sw.sum()), n_keep))

    n_sw += switch_to(r["time_flag"] == "TIME_RBD_RTV_DISAGREE", r["rtv_results_time"], "RTV_XCHECK")
    n_sw += switch_to(r["time_flag"] == "TIME_RBD_SEC_DISAGREE", r["sect_time"], "SEC_XCHECK")
    refresh(r)
    v3.log("v4: switched %d disagreements to the alternative time (nearer class par by >=%.0f lb)" % (n_sw, SWITCH_LB))
    return r


def estimate_k(r):
    """Observed seconds per extra yard vs pro-rata (k=1). Reported, not applied."""
    ok = (r["dist_status"] == "RTV_EXACT") & r["win_time"].notna() & r["exact_yards"].notna() & r["base_yards"].notna()
    ok = ok & (r["race_skip"] == "") & (r["base_yards"] > 0)
    d = r.loc[ok, ["std_key", "win_time", "exact_yards", "base_yards"]].copy()
    if len(d) < 200:
        return None
    d["dy"] = d["exact_yards"] - d["base_yards"]
    if d["dy"].abs().max() < 5:
        return None
    d["t0"] = d["win_time"] - d.groupby("std_key")["win_time"].transform("mean")
    d["y0"] = d["dy"] - d.groupby("std_key")["dy"].transform("mean")
    var = float((d["y0"] ** 2).sum())
    if var < 1:
        return None
    slope = float((d["y0"] * d["t0"]).sum() / var)
    pr = float((d["win_time"] / d["exact_yards"]).median())
    if pr <= 0:
        return None
    return {"secs_per_yard_obs": slope, "secs_per_yard_prorata": pr, "k_hat": slope / pr, "n": int(len(d))}


def prepare_v4(rn):
    rn, r = _orig_prepare(rn)
    v3.log("v4: joining Racing TV races (exact distance / sectional time)")
    j, rep = rtv_table(rn, r)
    ST["rep"] = {k: rep[k] for k in rep if isinstance(rep[k], (int, float, str))}
    r["win_time_official"] = r["win_time"]
    r["rtv_race_id"] = j["rtv_race_id"].reindex(r.index)
    r["rtv_yards"] = j["distance_yards"].reindex(r.index)
    r["sect_time"] = j["sect_time"].reindex(r.index)
    r["rtv_time"] = r["sect_time"]

    v3.log("v4: reading Racing TV results times (live, read-only)")
    rt = load_rtv_results_times(ST["start"], ST["end"])
    r["rtv_results_time"] = pd.to_numeric(r["rtv_race_id"], errors="coerce").map(rt)

    r["rbd_yards"] = r["dist_f"] * 220.0
    r["dy"] = r["rtv_yards"] - r["rbd_yards"]
    ok_d = r["rtv_yards"].notna() & (r["dy"].abs() <= MAX_DY)
    r["dist_status"] = np.where(r["rtv_yards"].isna(), "NO_RTV",
                       np.where(ok_d, "RTV_EXACT", "RTV_CONFLICT"))
    # RTV yards when they are trustworthy; RBD fallback for NO_RTV and conflicts (both flagged)
    r["exact_yards"] = r["rtv_yards"].where(ok_d, r["rbd_yards"])

    ref = r.loc[r["dist_status"] == "RTV_EXACT"].groupby("std_key")["exact_yards"].median()
    ref_all = r.groupby("std_key")["exact_yards"].median()
    r["base_yards"] = r["std_key"].map(ref).fillna(r["std_key"].map(ref_all))
    r["ref_yards"] = r["base_yards"]

    r = resolve_times(r)
    refresh(r)
    r = settle_disagreements(rn, r)
    refresh(r)

    ST["k_hat"] = estimate_k(r)
    ST["races"] = r
    n_rtv = int((r["dist_status"] == "RTV_EXACT").sum())
    n_no = int((r["dist_status"] == "NO_RTV").sum())
    n_cf = int((r["dist_status"] == "RTV_CONFLICT").sum())
    v3.log("v4: exact RTV distance on {:,} races; RBD fallback on {:,} NO_RTV and {:,} RTV_CONFLICT".format(n_rtv, n_no, n_cf))
    v3.log("v4: time sources: %s" % r["time_src"].value_counts().to_dict())
    return rn, r


def corr_next(path, keep=None):
    f = pd.read_csv(path, usecols=["race_id", "date", "horse_id", "weighted_fig", "code"], low_memory=False)
    f = f[f["weighted_fig"].notna() & f["horse_id"].notna()]
    f = f.sort_values(["horse_id", "date"])
    g = f.groupby("horse_id")
    f["nxt"] = g["weighted_fig"].shift(-1)
    f["nxt_race"] = g["race_id"].shift(-1)
    f["nc"] = g["code"].shift(-1)
    f = f[f["nxt"].notna() & (f["nc"] == f["code"])].copy()
    if keep is not None:
        f = f.merge(keep, on=["race_id", "horse_id", "nxt_race"])
    cols = f[["race_id", "horse_id", "nxt_race"]]
    if len(f) < 3:
        return float("nan"), 0, cols
    return float(np.corrcoef(f["weighted_fig"], f["nxt"])[0, 1]), len(f), cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist-k", type=float, default=1.0)
    ap.add_argument("--xlsx", action="store_true")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output folder (default data/speed_v4). Use a sidecar folder for slice tests.")
    a, rest = ap.parse_known_args()
    ST.update(k=a.dist_k, start=a.start, end=a.end)
    out = Path(a.out) if a.out else DATA / "speed_v4"
    if not out.is_absolute():
        out = ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    v3.prepare = prepare_v4
    v3.run = run_v4
    v3.run_2yo = run_2yo_v4
    if not a.xlsx:
        v3.write_xlsx = lambda *x, **y: v3.log("(review workbook skipped; use --xlsx)")
    sys.argv = [sys.argv[0], "--out", str(out)] + (["--start", a.start] if a.start else []) + (["--end", a.end] if a.end else []) + rest
    v3.main()
    r = ST["races"]
    cols = ["date", "off_time", "course", "surface", "code", "distance_raw", "dist_f", "rbd_yards", "rtv_race_id", "rtv_yards",
            "dy", "dist_status", "exact_yards", "base_yards", "ref_yards", "dist_adj_s", "secs_per_yard", "std_time_base", "std_time",
            "win_time_official", "rtv_results_time", "sect_time", "rtv_time", "time_src", "time_flag", "win_time", "race_skip"]
    cols = [c for c in cols if c in r.columns]
    dc = r[cols].rename(columns={"win_time": "win_time_used"}).round(3)
    dc.index.name = "race_id"
    dc.to_csv(out / "distance_corrections.csv")
    v3.log("v4: pace-adjusted figures (sectionals_v12 adjustments)")
    fig = pd.read_csv(out / "speed_figures.csv", low_memory=False)
    rs = DATA / "sectionals_v12" / "runner_sectionals.csv.gz"
    if rs.is_file():
        s = pd.read_csv(rs, usecols=["race_id", "horse_name", "adj", "unreliable", "race_pace"]).dropna(subset=["race_id"])
        s["hk"] = s["horse_name"].map(s12.horse_key); s = s.drop_duplicates(["race_id", "hk"])
        fig["hk"] = fig["horse"].map(s12.horse_key)
        fig = fig.drop(columns=[c for c in ("adj", "unreliable", "race_pace") if c in fig.columns]).merge(
            s[["race_id", "hk", "adj", "unreliable", "race_pace"]], on=["race_id", "hk"], how="left").drop(columns="hk")
        fig = fig.rename(columns={"adj": "pace_adj_lb", "unreliable": "pace_unreliable"})
        fig["pace_adj_fig"] = (fig["weighted_fig"] + fig["pace_adj_lb"].fillna(0.0)).round(1)
        fig.to_csv(out / "speed_figures.csv", index=False)
    L = ["FurlongIQ speed figures v4 - summary", "=" * 40, f"races {len(r):,}; join {ST['rep']}"]
    if ST.get("rtv_results_span"):
        L.append("Racing TV results times read live from racing_history.sqlite: {} to {} (no end-date cap)".format(*ST["rtv_results_span"]))
    vc = r["dist_status"].value_counts().to_dict(); L.append(f"distance status: {vc}")
    e = r[r["dist_status"] == "RTV_EXACT"]
    if len(e):
        L.append("RTV exact vs RBD rounded trip: differ >10y {:.1%}, >22y {:.1%}, >44y {:.1%}".format(
            float((e["dy"].abs() > 10).mean()), float((e["dy"].abs() > 22).mean()), float((e["dy"].abs() > 44).mean())))
    if "dist_adj_s" in r.columns:
        c = r["dist_adj_s"]
        moved = c.abs() > 0.05
        L.append("distance adjustment to the standard (recorded times unchanged): {:,} races; |adj| median {:.2f}s, 90th pct {:.2f}s".format(
            int(moved.sum()), float(c[moved].abs().median()) if moved.any() else 0.0,
            float(c[moved].abs().quantile(.9)) if moved.any() else 0.0))
        if "lbs_per_sec" in r.columns and moved.any():
            lb = (c * r["lbs_per_sec"]).abs()
            L.append("   = winner figure moves of median {:.1f} lb, 90th pct {:.1f} lb".format(
                float(lb[moved].median()), float(lb[moved].quantile(.9))))
        mile = r[r["dist_f"].between(7.5, 8.5) & r["secs_per_yard"].notna()] if "secs_per_yard" in r.columns else r.iloc[0:0]
        if len(mile):
            spy = float(mile["secs_per_yard"].median())
            L.append("   pro-rata at ~1m: 22y costs {:.2f}s (expect ~1.2-1.4s)".format(22.0 * spy))
    kh = ST.get("k_hat")
    if kh:
        L.append("observed extra-yard cost vs pro-rata (k=1 is used): k_hat={:.2f} (obs {:.4f} s/y, pro-rata {:.4f} s/y, n={:,})".format(
            kh["k_hat"], kh["secs_per_yard_obs"], kh["secs_per_yard_prorata"], kh["n"]))
    else:
        L.append("observed extra-yard cost: not enough variation in this run to estimate k; using pro-rata (k=1)")
    L.append("winning-time rule: RBD when all three agree; RTV/sectionals when those two agree and RBD differs; flagged if all three disagree.")
    L.append(f"time source: {r['time_src'].value_counts().to_dict()}")
    if "time_flag" in r.columns:
        fc = r.loc[r["time_flag"].fillna("") != "", "time_flag"].value_counts().to_dict()
        L.append(f"time flags: {fc if fc else '{}'}")
        n_td = int((r["time_src"].astype(str).str.startswith("TRIPLE_")).sum())
        if n_td:
            L.append("  all-three-disagree outcomes: %s" % r.loc[r["time_src"].astype(str).str.startswith("TRIPLE_"), "time_src"].value_counts().to_dict())
    try:
        s3 = pd.read_csv(DATA / "speed_v3" / "standard_times.csv"); s4 = pd.read_csv(out / "standard_times.csv")
        m = s3[["std_key", "std_time"]].merge(s4[["std_key", "std_time", "n_used"]], on="std_key", suffixes=("_v3", "_v4"))
        d = (m["std_time_v4"] - m["std_time_v3"]).abs()
        L.append(f"standards moved vs v3 ({len(m)} common): median {d.median():.2f}s, 90th pct {d.quantile(.9):.2f}s, >0.5s on {int((d>0.5).sum())}")
        if not a.start and not a.end:
            c3u, n3u, k3 = corr_next(DATA / "speed_v3" / "speed_figures.csv")
            c4u, n4u, k4 = corr_next(out / "speed_figures.csv")
            common = k3.merge(k4, on=["race_id", "horse_id", "nxt_race"])
            c3, n3, _ = corr_next(DATA / "speed_v3" / "speed_figures.csv", common)
            c4, n4, _ = corr_next(out / "speed_figures.csv", common)
            L.append("repeatability on the SAME (race_id, horse_id, next race) pairs: v3 {:.4f} (n {:,})  v4 {:.4f} (n {:,})".format(c3, n3, c4, n4))
            L.append("   unpaired (each version's own pairs): v3 {:.4f} (n {:,})  v4 {:.4f} (n {:,})".format(c3u, n3u, c4u, n4u))
            L.append("   higher = more accurate figures. Switch the site to speed_v4 only if v4 >= v3 on the same-pair test.")
    except Exception as ex:
        L.append(f"(v3 comparison skipped: {ex})")
    (out / "summary.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace"); main()
