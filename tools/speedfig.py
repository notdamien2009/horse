#!/usr/bin/env python3
r"""
Speed figures v1  --  standard times, going allowances, natural + weighted figures.

Usage (Windows, from the Speeds folder):
    python tools\speedfig.py
    (optional) --input data\rbd_core.csv.gz --out data\speed --pct 35 --min-races 10
               --start 2026-09-01 --end 2026-10-31   (test on a date window)
Needs only pandas + numpy (+ openpyxl for the review workbook). No pyarrow.

Design: a source "adapter" turns any data source (RBD now, Sporting Life / sectionals later)
into one common runner table (see COMMON_COLUMNS). Everything after that is source-agnostic.
"""
import argparse, json, re, sys, os, time
from pathlib import Path
import numpy as np
import warnings
warnings.filterwarnings("ignore")
import pandas as pd

# ----------------------------------------------------------------------------------------
# Constants / user spec
# ----------------------------------------------------------------------------------------
BASE_FIG = 100.0
BASE_WT = {"Flat": 126.0, "Hurdle": 154.0, "Chase": 154.0, "NHF": 154.0}   # 9st flat, 11st jumps
FAMILY = {"Flat": "Flat", "Hurdle": "Jumps", "Chase": "Jumps", "NHF": "Jumps"}
LENGTH_M = 2.6            # one horse length in metres (~8.5 ft)
YARDS_PER_F = 220.0
M_PER_F = 201.168
CAP_LENGTHS = {"Flat": 20.0, "Jumps": 30.0}   # beyond this, beaten lengths count half + TAILED_OFF flag
MARGINS = {"dht": 0.0, "nse": 0.05, "sh": 0.1, "shd": 0.1, "sht-hd": 0.1, "hd": 0.2, "snk": 0.25,
           "nk": 0.3, "dist": 30.0}
FRAC = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1/3, "⅔": 2/3, "⅛": 0.125}
AW_GOINGS = {"standard", "standard to slow", "standard to fast", "slow", "fast"}
AW_ONLY_COURSES = {"wolverhampton", "chelmsford", "dundalk"}   # no turf track at all
NON_GOING_WORDS = {"rowley", "old course", "new course", "inner", "round", "outer", "straight"}
PLAUSIBLE_SPF = {"Flat": (10.3, 16.5), "NHF": (11.3, 19.0), "Hurdle": (11.3, 21.0), "Chase": (11.8, 23.0)}
GOING_ORDER = ["Hard", "Firm", "Good To Firm", "Good", "Good To Yielding", "Good To Soft", "Yielding",
               "Yielding To Soft", "Soft", "Soft To Heavy", "Heavy",
               "Fast", "Standard To Fast", "Standard", "Standard To Slow", "Slow"]

COMMON_COLUMNS = ["race_id", "date", "off_time", "course_raw", "distance_raw", "going_raw", "class_raw",
                  "race_name", "horse", "age", "weight_raw", "offr", "place_raw", "windist_raw",
                  "winning_time_raw", "runners"]

# ----------------------------------------------------------------------------------------
# Parsers
# ----------------------------------------------------------------------------------------
def parse_number_with_frac(s):
    """'1¾' -> 1.75, '½' -> 0.5, '12' -> 12.0"""
    s = s.strip()
    m = re.fullmatch(r"(\d*)([½¼¾⅓⅔⅛]?)", s)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    v = float(m.group(1)) if m.group(1) else 0.0
    return v + FRAC.get(m.group(2), 0.0)

def parse_margin_token(tok):
    if tok is None:
        return None
    t = tok.strip().lower().rstrip("-").strip()
    if t == "":
        return None
    if t in MARGINS:
        return MARGINS[t]
    return parse_number_with_frac(t)

WD_RE = re.compile(r"^\s*(?P<m>[^\[]*?)\s*-?\s*(?:\[(?P<c>[^\]]*)\])?\s*$")
def parse_windist(s):
    """returns (margin_to_horse_in_front, cumulative_behind_winner_from_bracket)"""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return (None, None)
    m = WD_RE.match(str(s))
    if not m:
        return (None, None)
    return (parse_margin_token(m.group("m")), parse_margin_token(m.group("c")))

def parse_distance_f(s):
    """'5½f' -> 5.5 ; '1m2½f' -> 10.5 ; '2m' -> 16"""
    if not isinstance(s, str):
        return np.nan
    m = re.fullmatch(r"\s*(?:(\d+)m)?\s*(?:(\d*)([½¼¾]?)f)?\s*", s)
    if not m or not any(m.groups()):
        return np.nan
    miles = int(m.group(1)) if m.group(1) else 0
    fur = (int(m.group(2)) if m.group(2) else 0) + FRAC.get(m.group(3) or "", 0.0)
    v = miles * 8 + fur
    return v if v > 0 else np.nan

def parse_time_s(s):
    """'1m 14.67s' -> 74.67 ; '59.60s' -> 59.6 ; 'Pending'/'' -> nan"""
    if not isinstance(s, str):
        return np.nan
    m = re.fullmatch(r"\s*(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s\s*", s)
    if not m:
        return np.nan
    return (int(m.group(1)) if m.group(1) else 0) * 60 + float(m.group(2))

def parse_weight_lb(s):
    m = re.fullmatch(r"\s*(\d+)-(\d+)\s*", str(s))
    return int(m.group(1)) * 14 + int(m.group(2)) if m else np.nan

def canon_course(raw):
    s = re.sub(r"\((AW|IRE)\)", "", raw)
    s = re.sub(r"[\s\-]", "", s).strip().lower()
    return s

