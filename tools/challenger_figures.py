#!/usr/bin/env python3
"""FurlongIQ challenger: independent standards/results ratings and split-shape indices.

READ ONLY: data/speed_v4/speed_figures.csv, distance_corrections.csv, sectionals.sqlite.
WRITE ONLY: data/challenger_v1/. No modifications to production files/databases.
This is a research challenger, NOT a production speed-figure replacement.
"""
from __future__ import annotations
import argparse
import json
import math
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

FURLONG = 220.0
BASE = 100.0


def numeric(s):
    return pd.to_numeric(s, errors="coerce")


def norm(s):
    return (s.fillna("").astype(str).str.lower().str.replace(r"[^a-z0-9]+", "", regex=True))


def robust_q(s, q=.35):
    a = numeric(s).dropna().to_numpy(float)
    if len(a) == 0:
        return np.nan
    if len(a) >= 8:
        q1, q3 = np.quantile(a, [.25, .75]); iqr = q3 - q1
        a = a[(a >= q1 - 1.5 * iqr) & (a <= q3 + 1.5 * iqr)]
    return float(np.quantile(a, q)) if len(a) else np.nan


def robust_med(s):
    a = numeric(s).dropna().to_numpy(float)
    if len(a) == 0:
        return np.nan
    med = np.median(a)
    if len(a) >= 5:
        mad = 1.4826 * np.median(np.abs(a - med))
        a = a[np.abs(a - med) <= max(.15, 3 * mad)]
    return float(np.median(a)) if len(a) else np.nan


def choose_clock(r, tol=0.5):
    """No class-par tie breaking: ambiguous clocks are quarantined, not silently guessed."""
    inputs = []
    for key in ("win_time_official", "rtv_results_time", "sect_time"):
        try:
            x = float(r.get(key))
        except (ValueError, TypeError):
            continue
        if math.isfinite(x) and 15 < x < 1800:
            inputs.append((key, x))
    if not inputs:
        return np.nan, "NO_CLOCK"
    if len(inputs) == 1:
        return inputs[0][1], "SINGLE_" + inputs[0][0]
    candidates = []
    for i in range(len(inputs)):
        for j in range(i + 1, len(inputs)):
            a, b = inputs[i], inputs[j]
            if abs(a[1] - b[1]) <= tol:
                candidates.append((a, b))
    if candidates:
        # A verified RTV results + sectionals pair takes precedence.
        pair = next((p for p in candidates if {p[0][0], p[1][0]} == {"rtv_results_time", "sect_time"}), candidates[0])
        preferred = next((v for k, v in pair if k == "rtv_results_time"), pair[0][1])
        return preferred, "AGREED_PAIR"
    return np.nan, "DISPUTED_CLOCK"


