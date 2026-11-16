#!/usr/bin/env python3
r"""
Speed figures v2  --  standard times, going allowances, natural + weighted (+WFA) + field-average figures.
v2 changes: small-sample standards shrunk + capped, BHA weight-for-age, course layouts
(Newmarket Rowley/July, Cheltenham Old/New/Cross Country), tighter tailed-off cap, floor 45.

Usage (Windows, from the Speeds folder):
    python tools\speedfig_v2.py
    (optional) --input data\rbd_core.csv.gz --out data\speed_v2 --pct 35 --min-races 10
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
CAP_LENGTHS = {"Flat": 15.0, "Jumps": 20.0}   # beyond this, beaten lengths count half + TAILED_OFF flag
DROP_LENGTHS = {"Flat": 30.0, "Jumps": 40.0}  # beyond this: no figure (BEATEN_TOO_FAR)
FIG_FLOOR = 45.0                               # any figure below this is set to 45 + FLOORED flag
SHRINK_K = 3.0          # small-sample standard = (n*empirical + K*fit)/(n+K), never slower than empirical
FIT_OFFSET_CAP = 0.03   # course offset in the fallback fit capped at +-3% of the code/surface line
OTHER_CODE_CAP = 0.02   # offset borrowed from another code at the same course capped at +-2%

# ---- Weight-for-age (lb). BHA Flat WFA scale 2025 (lb), 24 half-month columns Jan(1-15),Jan(16-31),...,Dec(16-31).
# Row "3" = allowance a 3yo receives from 4yo+; row "2" = allowance a 2yo receives from 3yo (so 2yo total = row2 + row3);
# row "4" = allowance a 4yo receives from 5yo+ (9f+). Source: media.britishhorseracing.com/bha/Rules/Weight_for_age/2025_Flat_WFA_Scale_Changes.pdf
_Z = [0] * 14
WFA_FLAT = {
    5:  {2: _Z + [26, 24, 22, 20, 18, 18, 17, 17, 16, 16], 3: [15, 15, 14, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 1, 0, 0, 0, 0, 0, 0]},
    6:  {2: _Z + [28, 26, 24, 22, 21, 20, 19, 18, 17, 17], 3: [16, 16, 15, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 2, 1, 1, 0, 0, 0, 0]},
    7:  {2: _Z + [30, 28, 26, 24, 23, 22, 21, 20, 19, 19], 3: [18, 18, 17, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 2, 1, 1, 0, 0]},
    8:  {2: _Z + [35, 32, 29, 27, 25, 24, 23, 22, 21, 21], 3: [20, 20, 19, 19, 18, 17, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 3, 2, 2, 1, 1]},
    9:  {3: [22, 22, 21, 21, 20, 19, 17, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 4, 3, 3, 2, 2], 4: [1, 1] + [0] * 22},
    10: {3: [23, 23, 22, 22, 21, 20, 19, 17, 15, 14, 13, 12, 10, 9, 8, 7, 6, 5, 4, 4, 3, 3, 2, 2], 4: [1, 1] + [0] * 22},
    11: {3: [24, 24, 23, 23, 22, 21, 20, 19, 17, 15, 14, 13, 11, 10, 9, 8, 7, 6, 5, 5, 4, 4, 3, 3], 4: [2, 2, 1, 1] + [0] * 20},
    12: {3: [25, 25, 24, 24, 23, 22, 21, 20, 19, 17, 15, 14, 12, 11, 10, 9, 8, 7, 6, 6, 5, 5, 4, 4], 4: [3, 3, 2, 2, 1, 1] + [0] * 18},
    13: {3: [26, 26, 25, 25, 24, 23, 22, 21, 20, 19, 17, 15, 13, 11, 10, 9, 8, 7, 6, 6, 5, 5, 4, 4], 4: [3, 3, 2, 2, 1, 1] + [0] * 18},
    14: {3: [26, 26, 25, 25, 24, 23, 22, 21, 20, 19, 17, 15, 13, 11, 10, 9, 8, 7, 6, 6, 5, 5, 4, 4], 4: [3, 3, 2, 2, 1, 1] + [0] * 18},
    15: {3: [28, 28, 27, 27, 26, 25, 23, 22, 21, 20, 18, 16, 14, 12, 11, 10, 9, 8, 7, 6, 5, 5, 4, 4], 4: [3, 3, 2, 2, 2, 2, 1, 1] + [0] * 16},
    16: {3: [29, 29, 28, 28, 27, 26, 24, 23, 22, 21, 20, 18, 16, 14, 12, 11, 10, 9, 8, 7, 6, 6, 5, 5], 4: [4, 4, 4, 4, 3, 3, 2, 2, 1, 1] + [0] * 14},
}
# The BHA table only starts the 2yo row in August (2yos rarely meet older horses before then). For 2yo-only races
# earlier in the season we extend it backwards by +2 lb per half-month (the slope of the published Aug-Sep values).
for _d in (5, 6, 7, 8):
    _r = WFA_FLAT[_d][2]
    for _i in range(13, -1, -1):
        _r[_i] = _r[_i + 1] + 2
# Calibration: with the full BHA 2yo allowance, 2yo figures in this data came out ~9 lb above their official
# ratings relative to older horses in every month (Jul-Dec). 65% of the BHA 2yo total matched OR best. Set to 1.0 for pure BHA.
WFA_2YO_FACTOR = 0.65
# Jumps (approximation of the BHA NH scale; 4yo vs 5yo+, 3yo juveniles vs 4yo+), by month 1..12.
WFA_JUMPS = {
    "Hurdle": {4: [8, 8, 7, 7, 6, 5, 4, 3, 3, 2, 1, 0], 3: [0, 0, 0, 0, 0, 0, 0, 15, 14, 13, 12, 10]},
    "NHF":    {4: [8, 8, 7, 7, 6, 5, 4, 3, 3, 2, 1, 0], 3: [0, 0, 0, 0, 0, 0, 0, 15, 14, 13, 12, 10]},
    "Chase":  {4: [10, 10, 9, 9, 8, 7, 6, 5, 4, 3, 2, 1]},
}

def wfa_lb(code, dist_f, age, date):
    """Weight-for-age allowance (lb) the horse receives from fully-aged rivals at this distance and date."""
    if not (age == age) or not (dist_f == dist_f):
        return 0.0
    age = int(age)
    if code != "Flat":
        row = WFA_JUMPS.get(code, {}).get(age)
        return float(row[date.month - 1]) if row else 0.0
    if age >= 5:
        return 0.0
    col = (date.month - 1) * 2 + (0 if date.day <= 15 else 1)
    d = int(min(max(round(dist_f), 5), 16))
    t = WFA_FLAT[d]
    if age == 4:
        return float(t.get(4, [0] * 24)[col])
    if age == 3:
        return float(t[3][col])
    if age == 2:
        two = WFA_FLAT[min(d, 8)][2][col]
        return float(round(WFA_2YO_FACTOR * (two + t[3][col])))
    return 0.0
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

def course_variant(course, date, going_raw, race_name, all_dates_by_course=None):
    """Split courses with different layouts. Returns (course_key, variant_note)."""
    n = str(race_name).lower(); g = str(going_raw).lower()
    if course == "newmarket(july)":     # RBD names the July Course itself until the suffixes stop (Aug 2026)
        return "newmarket_july", "TRACK_NAME"
    if course == "newmarket":
        if "rowley" in g or "rowley" in n: return "newmarket_rowley", "RACE_INFO"
        if "july course" in n: return "newmarket_july", "RACE_INFO"
        return ("newmarket_july", "DATE_RULE") if date.month in (6, 7, 8) else ("newmarket_rowley", "DATE_RULE")
    if course == "cheltenham":
        if "cross country" in n or "cross-country" in n: return "cheltenham_xc", "RACE_INFO"
        if "old course" in g: return "cheltenham_old", "RACE_INFO"
        if "new course" in g: return "cheltenham_new", "RACE_INFO"
        if date.month in (10, 11): return "cheltenham_old", "DATE_RULE"
        if date.month == 3 and all_dates_by_course is not None:      # Festival: days 1-2 Old, days 3-4 New
            ds = sorted(d for d in all_dates_by_course if d.year == date.year and d.month == 3)
            return ("cheltenham_old" if ds.index(date) < 2 else "cheltenham_new"), "DATE_RULE"
        return "cheltenham_new", "DATE_RULE"
    return course, ""

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
    # course layouts (v2): Newmarket Rowley/July, Cheltenham Old/New/Cross Country
    chd = set(races.loc[races["course"] == "cheltenham", "date"])
    cv = [course_variant(c, d, g, n, chd) for c, d, g, n in zip(races["course"], races["date"], races["going_raw"].fillna(""), races["race_name"])]
    races["course"] = [a for a, b in cv]
    races["course_variant_src"] = [b for a, b in cv]
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
    # weight-for-age (v2): effective weight = carried + WFA allowance received
    rdate = rn["race_id"].map(races["date"]); rcode = rn["race_id"].map(races["code"]); rdist = rn["race_id"].map(races["dist_f"])
    rn["wfa_lb"] = [wfa_lb(c, d, a, dt) for c, d, a, dt in zip(rcode, rdist, rn["age"], rdate)]
    rn["eff_wt"] = rn["weight_lb"] + rn["wfa_lb"]
    win = rn[rn["place"] == 1].groupby("race_id")["eff_wt"].mean()
    races["win_wt"] = win.reindex(races.index)
    races["field_avg_wt"] = rn.groupby("race_id")["weight_lb"].mean().reindex(races.index)

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
    # v2: course offsets capped, small samples shrunk towards the fit and never slower than their own evidence
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
            off = float(np.clip(np.median(cs["lt"] - (a + b * cs["ld"])), -FIT_OFFSET_CAP, FIT_OFFSET_CAP))
            return np.exp(a + b * np.log(r["dist_f"]) + off), "COURSE_FIT"
        cs = good[(good["course"] == r["course"]) & (good["surface"] == r["surface"])]   # other code same track
        if len(cs):
            off = np.median([lt - (slopes.get((c, s_), fam_slope.get(c))[1] + slopes.get((c, s_), fam_slope.get(c))[0] * ld)
                             for lt, ld, c, s_ in zip(cs["lt"], cs["ld"], cs["code"], cs["surface"])])
            off = float(np.clip(off, -OTHER_CODE_CAP, OTHER_CODE_CAP))
            return np.exp(a + b * np.log(r["dist_f"]) + off), "COURSE_FIT_OTHER_CODE"
        return np.exp(a + b * np.log(r["dist_f"])), "GLOBAL_FIT"
    fits = [fit_for(r) for _, r in st.iterrows()]
    st["fit_time"] = [f for f, _ in fits]
    std, flag = [], []
    for (_, r), (ft, fl) in zip(st.iterrows(), fits):
        n = r["n_used"]
        if n >= min_races:
            std.append(r["emp_p35"]); flag.append("EMPIRICAL")
        elif n >= 1 and r["emp_p35"] == r["emp_p35"]:
            shr = (n * r["emp_p35"] + SHRINK_K * ft) / (n + SHRINK_K)
            v = min(shr, r["emp_p35"])                       # never slower than the empirical evidence
            std.append(v)
            flag.append(("BLEND_" if n >= blend_from else "FALLBACK_") + fl + ("_EMPCAP" if shr > r["emp_p35"] else ""))
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
                        "base_wt", "race_skip", "code_flag", "class_par_lb", "field_avg_wt", "course_variant_src"]].rename(columns={"date": "r_date"}),
                 left_on="race_id", right_index=True, how="left")
    cap = r["family"].map(CAP_LENGTHS)
    bl = r["beaten_l"]
    r["beaten_l_eff"] = np.where(bl > cap, cap + 0.5 * (bl - cap), bl)
    r["runner_time"] = r["win_time"] + r["beaten_l"] * r["sec_per_length"]
    r["natural_fig"] = (BASE_FIG + (r["std_time"] + r["going_allowance_spf"] * r["dist_f"] - r["win_time"]) * r["lbs_per_sec"]
                        - r["beaten_l_eff"] * r["lbs_per_length"])
    r["weighted_fig"] = r["natural_fig"] + (r["eff_wt"] - r["base_wt"])          # v2: includes WFA
    r["field_avg_fig"] = r["natural_fig"] + (r["weight_lb"] - r["field_avg_wt"])   # user's old style (no WFA)
    # skip reasons per runner
    reason = r["race_skip"].fillna("").astype(object)
    nf = r["place"].isna() | (r["place"] < 1)
    reason = np.where(reason != "", reason,
             np.where(nf, "NOT_FINISHED_" + r["place_raw"].astype(str),
             np.where(r["beaten_l"].isna(), "NO_BEATEN_LENGTHS",
             np.where(r["weight_lb"].isna(), "NO_WEIGHT",
             np.where(r["beaten_l"] > r["family"].map(DROP_LENGTHS), "BEATEN_TOO_FAR", "")))))
    r["skip_reason"] = reason
    keep = r["skip_reason"] == ""
    r.loc[~keep, ["natural_fig", "weighted_fig", "field_avg_fig", "runner_time"]] = np.nan
    r["raw_weighted_fig"] = r["weighted_fig"]
    floored = pd.Series(False, index=r.index)
    for c in ["natural_fig", "weighted_fig", "field_avg_fig"]:
        lo = r[c] < FIG_FLOOR
        floored |= lo
        r.loc[lo, c] = FIG_FLOOR
    r["floored"] = floored
    flags = []
    for row in r[["bl_source", "beaten_l", "std_flag", "ga_level", "code_flag", "going_note", "family", "wfa_lb", "floored", "course_variant_src"]].itertuples(index=False):
        f = []
        if row.beaten_l == row.beaten_l and row.beaten_l > CAP_LENGTHS[row.family]: f.append("TAILED_OFF")
        if row.bl_source == "sum_margins_gap": f.append("BL_GAP")
        elif row.bl_source == "sum_margins": f.append("BL_SUMMED")
        if isinstance(row.std_flag, str) and row.std_flag != "EMPIRICAL": f.append("STD_" + row.std_flag)
        if row.ga_level == "LOW_N": f.append("GA_LOW_N")
        if row.code_flag: f.append(row.code_flag)
        if row.wfa_lb: f.append(f"WFA_{row.wfa_lb:g}")
        if row.floored: f.append("FLOORED")
        if row.course_variant_src == "DATE_RULE": f.append("LAYOUT_BY_DATE")
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
    ap.add_argument("--out", default=str(root / "data" / "speed_v2"))
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
    global N_TIME_SUSPECT
    N_TIME_SUSPECT = int(bad.sum())
    log(f"{int(bad.sum())} races flagged TIME_SUSPECT (winner >{SUSPECT_LB:.0f} lb off class par); pass 2 without them")
    races, st, gd, cpt = run(rn, races, pct=a.pct, min_races=a.min_races)
    # v2: re-check after pass 2 (removing bad races sharpens the going allowances and exposes more bad times)
    bad2, _ = flag_suspect_times(races)
    if int(bad2.sum()):
        races.loc[bad2, "race_skip"] = "TIME_SUSPECT"
        N_TIME_SUSPECT += int(bad2.sum())
        log(f"{int(bad2.sum())} more TIME_SUSPECT after pass 2 (total {N_TIME_SUSPECT}); pass 3")
        races, st, gd, cpt = run(rn, races, pct=a.pct, min_races=a.min_races, iters=8)
        # final clean-up: anything still >40 lb off its class par is skipped without another recompute
        bad3, _ = flag_suspect_times(races)
        races.loc[bad3, "race_skip"] = "TIME_SUSPECT"
        races.loc[bad3, "win_natural"] = np.nan
        N_TIME_SUSPECT += int(bad3.sum())
        log(f"{int(bad3.sum())} more TIME_SUSPECT after pass 3 (final total {N_TIME_SUSPECT})")
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
                "wfa_lb", "eff_wt", "place_raw", "place", "windist_raw", "beaten_l", "bl_source", "beaten_l_eff", "win_time", "runner_time",
                "std_time", "std_flag", "going_allowance_spf", "lbs_per_length", "lbs_per_sec", "class_par_lb",
                "natural_fig", "weighted_fig", "field_avg_wt", "field_avg_fig", "raw_weighted_fig", "flags", "skip_reason"]
    fo = fig[out_cols].rename(columns={"r_date": "date", "class_raw": "class"})
    fo["date"] = pd.to_datetime(fo["date"]).dt.date
    for c in ["natural_fig", "weighted_fig", "field_avg_fig", "raw_weighted_fig", "field_avg_wt"]: fo[c] = fo[c].round(1)
    for c in ["beaten_l_eff", "runner_time", "std_time", "going_allowance_spf", "lbs_per_length", "lbs_per_sec", "class_par_lb"]:
        fo[c] = fo[c].round(3)
    log("writing speed_figures.csv")
    fo.to_csv(out / "speed_figures.csv", index=False)
    pd.DataFrame([dict(distance_f=d, age=a, half_month=i + 1, month=i // 2 + 1, lb=v) for d, t in WFA_FLAT.items()
                  for a, row in t.items() for i, v in enumerate(row)]).to_csv(out / "wfa_scale_flat.csv", index=False)
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
    add("floor", f"runners_floored_at_{FIG_FLOOR:g}", int(fo["flags"].fillna("").str.contains("FLOORED").sum()))
    add("floor", "weighted_below_floor_before_flooring", int((fo["raw_weighted_fig"] < FIG_FLOOR).sum()))
    add("floor", "figures_below_zero_before_flooring", int((fo["raw_weighted_fig"] < 0).sum()))
    add("top", "weighted_above_160", int((fo["weighted_fig"] > 160).sum()))
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
    # best-3 weighted per horse vs max OffR
    for f_ in ["Flat", "Jumps"]:
        x = fo[has & (fam == f_)]
        b3 = x.groupby("horse")["weighted_fig"].apply(lambda s: s.nlargest(3).mean())
        mo = x.groupby("horse")["offr"].max(); nr = x.groupby("horse").size()
        k = (nr >= 3) & mo.notna()
        add("best3_vs_maxOR", f_, round(b3[k].corr(mo[k]), 3), int(k.sum()), "horses with 3+ figures")
    # 2yo vs 3yo+ (Flat, GB class, winners)
    fl = fo[has & (fam == "Flat") & fo["class"].notna() & (fo["place"] == 1)]
    juv = fl["class_group"].str.endswith("|2yo")
    for c in sorted(fl["class"].dropna().unique()):
        a = fl.loc[juv & (fl["class"] == c), "weighted_fig"]; b = fl.loc[~juv & (fl["class"] == c), "weighted_fig"]
        if len(a) >= 20 and len(b) >= 20:
            add("2yo_minus_3yo+_winner_median", f"Class {int(c)}", round(a.median() - b.median(), 1), len(a), f"2yo {a.median():.1f} vs 3yo+ {b.median():.1f}")
    lbl = fo["class_group"].str.split("|").str[1:].str.join("|")
    for g, x in fo[has].groupby(lbl[has]):
        w = x.loc[x["place"] == 1, "weighted_fig"]
        add("by_class_winner_median", g, round(w.median(), 1), int(x["race_id"].nunique()))
        add("by_class_all_median", g, round(x["weighted_fig"].median(), 1), len(x))
    for f_ in ["Flat", "Jumps"]:
        t = fo[has & (fam == f_)].nlargest(20, "weighted_fig")
        for i, r in enumerate(t.itertuples(), 1):
            add(f"top20_{f_}", i, r.weighted_fig, None,
                f"{r.date} {r.course_raw} {r.off_time} {r.distance_raw} {r.going} | {r.horse} age {r.age} pos {r.place_raw} bl {r.beaten_l} wt {r.weight_raw} OR {r.offr} nat {r.natural_fig} | {r.std_flag} | {r.flags}")
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

METHOD_MD = r"""# Speed figures v2 – method (plain words)