def infer_code(name, med_wt, dist_f):
    """Race code from race name, checked against distance and weights carried."""
    n = name.lower()
    if "hurdle" in n:
        code = "Hurdle"
    elif re.search(r"\bchase\b|steeplechase", n):
        code = "Chase"
    elif (re.search(r"bumper|national hunt flat|\bn\.?h\.? flat|\bnhf\b|inh flat|standard open", n) or
          (re.search(r"\bflat race\b", n) and not re.search(r"won|flat races", n))):
        code = "NHF"
    else:
        code = "Flat"
    flag = ""
    # jumps word inside a Flat race name (e.g. sponsor "Chase Distillery"): jumps races are >= ~2m
    if code in ("Hurdle", "Chase") and ((dist_f == dist_f and dist_f < 15) or med_wt < 133):
        flag, code = "CODE_FROM_DIST_WEIGHT", "Flat"
    if code == "NHF" and dist_f == dist_f and dist_f < 12:
        flag, code = "CODE_FROM_DIST_WEIGHT", "Flat"
    return code, flag

def pattern_tag(name):
    n = name.lower()
    for k, tag in [(r"group 1|grade 1\b|\(g1\)", "G1"), (r"group 2|grade 2\b|\(g2\)", "G2"),
                   (r"group 3|grade 3\b|\(g3\)", "G3"), (r"listed", "L")]:
        if re.search(k, n):
            return tag
    return None