def load_inputs(fig_path: Path, correction_path: Path):
    if not fig_path.is_file():
        raise FileNotFoundError(f"Missing {fig_path}")
    F = pd.read_csv(fig_path, low_memory=False)
    # Canonical speedfig_v3/v4 CSVs do NOT export base_wt. It is a known
    # method constant in speedfig_v3.py, so reconstruct it from race code.
    # Keep any explicit base_wt where supplied (e.g. earlier research exports).
    base_weight_by_code = {"Flat": 126.0, "Hurdle": 154.0, "Chase": 154.0, "NHF": 154.0}
    if "code" in F.columns:
        derived_base = F["code"].astype(str).str.strip().map(base_weight_by_code)
        if "base_wt" not in F.columns:
            F["base_wt"] = derived_base
        else:
            F["base_wt"] = numeric(F["base_wt"]).fillna(derived_base)
        unknown = F.loc[F["base_wt"].isna(), "code"].value_counts().head(10).to_dict()
        if unknown:
            raise ValueError("Cannot determine base weight for race codes: " + str(unknown))
    needed = {"race_id", "horse", "place", "date", "course", "surface", "code", "dist_f", "win_time", "lbs_per_sec", "beaten_l_eff", "lbs_per_length", "eff_wt", "base_wt", "going", "class_group", "skip_reason", "weighted_fig", "off_time"}
    missing = needed - set(F.columns)
    if missing:
        raise ValueError("Missing required baseline factual columns: " + ", ".join(sorted(missing)))
    if not correction_path.is_file():
        raise FileNotFoundError(f"Missing {correction_path}; exact distance + independent clock reconciliation required")
    C = pd.read_csv(correction_path, low_memory=False)
    if "race_id" not in C.columns:
        raise ValueError("distance_corrections.csv is missing race_id")
    C = C.drop_duplicates("race_id", keep="first")
    for n in ["exact_yards", "base_yards", "rtv_race_id", "win_time_official", "rtv_results_time", "sect_time"]:
        if n not in C.columns:
            C[n] = np.nan
    F["date"] = pd.to_datetime(F["date"], errors="coerce")
    F["place"] = numeric(F["place"])
    F["horse_key"] = norm(F["horse"])
    for n in ["dist_f", "win_time", "lbs_per_sec", "beaten_l_eff", "lbs_per_length", "eff_wt", "base_wt"]:
        F[n] = numeric(F[n])
    F = F.drop_duplicates(["race_id", "horse_key"], keep="first")
    R = F.sort_values(["race_id", "place"]).drop_duplicates("race_id", keep="first")
    R = R[["race_id", "date", "course", "surface", "code", "dist_f", "going", "class_group", "win_time", "lbs_per_sec", "base_wt", "eff_wt", "horse_key", "place"]].rename(columns={"horse_key":"winner_key", "eff_wt":"win_eff_wt", "place":"winner_place", "win_time":"v4_win_time"})
    R = R.merge(C[["race_id", "exact_yards", "base_yards", "rtv_race_id", "win_time_official", "rtv_results_time", "sect_time"]], on="race_id", how="left", validate="one_to_one")
    R["actual_clock"], R["clock_qc"] = zip(*(choose_clock(r) for r in R.to_dict("records")))
    R["base_yards"] = numeric(R["base_yards"]).where(numeric(R["base_yards"]) > 0, R["dist_f"] * FURLONG)
    R["exact_yards"] = numeric(R["exact_yards"]).where(numeric(R["exact_yards"]) > 0, R["base_yards"])
    R["rtv_race_id"] = numeric(R["rtv_race_id"])
    R["distance_qc"] = np.where(R["rtv_race_id"].notna(), "HAS_RTV_ID", "NO_MATCHED_RTV_ID")
    R["trip_f"] = R["base_yards"] / FURLONG
    # A course may have distinct straight/round layouts already in source 'course'. Never merge them.
    R["key"] = (R["course"].astype(str) + "|" + R["surface"].astype(str) + "|" +
                R["code"].astype(str) + "|" + R["dist_f"].round(2).astype(str))
    R["family"] = np.where(R["code"].eq("Flat"), np.where(R["surface"].eq("AW"), "AW", "Flat"), R["code"])
    R["meeting"] = R["date"].dt.strftime("%Y-%m-%d") + "|" + R["course"].astype(str) + "|" + R["surface"].astype(str)
    R["clock_base"] = R["actual_clock"] * R["base_yards"] / R["exact_yards"]
    R["base_weight_time"] = R["clock_base"] - (numeric(R["win_eff_wt"]) - numeric(R["base_wt"])) / numeric(R["lbs_per_sec"])
    R["clock_valid"] = (R["winner_place"].eq(1) & R["actual_clock"].notna() & R["dist_f"].between(4, 40) &
                        R["base_weight_time"].gt(0) & R["lbs_per_sec"].gt(0) & R["date"].notna() &
                        ((R["exact_yards"] - R["base_yards"]).abs() <= 120) &
                        (R["clock_base"] / R["dist_f"]).between(9.5, 27.0))
    return F, R