Script: `tools\speedfig_v2.py`. Input: `data\rbd_core.csv.gz`. Output: `data\speed_v2\` (v1 in `data\speed\` is untouched).
v2 uses the same method as v1 (see v1 METHOD.md: parsing, class pars, lb per length/second, 35th-percentile standards,
going allowance per meeting) with these changes.

## 1. Rare distances: standards from small samples
- 10+ races: empirical 35th percentile (unchanged).
- 1-9 races: standard = (n × empirical + 3 × fitted) ÷ (n + 3), and it is **never slower than the empirical value** for
  that distance (flag `_EMPCAP` when the cap bites). v1 used the fitted time alone below 4 races, and fits that ran
  too slow gave figures of 170-180.
- The fitted time's course offset is capped at ±3% of the code/surface line, and ±2% when borrowed from another code at
  the same course (e.g. Listowel chases fitted from its hurdles).
- TIME_SUSPECT (winner more than 40 lb off its class par) is now checked three times: after pass 1 and after pass 2
  (each followed by a recompute), then a final clean-up after pass 3.

## 2. Weight-for-age
- **Flat**: BHA Flat WFA scale 2025 (lb), by half-month and distance 5f-2m (over 2m uses 2m). 3yo vs 4yo+, 4yo vs 5yo+
  (9f+ early in the year), 2yo = 2yo-from-3yo row + 3yo row. Source: BHA "2025 Flat WFA Scale Changes" PDF. The table is
  written to `wfa_scale_flat.csv`.
- The BHA 2yo row starts in August; for earlier 2yo races it is extended backwards by +2 lb per half-month.
- **2yo calibration**: with the full BHA 2yo allowance, 2yo figures came out about 9 lb too high against official ratings
  in every month, so 2yos get **65%** of the BHA total (`WFA_2YO_FACTOR`, set to 1.0 for pure BHA).
- **Jumps** (approximate BHA NH scale): 4yo hurdles/bumpers 8 lb in Jan falling to 0 in Dec; 4yo chases 10 lb falling to
  1 lb; 3yo juvenile hurdlers 15 lb in Aug falling to 10 lb in Dec.
- **Weighted figure** = natural + (weight carried + WFA − base weight). WFA is also used for the class pars and standards.

## 3. Course layouts
- **Newmarket**: Rowley Mile vs July Course. RBD names the July Course "Newmarket (July)" until Aug 2026. After that a
  date rule is used (Jun-Aug = July Course, otherwise Rowley), which matches the named data exactly. "Rowley" in the
  going or race name overrides it.
- **Cheltenham**: Cross Country (race name), Old Course (Oct-Nov, Festival days 1-2, or "Old Course" in the going field)
  and New Course (Festival days 3-4, Dec-Feb, Apr). Flag `LAYOUT_BY_DATE` when the date rule is used.
- **Not split** because the data has no clue: Goodwood, Ascot straight vs round mile (only 2-3 races say "Round"),
  Haydock inner/outer (6 races), York and Newcastle straight vs round. The scraped data may support these later.

## 4. Tailed-off horses and floor
- Beaten lengths beyond 15 (Flat) or 20 (jumps) count half (flag TAILED_OFF). v1 used 20 and 30.
- Beaten more than 30 lengths (Flat) or 40 lengths (jumps): no figure (skip_reason BEATEN_TOO_FAR).
- **Floor 45**: any natural, weighted or field-average figure below 45 becomes 45 (flag FLOORED).
  `raw_weighted_fig` keeps the weighted figure before the floor.

## 5. Extra column
- `field_avg_fig` = natural + (weight carried − the race's average weight), the old style (no WFA). `field_avg_wt` is
  shown alongside it.
"""

if __name__ == "__main__":
    main()