# ----------------------------------------------------------------------------------------
# Adapter: RBD parquet -> common table
# ----------------------------------------------------------------------------------------
def load_rbd(path, start=None, end=None):
    cols = ["Date", "Time", "Track Name", "Distance", "Going", "Class (GB only)", "Race Name", "Horse",
            "Age", "Weight", "OffR", "Place_raw", "WinDist", "Winning Time", "Runners"]
    if str(path).endswith(".parquet"):
        df = pd.read_parquet(path, columns=cols)
    else:
        df = pd.read_csv(path, usecols=cols, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8")
    if start: df = df[df["Date"].astype(str) >= start]
    if end: df = df[df["Date"].astype(str) <= end]
    out = pd.DataFrame({
        "date": pd.to_datetime(df["Date"].astype(str)),
        "off_time": df["Time"].astype(str).str[:5],
        "course_raw": df["Track Name"].astype(str),
        "distance_raw": df["Distance"],
        "going_raw": df["Going"],
        "class_raw": pd.to_numeric(df["Class (GB only)"], errors="coerce"),
        "race_name": df["Race Name"].astype(str),
        "horse": df["Horse"].astype(str),
        "age": pd.to_numeric(df["Age"], errors="coerce"),
        "weight_raw": df["Weight"].astype(str),
        "offr": pd.to_numeric(df["OffR"], errors="coerce"),        # '–' -> NaN
        "place_raw": df["Place_raw"].astype(str).str.strip(),
        "windist_raw": df["WinDist"],
        "winning_time_raw": df["Winning Time"],
        "runners": pd.to_numeric(df["Runners"], errors="coerce"),
    })
    out["race_id"] = out["date"].dt.strftime("%Y%m%d") + "_" + out["course_raw"].map(canon_course) + "_" + out["off_time"].str.replace(":", "")
    return out[COMMON_COLUMNS]

# ----------------------------------------------------------------------------------------
# Race / runner preparation
# ----------------------------------------------------------------------------------------
def prepare(rn):
    rn = rn.copy()
    rn["course"] = rn["course_raw"].map(canon_course)
    rn["weight_lb"] = rn["weight_raw"].map(parse_weight_lb)
    rn["place"] = pd.to_numeric(rn["place_raw"], errors="coerce")
    md = rn["windist_raw"].map(parse_windist)
    rn["margin_l"] = [a for a, b in md]
    rn["bracket_l"] = [b for a, b in md]
    rn["margin_l"] = pd.to_numeric(rn["margin_l"], errors="coerce")
    rn["bracket_l"] = pd.to_numeric(rn["bracket_l"], errors="coerce")

    # race level ---------------------------------------------------------------------
    g = rn.groupby("race_id", sort=False)
    races = g.agg(date=("date", "first"), off_time=("off_time", "first"), course=("course", "first"),
                  course_raw=("course_raw", "first"), distance_raw=("distance_raw", "first"),
                  going_raw=("going_raw", "first"), class_raw=("class_raw", "first"),
                  race_name=("race_name", "first"), wt_med=("weight_lb", "median"),
                  max_or=("offr", "max"), min_age=("age", "min"), max_age=("age", "max"),
                  winning_time_raw=("winning_time_raw", "first"), n_rows=("horse", "size"))
    races["dist_f"] = races["distance_raw"].map(parse_distance_f)
    races["win_time"] = races["winning_time_raw"].map(parse_time_s)
    gr = races["going_raw"].fillna("").astype(str).str.strip()
    races["going"] = np.where(gr.str.lower().isin(NON_GOING_WORDS) | (gr == ""), "Unknown", gr)
    races["going_note"] = np.where(gr.str.lower().isin(NON_GOING_WORDS), gr, "")
    is_aw = (races["course_raw"].str.contains(r"\(AW\)") |
             races["going"].str.lower().isin(AW_GOINGS) |
             races["course"].isin(AW_ONLY_COURSES))
    races["surface"] = np.where(is_aw, "AW", "Turf")
    cf = [infer_code(n, w, d) for n, w, d in zip(races["race_name"], races["wt_med"].fillna(140), races["dist_f"])]
    races["code"] = [c for c, f in cf]
    races["code_flag"] = [f for c, f in cf]
    races["family"] = races["code"].map(FAMILY)
    races["base_wt"] = races["code"].map(BASE_WT)

    # class group used to normalise standards / going allowances for race quality
    pt = races["race_name"].map(pattern_tag)
    hcap = races["race_name"].str.lower().str.contains("handicap|nursery")
    def grp(i):
        r = races.loc[i]
        fam = r["family"]
        juv = "2yo" if (fam == "Flat" and r["max_age"] == 2) else ""
        if isinstance(pt[i], str):
            base = pt[i]
        elif not np.isnan(r["class_raw"]):
            base = f"C{int(r['class_raw'])}"
        else:   # Ireland: no class -> handicap OR band, or race type
            n = r["race_name"].lower()
            if hcap[i] and not np.isnan(r["max_or"]):
                base = f"IRE_H{int(min(max(r['max_or'] // 10 * 10, 40), 140 if fam=='Jumps' else 110))}"
            elif r["code"] == "NHF":
                base = "IRE_NHF"
            elif re.search(r"maiden|beginners", n):
                base = "IRE_MDN"
            elif re.search(r"novice|juvenile", n):
                base = "IRE_NOV"
            else:
                base = "IRE_OTH"
        return f"{fam}|{r['code'] if fam=='Jumps' else 'Flat'}|{base}{'|'+juv if juv else ''}"
    races["class_group"] = [grp(i) for i in races.index]
    races["meeting_id"] = races["date"].dt.strftime("%Y%m%d") + "_" + races["course"] + "_" + races["surface"]
    races["std_key"] = races["course"] + "|" + races["surface"] + "|" + races["code"] + "|" + races["dist_f"].map(lambda x: f"{x:g}f" if x == x else "na")

    # winners (dead heats -> average weight)
    win = rn[rn["place"] == 1].groupby("race_id")["weight_lb"].mean()
    races["win_wt"] = win.reindex(races.index)

    # skip reasons at race level
    spf = races["win_time"] / races["dist_f"]
    lo = races["code"].map(lambda c: PLAUSIBLE_SPF[c][0]); hi = races["code"].map(lambda c: PLAUSIBLE_SPF[c][1])
    reason = pd.Series("", index=races.index, dtype=object)
    reason[races["win_time"].isna()] = "NO_WINNING_TIME"
    reason[(reason == "") & races["dist_f"].isna()] = "NO_DISTANCE"
    reason[(reason == "") & races["win_wt"].isna()] = "NO_WINNER"
    reason[(reason == "") & ((spf < lo) | (spf > hi))] = "IMPLAUSIBLE_TIME"
    races["race_skip"] = reason

    # speed / scale per race
    races["dist_m"] = races["dist_f"] * M_PER_F
    races["lbs_per_length"] = 2.0 * (8.0 / races["dist_f"]) ** 0.8
    races["sec_per_length"] = LENGTH_M / (races["dist_m"] / races["win_time"])
    races["lbs_per_sec"] = races["lbs_per_length"] / races["sec_per_length"]

    # beaten lengths per runner --------------------------------------------------------
    rn = rn.sort_values(["race_id", "place"], na_position="last").reset_index(drop=True)
    fin = rn["place"].notna() & (rn["place"] >= 1)
    rn["cum_from_margins"] = np.nan
    m = rn["margin_l"].where(fin & (rn["place"] > 1), 0.0).fillna(0.0)
    rn.loc[fin, "cum_from_margins"] = m[fin].groupby(rn.loc[fin, "race_id"]).cumsum()
    rn["beaten_l"] = np.where(rn["place"] == 1, 0.0, rn["bracket_l"])
    rn["bl_source"] = np.where(rn["place"] == 1, "winner", np.where(rn["bracket_l"].notna(), "bracket", ""))
    use_sum = fin & rn["beaten_l"].isna()
    rn.loc[use_sum, "beaten_l"] = rn.loc[use_sum, "cum_from_margins"]
    rn.loc[use_sum, "bl_source"] = "sum_margins"
    # runner whose own margin is missing and has no bracket -> sum is unreliable
    bad = use_sum & (rn["place"] > 1) & rn["margin_l"].isna()
    rn.loc[bad, "bl_source"] = "sum_margins_gap"
    return rn, races

# ----------------------------------------------------------------------------------------
# Core: standards <-> going allowance <-> class pars (iterated)
# ----------------------------------------------------------------------------------------
def robust_pct(x, pct):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return np.nan, 0, 0
    q1, q3 = np.percentile(x, [25, 75]); iqr = q3 - q1
    keep = x[(x >= q1 - 1.5 * iqr) & (x <= q3 + 1.5 * iqr)] if len(x) >= 5 else x
    return np.percentile(keep, pct), len(keep), len(x) - len(keep)

def compute_standards(races, tnorm, pct, min_races, blend_from):
    ok = races["race_skip"] == ""
    d = pd.DataFrame({"std_key": races["std_key"], "t": tnorm, "course": races["course"], "surface": races["surface"],
                      "code": races["code"], "dist_f": races["dist_f"]})[ok]
    rows = []
    for k, sub in d.groupby("std_key"):
        p35, n_keep, n_out = robust_pct(sub["t"], pct)
        p30, _, _ = robust_pct(sub["t"], pct - 5)
        p40, _, _ = robust_pct(sub["t"], pct + 5)
        med, _, _ = robust_pct(sub["t"], 50)
        rows.append(dict(std_key=k, course=sub["course"].iat[0], surface=sub["surface"].iat[0], code=sub["code"].iat[0],
                         dist_f=sub["dist_f"].iat[0], n_races=len(sub), n_used=n_keep, n_outliers=n_out,
                         emp_p30=p30, emp_p35=p35, emp_p40=p40, emp_median=med))
    st = pd.DataFrame(rows)
    # fallback model: log(time) = a_course + b_code_surface * log(dist), fitted on well-sampled standards
    good = st[st["n_used"] >= min_races].copy()
    good["lt"], good["ld"] = np.log(good["emp_p35"]), np.log(good["dist_f"])
    slopes = {}
    for (code, surf), s in good.groupby(["code", "surface"]):
        if s["ld"].nunique() >= 3:
            slopes[(code, surf)] = np.polyfit(s["ld"], s["lt"], 1)
    fam_slope = {}
    for code, s in good.groupby("code"):
        fam_slope[code] = np.polyfit(s["ld"], s["lt"], 1)
    def fit_for(r):
        b, a = slopes.get((r["code"], r["surface"]), fam_slope.get(r["code"], fam_slope["Flat"]))
        cs = good[(good["course"] == r["course"]) & (good["surface"] == r["surface"]) & (good["code"] == r["code"])]
        if len(cs):
            off = np.median(cs["lt"] - (a + b * cs["ld"]))
            return np.exp(a + b * np.log(r["dist_f"]) + off), "COURSE_FIT"
        cs = good[(good["course"] == r["course"]) & (good["surface"] == r["surface"])]   # other code same track
        if len(cs):
            off = np.median([lt - (slopes.get((c, s_), fam_slope.get(c))[1] + slopes.get((c, s_), fam_slope.get(c))[0] * ld)
                             for lt, ld, c, s_ in zip(cs["lt"], cs["ld"], cs["code"], cs["surface"])])
            return np.exp(a + b * np.log(r["dist_f"]) + off), "COURSE_FIT_OTHER_CODE"
        return np.exp(a + b * np.log(r["dist_f"])), "GLOBAL_FIT"
    fits = [fit_for(r) for _, r in st.iterrows()]
    st["fit_time"] = [f for f, _ in fits]
    std, flag = [], []
    for (_, r), (ft, fl) in zip(st.iterrows(), fits):
        n = r["n_used"]
        if n >= min_races:
            std.append(r["emp_p35"]); flag.append("EMPIRICAL")
        elif n >= blend_from:
            w = n / min_races
            std.append(w * r["emp_p35"] + (1 - w) * ft); flag.append("BLEND_" + fl)
        else:
            std.append(ft); flag.append("FALLBACK_" + fl)
    st["std_time"] = std
    st["std_flag"] = flag
    # 30th/40th reported on the same basis (shift by the empirical spread when available)
    st["std_p30"] = np.where(st["std_flag"] == "EMPIRICAL", st["emp_p30"], st["std_time"] - (st["emp_p35"] - st["emp_p30"]).fillna(0))
    st["std_p40"] = np.where(st["std_flag"] == "EMPIRICAL", st["emp_p40"], st["std_time"] + (st["emp_p40"] - st["emp_p35"]).fillna(0))
    return st

SUSPECT_LB = 40.0
def flag_suspect_times(races):
    """Winner's weighted figure more than SUSPECT_LB away from its class par -> time/distance probably wrong."""
    ok = races["race_skip"] == ""
    wfig = races["win_natural"] + (races["win_wt"] - races["base_wt"])
    resid = wfig - BASE_FIG - races["class_par_lb"]
    bad = ok & (resid.abs() > SUSPECT_LB)
    return bad, resid

def trimmed_median(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]
    if len(v) == 0: return np.nan, 0
    if len(v) >= 4:
        med = np.median(v); mad = 1.4826 * np.median(np.abs(v - med))
        keep = v[np.abs(v - med) <= max(0.25, 3 * mad)]
        return np.median(keep), len(keep)
    return np.median(v), len(v)

def compute_going(races, dev_spf, prior_k=1.0):
    """dev_spf: per-race (class/weight-normalised time - standard)/furlong."""
    ok = (races["race_skip"] == "") & dev_spf.notna()
    d = races.loc[ok, ["meeting_id", "date", "course", "surface", "code", "family", "going"]].copy()
    d["v"] = dev_spf[ok]
    d["cgroup"] = np.where(d["code"] == "Chase", "Chase", np.where(d["family"] == "Jumps", "Hurdle+NHF", "Flat"))
    lvl1 = d.groupby(["meeting_id", "cgroup"])["v"].apply(lambda s: trimmed_median(s)).to_dict()
    lvl2 = d.groupby(["meeting_id"])["v"].apply(lambda s: trimmed_median(s)).to_dict()
    raw = []
    for mid, cg in zip(d["meeting_id"], d["cgroup"]):
        m1, n1 = lvl1[(mid, cg)]; m2, n2 = lvl2[mid]
        if n1 >= 3: raw.append((m1, n1, "CODE"))
        elif n2 >= 3 and n2 > n1: raw.append((m2, n2, "MEETING"))
        else: raw.append((m1, n1, "LOW_N"))
    d["ga_raw"] = [a for a, b, c in raw]; d["ga_n"] = [b for a, b, c in raw]; d["ga_level"] = [c for a, b, c in raw]
    # prior = typical allowance for that official going / surface / code-group (shrinks low-n meetings)
    pri = d.drop_duplicates(["meeting_id", "cgroup"]).groupby(["surface", "cgroup", "going"])["ga_raw"].median()
    d["prior"] = [pri.get((s, c, g), np.nan) for s, c, g in zip(d["surface"], d["cgroup"], d["going"])]
    d["prior"] = d["prior"].fillna(0.0)
    d["ga"] = (d["ga_n"] * d["ga_raw"] + prior_k * d["prior"]) / (d["ga_n"] + prior_k)
    return d

def run(rn, races, pct=35, min_races=10, blend_from=4, iters=12, verbose=True):
    ok = races["race_skip"] == ""
    lbps = races["lbs_per_sec"]
    t = races["win_time"]
    wt_adj_s = (races["win_wt"] - races["base_wt"]) / lbps      # extra weight slows the winner by this many s
    par = pd.Series(0.0, index=races.index)
    ga_spf = pd.Series(0.0, index=races.index)
    for it in range(iters):
        # time a base-weight, reference-class horse would have run, on the day's ground
        tnorm_day = t + par / lbps - wt_adj_s
        st = compute_standards(races, tnorm_day - ga_spf * races["dist_f"], pct, min_races, blend_from)
        std = races["std_key"].map(st.set_index("std_key")["std_time"])
        dev = (tnorm_day - std) / races["dist_f"]
        gd = compute_going(races, dev)
        ga_spf = gd["ga"].reindex(races.index).fillna(0.0)
        # class pars: how many lb above/below the reference each class group's winners run
        wfig = (std + ga_spf * races["dist_f"] - t) * lbps + (races["win_wt"] - races["base_wt"])
        cp = pd.DataFrame({"g": races["class_group"], "fam": races["family"], "w": wfig})[ok]
        agg = cp.groupby("g")["w"].agg(["median", "size"])
        shr = agg["median"] * agg["size"] / (agg["size"] + 20)
        newpar = races["class_group"].map(shr).fillna(0.0)
        for fam in ["Flat", "Jumps"]:                       # anchor: median race of each family = reference (0)
            msk = ok & (races["family"] == fam)
            newpar[races["family"] == fam] -= newpar[msk].median()
        if it >= 3:                                         # damping: pars and allowances are only weakly separable
            newpar = 0.5 * par + 0.5 * newpar
        delta = (newpar - par).abs().max()
        par = newpar
        if verbose:
            print(f"  iter {it}: max class-par change {delta:.2f} lb, standards {len(st)}, meetings {gd['meeting_id'].nunique()}")
    races = races.copy()
    races["class_par_lb"] = par
    races["std_time"] = std
    races["std_flag"] = races["std_key"].map(st.set_index("std_key")["std_flag"])
    races["std_n"] = races["std_key"].map(st.set_index("std_key")["n_used"])
    races["going_allowance_spf"] = ga_spf.where(ok)
    races["ga_level"] = gd["ga_level"].reindex(races.index)
    races["ga_n"] = gd["ga_n"].reindex(races.index)
    races["win_natural"] = (std + ga_spf * races["dist_f"] - t) * lbps + BASE_FIG
    races["win_natural"] = races["win_natural"].where(ok)
    # class groups table
    cpt = pd.DataFrame({"class_group": races["class_group"], "class_par_lb": par, "ok": ok}).groupby("class_group").agg(
        class_par_lb=("class_par_lb", "first"), races=("ok", "sum")).reset_index()
    return races, st, gd, cpt

def runner_figures(rn, races):
    r = rn.merge(races[["date", "surface", "code", "family", "dist_f", "going", "going_note",
                        "class_group", "meeting_id", "std_key", "std_time", "std_flag", "std_n", "win_time",
                        "going_allowance_spf", "ga_level", "ga_n", "lbs_per_length", "sec_per_length", "lbs_per_sec",
                        "base_wt", "race_skip", "code_flag", "class_par_lb"]].rename(columns={"date": "r_date"}),
                 left_on="race_id", right_index=True, how="left")
    cap = r["family"].map(CAP_LENGTHS)
    bl = r["beaten_l"]
    r["beaten_l_eff"] = np.where(bl > cap, cap + 0.5 * (bl - cap), bl)
    r["runner_time"] = r["win_time"] + r["beaten_l"] * r["sec_per_length"]
    r["natural_fig"] = (BASE_FIG + (r["std_time"] + r["going_allowance_spf"] * r["dist_f"] - r["win_time"]) * r["lbs_per_sec"]
                        - r["beaten_l_eff"] * r["lbs_per_length"])
    r["weighted_fig"] = r["natural_fig"] + (r["weight_lb"] - r["base_wt"])
    # skip reasons per runner
    reason = r["race_skip"].fillna("").astype(object)
    nf = r["place"].isna() | (r["place"] < 1)
    reason = np.where(reason != "", reason,
             np.where(nf, "NOT_FINISHED_" + r["place_raw"].astype(str),
             np.where(r["beaten_l"].isna(), "NO_BEATEN_LENGTHS",
             np.where(r["weight_lb"].isna(), "NO_WEIGHT", ""))))
    r["skip_reason"] = reason
    keep = r["skip_reason"] == ""
    r.loc[~keep, ["natural_fig", "weighted_fig", "runner_time"]] = np.nan
    flags = []
    for row in r[["bl_source", "beaten_l", "std_flag", "ga_level", "code_flag", "going_note", "family"]].itertuples(index=False):
        f = []
        if row.beaten_l == row.beaten_l and row.beaten_l > CAP_LENGTHS[row.family]: f.append("TAILED_OFF")
        if row.bl_source == "sum_margins_gap": f.append("BL_GAP")
        elif row.bl_source == "sum_margins": f.append("BL_SUMMED")
        if isinstance(row.std_flag, str) and row.std_flag != "EMPIRICAL": f.append("STD_" + row.std_flag)
        if row.ga_level == "LOW_N": f.append("GA_LOW_N")
        if row.code_flag: f.append(row.code_flag)
        if row.going_note: f.append("GOING_FIELD_" + row.going_note.upper().replace(" ", "_"))
        flags.append(";".join(f))
    r["flags"] = flags
    r.loc[~keep, "flags"] = r.loc[~keep, "flags"]
    return r

# ----------------------------------------------------------------------------------------
def default_root():
    here = Path(__file__).resolve().parent
    return here.parent if here.name.lower() == "tools" else Path.cwd()

def log(msg, t0=[time.time()]):
    print(f"[{time.time()-t0[0]:6.1f}s] {msg}", flush=True)

def main():
    root = default_root()
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(root / "data" / "rbd_core.csv.gz"))
    ap.add_argument("--out", default=str(root / "data" / "speed"))
    ap.add_argument("--pct", type=float, default=35)
    ap.add_argument("--min-races", type=int, default=10)
    ap.add_argument("--start"); ap.add_argument("--end")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    log(f"loading {a.input}")
    rn = load_rbd(a.input, a.start, a.end)
    log("parsing races / margins")
    rn, races = prepare(rn)
    log(f"runners {len(rn)}, races {len(races)}")
    log("pass 1: standards <-> going allowances <-> class pars")
    races1, st, gd, cpt = run(rn, races, pct=a.pct, min_races=a.min_races)
    bad, resid = flag_suspect_times(races1)
    races.loc[bad, "race_skip"] = "TIME_SUSPECT"
    log(f"{int(bad.sum())} races flagged TIME_SUSPECT (winner >{SUSPECT_LB:.0f} lb off class par); pass 2 without them")
    races, st, gd, cpt = run(rn, races, pct=a.pct, min_races=a.min_races)
    log("runner figures")
    fig = runner_figures(rn, races)
    # ---- standards
    sto = st[["std_key", "course", "surface", "code", "dist_f", "n_races", "n_used", "n_outliers", "std_time",
              "std_p30", "std_p40", "emp_median", "fit_time", "std_flag"]].copy()
    sto["std_time_fmt"] = sto["std_time"].map(lambda x: f"{int(x//60)}m {x%60:05.2f}s")
    sto["std_sec_per_f"] = sto["std_time"] / sto["dist_f"]
    sto = sto.sort_values(["course", "surface", "code", "dist_f"]).round(3)
    sto.to_csv(out / "standard_times.csv", index=False)
    # ---- going allowances (one row per meeting x code group)
    gm = gd.groupby(["meeting_id", "cgroup"]).agg(date=("date", "first"), course=("course", "first"),
            surface=("surface", "first"), official_going=("going", lambda s: s.mode().iat[0]),
            races=("v", "size"), ga_raw_spf=("ga_raw", "first"), prior_spf=("prior", "first"),
            going_allowance_spf=("ga", "first"), ga_level=("ga_level", "first"), ga_n=("ga_n", "first")).reset_index()
    med = gm.groupby(["surface", "cgroup", "official_going"])["going_allowance_spf"].median()
    def implied(r):
        try: m = med.loc[(r["surface"], r["cgroup"])]
        except KeyError: return ""
        m = m[[g for g in m.index if g != "Unknown"]]
        return (m - r["going_allowance_spf"]).abs().idxmin() if len(m) else ""
    gm["implied_going"] = gm.apply(implied, axis=1)
    order = {g: i for i, g in enumerate(GOING_ORDER)}
    gm["going_steps_diff"] = [order[i] - order[o] if (i in order and o in order) else np.nan
                              for i, o in zip(gm["implied_going"], gm["official_going"])]
    gm["going_disagree"] = gm["going_steps_diff"].abs() >= 3
    gm = gm.sort_values(["date", "course"]).round(3)
    gm["date"] = pd.to_datetime(gm["date"]).dt.date
    gm.to_csv(out / "going_allowances.csv", index=False)
    # ---- figures
    out_cols = ["race_id", "r_date", "off_time", "course_raw", "course", "surface", "code", "distance_raw", "dist_f",
                "going", "class_raw", "class_group", "race_name", "horse", "age", "weight_raw", "weight_lb", "offr",
                "place_raw", "place", "windist_raw", "beaten_l", "bl_source", "beaten_l_eff", "win_time", "runner_time",
                "std_time", "std_flag", "going_allowance_spf", "lbs_per_length", "lbs_per_sec", "class_par_lb",
                "natural_fig", "weighted_fig", "flags", "skip_reason"]
    fo = fig[out_cols].rename(columns={"r_date": "date", "class_raw": "class"})
    fo["date"] = pd.to_datetime(fo["date"]).dt.date
    for c in ["natural_fig", "weighted_fig"]: fo[c] = fo[c].round(1)
    for c in ["beaten_l_eff", "runner_time", "std_time", "going_allowance_spf", "lbs_per_length", "lbs_per_sec", "class_par_lb"]:
        fo[c] = fo[c].round(3)
    log("writing speed_figures.csv")
    fo.to_csv(out / "speed_figures.csv", index=False)
    cpt.round(2).to_csv(out / "class_pars.csv", index=False)
    log("sanity checks")
    san = sanity(fo, races)
    san.to_csv(out / "sanity_checks.csv", index=False)
    (out / "METHOD.md").write_text(METHOD_MD, encoding="utf-8")
    log("review workbook")
    write_xlsx(out / "speed_review.xlsx", sto, gm, fo, san, cpt)
    log(f"done: {int(fo['natural_fig'].notna().sum())} runner figures -> {out}")