def fit_standard_model(R, cutoff, n_min=12):
    T = R[R["clock_valid"] & (R["date"] < cutoff)].copy()
    if len(T) < 50:
        raise ValueError(f"Only {len(T)} clean training races before {cutoff.date()}; need >=50.")
    # The 35th percentile is an independent empirical reference, not copied from v4.
    stats = T.groupby(["key", "course", "code", "surface", "dist_f"], dropna=False).agg(
        n=("clock_base", "size"), empirical=("base_weight_time", robust_q)).reset_index()
    fit = {}
    for (code, surface), g in stats.groupby(["code", "surface"]):
        good = g[(g["n"] >= 5) & g["empirical"].gt(0) & g["dist_f"].gt(0)]
        if good["dist_f"].nunique() >= 3:
            b, a = np.polyfit(np.log(good["dist_f"]), np.log(good["empirical"]), 1, w=np.sqrt(good["n"].clip(upper=100)))
            fit[(code, surface)] = (float(a), float(b))
    fallback_rate = T.groupby(["code", "surface"])["base_weight_time"].median() / T.groupby(["code", "surface"])["dist_f"].median()
    fallback_all = float((T["base_weight_time"] / T["dist_f"]).median())
    rows = []
    for p in stats.to_dict("records"):
        a_b = fit.get((p["code"], p["surface"]))
        global_fit = math.exp(a_b[0] + a_b[1]*math.log(p["dist_f"])) if a_b else float(fallback_rate.get((p["code"], p["surface"]), fallback_all) * p["dist_f"])
        course_group = stats[(stats["course"] == p["course"]) & (stats["code"] == p["code"]) & (stats["surface"] == p["surface"]) & (stats["n"] >= n_min)]
        if len(course_group) >= 2 and a_b:
            pred = np.exp(a_b[0] + a_b[1]*np.log(course_group["dist_f"]))
            off = float(np.clip(np.median(np.log(course_group["empirical"] / pred)), -0.04, 0.04))
            global_fit *= math.exp(off)
        n = p["n"]
        shrink = n / (n + 15.0)
        std = float(shrink*p["empirical"] + (1-shrink)*global_fit) if n < n_min else float(p["empirical"])
        rows.append({**p, "std_base_s":std, "model_fit_s":global_fit, "tier":"EMPIRICAL" if n>=n_min else "SHRUNK"})
    standards = pd.DataFrame(rows)
    global_fallback = (T.groupby(["code", "surface", "dist_f"])["base_weight_time"]
                       .agg(robust_q).reset_index(name="std_base_s"))
    # Estimate historic class and going effects using training data only, iterating.
    lookup = standards.set_index("key")["std_base_s"]
    T["std"] = T["key"].map(lookup)
    T["resid_spf"] = (T["base_weight_time"] - T["std"]) / T["dist_f"]
    class_med = T.groupby("class_group")["resid_spf"].agg(["median", "count"])
    class_med["shrunken"] = class_med["median"] * class_med["count"]/(class_med["count"]+50)
    T["class_sec_per_f"] = T["class_group"].map(class_med["shrunken"]).fillna(0)
    T["resid_going"] = T["resid_spf"] - T["class_sec_per_f"]
    # Meeting medians serve only training and holdout meeting offset estimates, not future feature labels.
    G = T.groupby(["surface", "code", "going"], dropna=False)["resid_going"].agg(["median", "count"])
    G["prior"] = G["median"] * G["count"]/(G["count"]+20)
    T["prior"] = [G["prior"].get((s,c,g), 0.) for s,c,g in zip(T["surface"], T["code"], T["going"])]
    # Relearn standards once after class/going normalisation; avoid race-specific or future target values.
    T["prior"] = numeric(T["prior"]).fillna(0)
    T["neutral"] = T["base_weight_time"] - (T["prior"] + T["class_sec_per_f"]) * T["dist_f"]
    revised = T.groupby("key")["neutral"].agg(robust_q)
    standards["neutral_empirical"] = standards["key"].map(revised)
    standards["std_base_s"] = np.where(standards["n"] >= n_min,
        standards["neutral_empirical"],
        (standards["n"]*standards["neutral_empirical"] + 15 * standards["model_fit_s"]) / (standards["n"] + 15))
    return standards, class_med, G, global_fallback, T