def sanity(fo, races):
    rows = []
    def add(section, key, value, n=None, note=""):
        rows.append(dict(section=section, key=key, value=value, n=n, note=note))
    has = fo["weighted_fig"].notna()
    rg = fo.groupby("race_id")["weighted_fig"].apply(lambda s: s.notna().any())
    add("coverage", "races_total", len(rg)); add("coverage", "races_with_figures", int(rg.sum()))
    add("coverage", "runners_total", len(fo)); add("coverage", "runners_with_figures", int(has.sum()))
    for k, v in races["race_skip"].replace("", np.nan).dropna().value_counts().items(): add("races_skipped", k, int(v))
    for k, v in fo.loc[~has, "skip_reason"].value_counts().items(): add("runners_skipped", k, int(v))
    for k, v in fo.loc[has, "flags"].fillna("").str.split(";").explode().loc[lambda s: s != ""].value_counts().items():
        add("flags_on_figured_runners", k, int(v))
    fam = np.where(fo["code"] == "Flat", "Flat", "Jumps")
    for f_ in ["Flat", "Jumps"]:
        for sub, m in [("all", fo["offr"].notna()), ("within5L", fo["offr"].notna() & (fo["beaten_l"] <= 5)),
                       ("winners", fo["offr"].notna() & (fo["place"] == 1))]:
            x = fo[has & m & (fam == f_)]
            for col in ["natural_fig", "weighted_fig"]:
                if len(x) > 2:
                    add("corr_with_OffR", f"{f_}|{sub}|{col}", round(x[col].corr(x["offr"]), 3), len(x), "pearson")
                    add("corr_with_OffR", f"{f_}|{sub}|{col}|spearman", round(x[col].rank().corr(x["offr"].rank()), 3), len(x))
    lbl = fo["class_group"].str.split("|").str[1:].str.join("|")
    for g, x in fo[has].groupby(lbl[has]):
        w = x.loc[x["place"] == 1, "weighted_fig"]
        add("by_class_winner_median", g, round(w.median(), 1), int(x["race_id"].nunique()))
        add("by_class_all_median", g, round(x["weighted_fig"].median(), 1), len(x))
    for f_ in ["Flat", "Jumps"]:
        t = fo[has & (fam == f_)].nlargest(20, "weighted_fig")
        for i, r in enumerate(t.itertuples(), 1):
            add(f"top20_{f_}", i, r.weighted_fig, None,
                f"{r.date} {r.course_raw} {r.off_time} {r.distance_raw} {r.going} | {r.horse} pos {r.place_raw} bl {r.beaten_l} wt {r.weight_raw} OR {r.offr} nat {r.natural_fig} | {r.flags}")
    return pd.DataFrame(rows)