def score_results(F, R, standards, class_med, G, fallback, train_cutoff):
    R = R.copy()
    s_map = standards.set_index("key")
    R["std_base_s"] = R["key"].map(s_map["std_base_s"])
    R["std_n"] = R["key"].map(s_map["n"])
    R["std_tier"] = R["key"].map(s_map["tier"])
    R["std_base_s"] = R["std_base_s"].fillna(pd.Series([
        fallback.set_index(["code", "surface", "dist_f"])["std_base_s"].get((c,s,d), np.nan)
        for c,s,d in zip(R["code"],R["surface"],R["dist_f"])], index=R.index))
    R["std_tier"] = R["std_tier"].fillna("FALLBACK_CODE_TRIP")
    # Last-resort slope derives from historical training calibration only.
    global_train_spf = float((fallback["std_base_s"] / fallback["dist_f"]).median())
    R["std_base_s"] = R["std_base_s"].fillna(R["dist_f"] * global_train_spf)
    R["std_tier"] = np.where(R["key"].isin(s_map.index), R["std_tier"], "FALLBACK")
    R["std_actual_s"] = R["std_base_s"] * R["exact_yards"] / R["base_yards"]
    R["class_prior_spf"] = R["class_group"].map(class_med["shrunken"]).fillna(0)
    R["going_prior_spf"] = [G["prior"].get((s,c,g), 0.0) for s,c,g in zip(R["surface"], R["code"], R["going"])]
    R["going_prior_spf"] = numeric(R["going_prior_spf"]).fillna(0)
    R["going_resid_spf"] = ((R["clock_base"] - R["std_base_s"] - R["class_prior_spf"]*R["dist_f"] -
                             (R["win_eff_wt"] - R["base_wt"]) / R["lbs_per_sec"]) / R["dist_f"])
    # Leave-one-out meeting allowance: a target race cannot adjust its own rating.
    d = R[R["clock_valid"]].copy()
    # Only observations from the training period contribute to historic going model;
    # for a held-out meeting, same-day OTHER race results are post-race context, not pre-race prediction.
    d["clean_resid"] = (d["going_resid_spf"] - d["going_prior_spf"]).clip(-2.5, 2.5)
    valid = d["clean_resid"].notna()
    sums = d["clean_resid"].where(valid, 0).groupby(d["meeting"]).transform("sum")
    counts = valid.astype(int).groupby(d["meeting"]).transform("sum")
    d["loo_n"] = counts - valid.astype(int)
    d["loo_offset"] = (sums - d["clean_resid"].where(valid, 0)) / (d["loo_n"] + 4)
    # For racing results this is valid post-race, since other races on the card are known;
    # not valid as a pre-race prediction input.
    R["meeting_offset_spf"] = R["race_id"].map(d.set_index("race_id")["loo_offset"]).fillna(0).clip(-1.5, 1.5)
    R["going_spf"] = R["going_prior_spf"] + R["meeting_offset_spf"]
    jcols = ["race_id", "actual_clock", "clock_qc", "clock_valid", "exact_yards", "std_actual_s", "std_base_s", "std_n", "std_tier", "going_spf", "going_prior_spf", "meeting_offset_spf", "class_prior_spf", "rtv_race_id"]
    F = F.merge(R[jcols], on="race_id", how="left", validate="many_to_one")
    # Historical class variation is NOT added to runner ratings; class only helps estimate going and standards.
    F["challenger_raw_fig"] = (BASE + (F["std_actual_s"] + F["going_spf"]*(F["exact_yards"]/FURLONG) - F["actual_clock"])*F["lbs_per_sec"]
                               - F["beaten_l_eff"]*F["lbs_per_length"])
    F["challenger_fig"] = F["challenger_raw_fig"] + (F["eff_wt"] - F["base_wt"])
    F.loc[~F["clock_valid"].fillna(False) | F["skip_reason"].fillna("").ne(""), ["challenger_raw_fig", "challenger_fig"]] = np.nan
    F["fig_delta"] = F["challenger_fig"] - numeric(F["weighted_fig"])
    F["challenger_qc"] = np.select(
        [~F["clock_valid"].fillna(False), F["clock_qc"].astype(str).str.startswith("SINGLE_"),
         F["std_tier"].eq("FALLBACK"), F["std_tier"].eq("SHRUNK")],
        ["BAD_RACE_INPUT", "SINGLE_CLOCK", "STANDARD_FALLBACK", "STANDARD_SMALL_SAMPLE"],default="OK")
    F["evaluation_period"] = np.where(F["date"] < train_cutoff, "TRAIN_IN_SAMPLE", "HELD_OUT")
    # Explicit: not using baseline result figure for rating, but uses v4's parsed distances,
    # runner margins and WFA/weight conversion. This is a different calibration, not raw-data independence.
    return F, R


def sectional_split_frames(sqlite_path, R, train_cutoff, max_races=None):
    if not sqlite_path.is_file():
        return pd.DataFrame(), pd.DataFrame(), {"status":"NO_SECTIONALS_SQLITE"}
    conn = sqlite3.connect(f"file:{sqlite_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        # Restrict to races that were reliably joined to the result sample.
        id_series = numeric(R["rtv_race_id"]).dropna().astype(int)
        unique_ids = id_series.value_counts()
        # One-to-many accidental race joins are not safe for sectional scoring.
        IDs = set(unique_ids[unique_ids == 1].index)
        if not IDs:
            return pd.DataFrame(), pd.DataFrame(), {"status":"NO_RTV_RACE_IDS"}
        races = pd.read_sql("SELECT rtv_race_id, race_date, distance_yards FROM rtv_races", conn)
        races = races[races["rtv_race_id"].isin(IDs)]
        # A bounded pilot is intentional: it keeps large multi-year SQLite scans manageable.
        if max_races is not None and len(races) > max_races:
            ordered = races.sort_values(["race_date", "rtv_race_id"])
            older = ordered[pd.to_datetime(ordered["race_date"]) < train_cutoff]
            newer = ordered[pd.to_datetime(ordered["race_date"]) >= train_cutoff]
            n_old = min(len(older), int(max_races*0.65))
            n_new = min(len(newer), max_races-n_old)
            if n_old+n_new < max_races:
                n_old = min(len(older), max_races-n_new)
            races = pd.concat([older.tail(n_old), newer.tail(n_new)]).drop_duplicates("rtv_race_id")
            IDs = set(races["rtv_race_id"].astype(int))
        if races.empty:
            return pd.DataFrame(), pd.DataFrame(), {"status":"NO_MATCHED_RTV_RACES"}
        # Restrict SQL reads to matched RTV races. SQLite parameter lists are batched.
        U_parts, S_parts = [], []
        ordered_ids = sorted(IDs)
        for offset in range(0, len(ordered_ids), 800):
            batch = ordered_ids[offset:offset+800]
            ph = ",".join("?" for _ in batch)
            U_parts.append(pd.read_sql(
                f"SELECT rtv_race_id,rtv_runner_id,horse_name,finish_position,total_time_s "
                f"FROM rtv_runners WHERE rtv_race_id IN ({ph})", conn, params=batch))
            S_parts.append(pd.read_sql(
                f"SELECT rtv_race_id,rtv_runner_id,sector_number,sector_time "
                f"FROM rtv_sectionals WHERE rtv_race_id IN ({ph})", conn, params=batch))
        U = pd.concat(U_parts,ignore_index=True)
        S = pd.concat(S_parts,ignore_index=True)
    finally:
        conn.close()
    if U.empty or S.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status":"NO_MATCHED_SECTION_ROWS"}
    U["horse_key"] = norm(U["horse_name"])
    racecols = ["rtv_race_id", "race_id", "date", "course", "code", "surface", "dist_f", "actual_clock", "clock_valid"]
    racekey = R[racecols].dropna(subset=["rtv_race_id"]).drop_duplicates("rtv_race_id")
    racekey["rtv_race_id"] = racekey["rtv_race_id"].astype(int)
    U = U.merge(racekey, on="rtv_race_id", how="inner", validate="many_to_one")
    S = S.merge(U, on=["rtv_race_id", "rtv_runner_id"], how="inner", validate="many_to_one")
    S = S.sort_values(["rtv_race_id", "rtv_runner_id", "sector_number"])
    keys = ["rtv_race_id", "rtv_runner_id"]
    g = S.groupby(keys, sort=False)
    S["nsec"] = g["sector_number"].transform("size")
    S["minsec"] = g["sector_number"].transform("min")
    S["maxsec"] = g["sector_number"].transform("max")
    S["total_sec"] = g["sector_time"].transform("sum")
    S["first_len"] = S["dist_f"] * FURLONG - (S["nsec"]-1)*FURLONG
    # RTV exact length is separately available; use it, not rounded trip.
    rtv_d = races.set_index("rtv_race_id")["distance_yards"]
    S["dist_y"] = numeric(S["rtv_race_id"].map(rtv_d))
    S["first_len"] = S["dist_y"] - (S["nsec"]-1)*FURLONG
    S["seg_y"] = np.where(S["sector_number"].eq(0), S["first_len"], FURLONG)
    S["kend"] = S["nsec"] - 1 - S["sector_number"]
    S["sector_time"] = numeric(S["sector_time"])
    S["total_time_s"] = numeric(S["total_time_s"])
    S["good"] = (S["clock_valid"] & S["nsec"].ge(3) & S["minsec"].eq(0) &
                 S["maxsec"].eq(S["nsec"]-1) & S["first_len"].between(20,460) &
                 S["sector_time"].gt(0) & (S["seg_y"]/S["sector_time"]).between(8,22) &
                 S["total_sec"].gt(0) &
                 (S["total_sec"]-S["total_time_s"].fillna(S["total_sec"])).abs().le(1.0))
    # All sectors must be valid; don't rate only the good portions of an incomplete race.
    S["good"] = S.groupby(keys)["good"].transform("all")
    S = S[S["good"]].copy()
    if S.empty:
        return pd.DataFrame(), pd.DataFrame(), {"status":"NO_CLEAN_SECTIONALS"}
    S["baseline_seg_s"] = S["total_sec"] * S["seg_y"] / S["dist_y"]
    S["shape_ratio"] = S["sector_time"] / S["baseline_seg_s"]
    S["trip"] = (S["dist_y"] / FURLONG).round().astype(int)
    S["family"] = np.where(S["code"].eq("Flat"), np.where(S["surface"].eq("AW"),"AW","Flat"),S["code"])
    train = S[(S["date"] < train_cutoff) & numeric(S["finish_position"]).eq(1)].copy()
    if len(train) < 30:
        return pd.DataFrame(), pd.DataFrame(), {"status":"TOO_FEW_TRAINING_SECTIONS", "training_winner_segments":int(len(train))}
    # A sectional 'par' is a *shape ratio*, not the winner's absolute time. This
    # means slow-run races do not automatically create slow course standards.
    exact = train.groupby(["course", "family", "trip", "kend"])["shape_ratio"].agg(["median", "count"])
    pooled = train.groupby(["family", "trip", "kend"])["shape_ratio"].agg(["median", "count"])
    broad = train.groupby(["family", "kend"])["shape_ratio"].agg(["median", "count"])
    def par(row):
        k = (row.course, row.family, row.trip, row.kend)
        p = exact.loc[k] if k in exact.index else None
        k2 = (row.family, row.trip, row.kend)
        q = pooled.loc[k2] if k2 in pooled.index else None
        k3 = (row.family, row.kend)
        b = broad.loc[k3] if k3 in broad.index else None
        pri = float(b["median"]) if b is not None else 1.0
        if q is not None:
            pri = (float(q["median"])*float(q["count"]) + 30*pri)/(float(q["count"])+30)
        if p is not None:
            n = float(p["count"])
            return (float(p["median"])*n + 20*pri)/(n+20), int(n), "COURSE" if n>=20 else "SHRUNK_COURSE"
        return pri, 0, "POOLED"
    pars = S[["course","family","trip","kend"]].drop_duplicates()
    calc = [par(r) for r in pars.itertuples(index=False)]
    pars["shape_par"] = [x[0] for x in calc]
    pars["par_n"] = [x[1] for x in calc]
    pars["par_tier"] = [x[2] for x in calc]
    S = S.merge(pars, on=["course","family","trip","kend"], how="left", validate="many_to_one")
    S["par_unscaled_s"] = S["baseline_seg_s"] * S["shape_par"]
    normer = S.groupby(keys)["par_unscaled_s"].transform("sum")
    S["expected_seg_s"] = S["par_unscaled_s"] * S["total_sec"] / normer
    S["section_delta_s"] = S["expected_seg_s"] - S["sector_time"]
    S["section_index"] = (100 * S["expected_seg_s"] / S["sector_time"]).round(2)
    S["section_speed_yps"] = S["seg_y"] / S["sector_time"]
    S["section_delta_per_f"] = S["section_delta_s"] / (S["seg_y"] / FURLONG)
    # Summary uses fully observed runners and excludes the section as an independent total figure.
    S["is_late"] = S["kend"].lt(np.where(S["family"].isin(["Flat","AW"]), 2, 3))
    summary = S.groupby(keys, sort=False).agg(rtv_race_id=("rtv_race_id","first"), race_id=("race_id","first"),
        horse_key=("horse_key","first"), horse_name=("horse_name","first"), date=("date","first"),
        finish_position=("finish_position","first"), secs=("sector_number","size"),
        min_par_n=("par_n","min"), late_index=("section_index",lambda x: np.nan),
        total_s=("total_sec","first"))
    # Calculate distance-weighted speed ratios for last 2f (Flat) or 3f (Jumps).
    for lab, sub in [("late",S[S["is_late"]]), ("early",S[~S["is_late"]])]:
        ag = sub.groupby(keys).agg(exp_s=("expected_seg_s","sum"), obs_s=("sector_time","sum"))
        summary[lab+"_index"] = 100 * ag["exp_s"]/ag["obs_s"]
    # Independent sectional clock: absolute race speed can be scored directly from
    # the sum of electronic split times, without estimated beaten-length margins.
    # Verify the sectional winner clock against the adjudicated result first.
    winners = S[numeric(S["finish_position"]).eq(1)].drop_duplicates("rtv_race_id")
    winner_clock = winners.set_index("rtv_race_id")["total_sec"]
    sec_clock_diff = R.set_index("rtv_race_id")["actual_clock"] - winner_clock
    summary["winner_clock_abs_diff_s"] = summary["rtv_race_id"].map(sec_clock_diff.abs())
    summary["clock_matched"] = summary["winner_clock_abs_diff_s"].le(1.0)
    summary["sectional_clock_status"] = np.where(summary["winner_clock_abs_diff_s"].isna(), "WINNER_CLOCK_UNVERIFIED",
                                         np.where(summary["clock_matched"], "MATCHED", "WINNER_CLOCK_MISMATCH"))
    summary["sectional_style"] = np.select(
        [(summary["late_index"] - summary["early_index"]) >= 4,
         (summary["early_index"] - summary["late_index"]) >= 4,
         (summary["late_index"] - summary["early_index"]).abs() <= 2],
        ["STRONG_FINISH_RELATIVE_TO_PAR", "FRONT_LOADED_RELATIVE_TO_PAR", "EVEN_RELATIVE_TO_PAR"],
        default="MIXED_RELATIVE_TO_PAR")
    summary.loc[summary["min_par_n"].fillna(0).lt(5), "sectional_style"] = "LOW_COURSE_PAR_SAMPLE"
    S["sectional_period"] = np.where(S["date"] < train_cutoff,"TRAIN_IN_SAMPLE", "HELD_OUT")
    return S, summary.reset_index(drop=True), {"status":"OK", "section_rows":int(len(S)), "par_rows":int(len(pars)),
                                     "training_winner_segments":int(len(train)),"rated_runners":int(len(summary)),
                                     "runner_rows_with_verified_winner_clock":int(summary["clock_matched"].sum()),
                                     "unverified_or_mismatched_runners":int((~summary["clock_matched"]).sum()),
                                     "pilot_limited": bool(max_races is not None and max_races < int(R["rtv_race_id"].notna().sum()))}


def prospective_benchmark(F, cutoff):
    """Compare pre-race ratings for same eligible runners/races; no future horse runs."""
    d = F.copy()
    if "horse_id" not in d.columns:
        d["horse_id"] = d["horse_key"]
    d = d[d["horse_id"].notna() & d["date"].notna() & d["place"].notna()].copy()
    d["group"] = d["horse_id"].astype(str) + "|" + np.where(d["code"].eq("Flat"),"Flat", "Jumps")
    d = d.sort_values(["date","off_time","race_id","group"], kind="mergesort")
    for src, dest in [("weighted_fig", "baseline_pre"), ("challenger_fig", "challenger_pre")]:
        d[src] = numeric(d[src])
        def last3(g):
            vals = g.to_numpy(float)
            out = np.full(len(vals), np.nan)
            seen = []
            for i,v in enumerate(vals):
                prior = np.array(seen[-12:], dtype=float)
                prior = prior[np.isfinite(prior)]
                if len(prior) >= 2:
                    out[i] = float(np.sort(prior)[-3:].mean())
                seen.append(v)
            return pd.Series(out, index=g.index)
        d[dest] = d.groupby("group", group_keys=False)[src].apply(last3)
    te = d[d["date"] >= cutoff].copy()
    elig = te["baseline_pre"].notna() & te["challenger_pre"].notna()
    te = te[elig].copy()
    # Require all finishers in the race to have both pre-race figures; at least 3 runners.
    counts = te.groupby("race_id").agg(n=("place","size"), winners=("place",lambda x:int((x==1).sum())))
    candidates = counts[(counts["n"]>=3) & (counts["winners"]>=1)].index
    te = te[te["race_id"].isin(candidates)]
    # Warn that baseline V4 standards may have been fitted with data from the holdout.
    report = {"n_comparable_races": int(te["race_id"].nunique()), "warning":"Baseline v4 may contain future-trained standards; rerun baseline with train cutoff for a fully fair comparison."}
    if te.empty:
        return pd.DataFrame(), report
    results=[]
    for col, label in [("baseline_pre","baseline_v4"),("challenger_pre","challenger_v1")]:
        chosen=te.sort_values(["race_id",col],ascending=[True,False]).drop_duplicates("race_id")
        report[label] = {"races":int(len(chosen)), "top_wins":int(chosen["place"].eq(1).sum()),"top_win_rate":round(float(chosen["place"].eq(1).mean()),5)}
        results.append(chosen[["race_id","horse","place",col]].rename(columns={"horse":"top_horse","place":"top_place",col:"pre_rating"}).assign(model=label))
    return pd.concat(results,ignore_index=True), report


def run(args):
    root=Path(args.root).resolve()
    fig=root/"data/speed_v4/speed_figures.csv"
    correction=root/"data/speed_v4/distance_corrections.csv"
    out = Path(args.out).resolve() if args.out else root/"data/challenger_v1"
    F,R=load_inputs(fig,correction)
    good_dates=R.loc[R["clock_valid"], "date"].sort_values().dropna().drop_duplicates()
    if args.train_end:
        cutoff=pd.Timestamp(args.train_end)+pd.Timedelta(days=1)
    elif len(good_dates)>=10:
        cutoff=good_dates.iloc[int(len(good_dates)*.80)]
    else:
        raise ValueError("Need >=10 usable race dates to choose chronological holdout")
    if cutoff >= good_dates.max():
        raise ValueError("Training cutoff must leave at least one later evaluation date")
    st,classes,go,fb,train=fit_standard_model(R,cutoff)
    F,R=score_results(F,R,st,classes,go,fb,cutoff)
    splits,secsummary,secdiag=sectional_split_frames(root/"data/sectionals.sqlite",R,cutoff,
            getattr(args,"max_rtv_races",None))
    if len(secsummary):
        F=F.merge(secsummary[["race_id","horse_key","late_index","early_index","min_par_n","total_s",
                                  "sectional_clock_status", "sectional_style"]],on=["race_id","horse_key"],how="left",validate="one_to_one")
        F["sectional_clock_fig"] = (BASE + (F["std_actual_s"] + F["going_spf"]*(F["exact_yards"]/FURLONG)
                                       - F["total_s"])*F["lbs_per_sec"] + (F["eff_wt"]-F["base_wt"]))
        F.loc[F["sectional_clock_status"].ne("MATCHED") | F["skip_reason"].fillna("").ne("") |
              ~F["clock_valid"].fillna(False), "sectional_clock_fig"] = np.nan
        F["sectional_clock_delta"] = F["sectional_clock_fig"]-F["challenger_fig"]
    benchmark,eval_report=prospective_benchmark(F,cutoff)
    # Every write stays in the isolated challenger folder.
    out.mkdir(parents=True,exist_ok=True)
    F.to_csv(out/"result_speed_figures.csv.gz",index=False)
    st.to_csv(out/"standard_times.csv",index=False)
    R.to_csv(out/"race_clock_and_going_audit.csv.gz",index=False)
    classes.to_csv(out/"class_calibration.csv")
    go.to_csv(out/"going_priors.csv")
    if len(splits):
        splits[[x for x in ("race_id","rtv_race_id","horse_name","horse_key","date","sector_number","kend","seg_y","sector_time","shape_ratio","shape_par","par_n","par_tier","expected_seg_s","section_delta_s","section_delta_per_f","section_index","section_speed_yps","sectional_period") if x in splits.columns]].to_csv(out/"sectional_splits.csv.gz",index=False)
        secsummary.to_csv(out/"sectional_runner_summary.csv.gz",index=False)
    if len(benchmark):
        benchmark.to_csv(out/"head_to_head_picks.csv",index=False)
    # Side-by-side audits retain every possible comparison, including unknown cases.
    v4_race = (F.sort_values(["race_id","place"]).drop_duplicates("race_id")
               [[c for c in ("race_id", "std_time", "going_allowance_spf", "weighted_fig", "challenger_fig") if c in F.columns]])
    std_review = R[["race_id","date","course","code","surface","dist_f","std_base_s","std_actual_s",
                    "std_n","std_tier","going_spf","clock_qc","clock_valid", "distance_qc"]].merge(
                        v4_race.drop(columns=["challenger_fig"],errors="ignore"),on="race_id",how="left")
    if "std_time" in std_review:
        std_review["standard_diff_s"] = std_review["std_actual_s"] - numeric(std_review["std_time"])
    if "going_allowance_spf" in std_review:
        std_review["going_diff_spf"] = std_review["going_spf"] - numeric(std_review["going_allowance_spf"])
    std_review.to_csv(out/"result_standard_comparison.csv.gz",index=False)
    report={"version":"challenger_v1", "training_before":cutoff.strftime("%Y-%m-%d"),"n_raw_runner_rows":len(F),
            "n_races":int(len(R)),"valid_race_clocks":int(R["clock_valid"].sum()),"disputed_clocks":int((R["clock_qc"]=="DISPUTED_CLOCK").sum()),
            "holdout_races":int(R["date"].ge(cutoff).sum()), "n_standard_groups":len(st),"sectionals":secdiag,
            "benchmark":eval_report,
            "figure_delta": {"n_comparable":int(F["fig_delta"].notna().sum()),
               "median_delta_lb":float(F["fig_delta"].median()) if F["fig_delta"].notna().any() else None,
               "pct_abs_ge_10lb":float(F["fig_delta"].abs().ge(10).mean()) if F["fig_delta"].notna().any() else None},
            "conditions":["Alternative standards/going recalibrated from same underlying races",
              "Input runner parsing/weights/clock candidates originated in v4 outputs, not independently scraped raw sources",
              "Sectional split index is a pace-shape index; it is NOT a second absolute race speed figure",
              "No automatic sectional uplift is supplied until a held-out next-performance study validates one",
              "Baseline v4 trained on all history may contaminate historical head-to-head benchmark"]}
    (out/"audit.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    print(json.dumps(report,indent=2,default=str))
    return report


def main():
    p=argparse.ArgumentParser(description="Non-destructive speed figure and sectional challenger")
    p.add_argument("--root",default=str(Path(__file__).resolve().parents[1]))
    p.add_argument("--out",default=None)
    p.add_argument("--train-end",help="Last date (inclusive) allowed for calibration, e.g. 2025-12-31")
    p.add_argument("--max-rtv-races",type=int,default=None,help="Pilot: restrict sectional timing scan to newest N matched RTV races")
    run(p.parse_args())


if __name__=="__main__":
    main()