def write_xlsx(path, sto, gm, fo, san, cpt):
    try:
        import openpyxl  # noqa
    except ImportError:
        print("openpyxl not installed - skipping workbook"); return
    d = pd.to_datetime(fo["date"])
    last = d.max(); m0 = (last - pd.offsets.MonthBegin(1)).normalize() if last.day < 28 else last.replace(day=1)
    sample = fo[(d >= m0 - pd.offsets.MonthBegin(1)) & (d < m0)] if last.day < 28 else fo[d >= m0]
    if len(sample) == 0: sample = fo.head(20000)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        sto.to_excel(xw, sheet_name="Standards", index=False)
        gm.to_excel(xw, sheet_name="Going allowances", index=False)
        sample.to_excel(xw, sheet_name="Sample month figures", index=False)
        san.to_excel(xw, sheet_name="Sanity checks", index=False)
        cpt.to_excel(xw, sheet_name="Class pars", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(40, max(9, len(str(col[0].value)) + 2))

METHOD_MD = r"""# Speed figures v1 – method (plain words)

Script: `tools\speedfig.py`. Input: `data\rbd_core.csv.gz` (RBD file, only the needed columns). Output: `data\speed\`.

## 1. Reading the data
- **Distance**: '5½f', '1m2½f', '2m' turned into furlongs (1m = 8f).
- **Winning time**: '1m 14.67s' or '59.60s' turned into seconds. 'Pending' or blank means the race is skipped (NO_WINNING_TIME).
- **Weight**: '9-7' turned into pounds (st×14 + lb).
- **Margins (WinDist)**: the part before the dash is the margin to the horse in front, and the [bracket] is the total lengths behind the winner. Word margins: dht 0, nse 0.05, sh/shd/sht-hd 0.1, hd 0.2, snk 0.25, nk 0.3, dist 30. Fractions ½ ¼ ¾ are handled. The bracket is used when present. Otherwise the margins are added up in finishing order (flag BL_SUMMED). If a margin is missing along the way the flag is BL_GAP.
- **Non-finishers** (PU, F, UR, BD, RR, RO, SU, REF, CO, DSQ) get no figure.
- **Course**: '(AW)' and '(IRE)' plus spaces are stripped, so 'GowranPark(IRE)' and 'Gowran Park' are the same course. The RBD file stops adding these suffixes from 25 Aug 2026.
- **Surface**: AW if the name has '(AW)', the going is Standard, Standard To Slow, Slow or Fast, or the course has no turf track (Wolverhampton, Chelmsford, Dundalk). Otherwise Turf.
- **Race code**, inferred from the race name:
  - Hurdle if the name contains 'hurdle'.
  - Chase if it contains the word 'chase' or 'steeplechase'.
  - NHF (bumper) if it contains bumper, National Hunt Flat, NH Flat, NHF, INH Flat or Standard Open, or the Irish 'Flat Race' (but not 'won a Flat race').
  - Everything else is Flat.
  - Check: a Hurdle or Chase under 15f, or with median weight under 9st 7, is really a Flat race with a sponsor name such as 'Chase Distillery'. These become Flat with the flag CODE_FROM_DIST_WEIGHT.
- **Going**: some rows have 'Rowley', 'Old Course', 'Inner' or 'Round' in the Going field. That is the track layout, so the going is treated as Unknown and a flag is added.

## 2. Class groups (used to normalise for race quality)
Each race gets a group: family (Flat or Jumps) | code | quality.
- Quality is Group/Grade 1-3 or Listed (from the race name), else the GB Class 1-6.
- Irish races have no class, so they are grouped by handicap OR band (top OR rounded down to 10) or by maiden, novice, bumper or other.
- Flat races for 2-year-olds only get their own '2yo' group.
- Each group's **class par** is the median number of pounds by which its winners beat the reference. It is shrunk towards 0 when the group is small (n/(n+20)).
- The median race in each family is set to 0. In other words, **100 = the typical winner of a median-class race, at base weight, on standard ground**.

## 3. Pounds per length and per second
- **lb per length** = 2 × (8 / furlongs)^0.8. That gives about 2.9 at 5f, 2.0 at 1m, 1.45 at 1m4f, 1.15 at 2m and 0.83 at 3m, close to the official BHA scales.
- **Seconds per length** = 2.6 m (one length) ÷ the winner's average speed in that race. That works out at about 0.15s in a fast sprint and 0.2-0.25s in slow jumps races or on heavy ground.
- **lb per second** = lb per length ÷ seconds per length. That is about 19 at 5f, 12.6 at 1m, 6 for a 2m hurdle and 4 for a 3m chase.

## 4. Standard times (course + surface + code + distance)
1. For each race the winner's time is normalised to "reference class, base weight, standard ground":
   - add the class par converted to seconds;
   - take off the winner's weight above base (9st Flat, 11st jumps) converted to seconds;
   - take off the meeting's going allowance × furlongs.
2. For each course/surface/code/distance, outliers are removed with the IQR rule (outside Q1 − 1.5·IQR to Q3 + 1.5·IQR).
3. **Standard = 35th percentile** of what is left, so it sits on the fast side. The 30th and 40th percentiles are also reported (std_p30, std_p40).
4. Sample size:
   - 10 or more races: the empirical standard is used (EMPIRICAL).
   - 4-9 races: the standard is blended with a fitted value (BLEND_…).
   - Fewer than 4: the fitted value only (FALLBACK_…).
   - The fit is log(time) = a + b·log(furlongs). The slope b comes from all well-sampled standards of that code and surface, and each course gets its own offset (COURSE_FIT). If the course has no good standard in that code, the offset comes from another code at the same course (COURSE_FIT_OTHER_CODE). If there is nothing at all, the global fit is used (GLOBAL_FIT).
5. Steps 1-4 run in a loop with the going allowances and class pars below (12 rounds, damped) until they settle.

## 5. Going allowance (per meeting)
1. For every race: deviation per furlong = (normalised time − standard) ÷ furlongs.
2. Races are grouped by meeting (date + course + surface) and split into Flat, Hurdle+NHF and Chase.
3. Robust median: values more than max(0.25 s/f, 3×MAD) from the median are dropped, then the median of the rest is taken.
4. If a code group has fewer than 3 races, the whole meeting's value is used (MEETING). If even that is too few, the flag is LOW_N.
5. The allowance is shrunk slightly towards the typical allowance for that official going: (n·value + 1·prior) / (n + 1).
6. Compared with the official going: `implied_going` is the official description whose median allowance is nearest. `going_disagree` is set when they are 3 or more steps apart.
7. Note: standards sit on the fast side, so most allowances are positive (slower than standard). That is expected.

## 6. Figures
- **Winner's natural figure** = 100 + (standard + going allowance × furlongs − winning time) × lb per second.
- **Beaten horses** lose beaten lengths × lb per length. Beyond 20 lengths (Flat) or 30 lengths (jumps) only half of each extra length counts, and the horse is flagged TAILED_OFF.
- **Weighted figure** = natural figure + (weight carried − base weight), with a base of 126 lb on the Flat and 154 lb over jumps.
- There is no weight-for-age or jockey-claim adjustment yet. The Weight column is used as given.

## 7. Safety checks
- **IMPLAUSIBLE_TIME**: seconds per furlong outside a sensible range for the code. The race is skipped.
- **TIME_SUSPECT**: after the first pass, a winner more than 40 lb away from its class par. That almost always means a wrong time or distance (e.g. a shortened race, or a time from a different race). These races are skipped and everything is recomputed without them.
- `sanity_checks.csv` holds: coverage and skip reasons, flag counts, correlation with OffR (natural and weighted; all runners, within 5 lengths, winners), the median figure by class, and the top 20 figures for Flat and Jumps.

## Known limits (v1)
- There are no rail movements or distance changes in the data, which is the biggest source of noise over jumps.
- Straight and round courses at the same distance (e.g. Ascot, Newmarket) are not told apart.
- Going is one value per meeting, so a change during the day is missed.
- To rerun on Sporting Life data, write another `load_…()` adapter that returns the same columns (`COMMON_COLUMNS`). Everything after that is shared.
"""

if __name__ == "__main__":
    main()
