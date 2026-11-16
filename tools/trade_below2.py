#!/usr/bin/env python3
r"""
Pre-off models for in-running Betfair events, trained on RBD prices + v3 speed figures.

Decision-time prices (known before the off; BSP is NOT used as a feature in these):
  5m  <- RBD column '5 mins'
  2m  <- RBD column '2 mins'
  1m  <- RBD column '1 min'
BSP model is a reference only (BSP is not known when you bet at 5m/2m/1m).

Targets
  below2  ip_min <= 2.0
  lay18   ip_min <= 1.8
  lay15   ip_min <= 1.5
  lay12   ip_min <= 1.2
  dob     ip_min <= snapshot_price / 2     (needs the pre-off price to define the label)
  dob2    ip_min <= snapshot_price / 4

For each snapshot and target, three versions are trained on the same runners:
  form   speed figures + race conditions only (no odds)
  price  log(price) + 1/price only
  full   pre-off price + form

Usage (from the Speeds folder):
    python tools\trade_below2.py
    python tools\trade_below2.py --limit 800
    python tools\trade_below2.py --score-cards
"""
from __future__ import annotations

import argparse, json, math, re, sqlite3, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Exact RBD parquet column names, mapped to our compact CSV.
RBD_PRICE_COLS = {
    "p15": "15 Mins",
    "p10": "10 mins",
    "p5": "5 mins",
    "p3": "3 mins",
    "p2": "2 mins",
    "p1": "1 min",
    "post": "Post Time",
    "bsp": "BSP",
    "ip_min": "Min Price",
}
SNAPSHOTS = [
    ("5m", "p5", "5 minutes before the off", False),
    ("2m", "p2", "2 minutes before the off", False),
    ("1m", "p1", "1 minute before the off", False),
    ("bsp", "bsp", "BSP (reference only — not known at bet time)", True),
]
TARGETS = [
    ("below2", "ip_min <= 2.0", "trades at or below 2.0 in running", False),
    ("lay18", "ip_min <= 1.8", "trades at or below 1.8 in running", False),
    ("lay15", "ip_min <= 1.5", "trades at or below 1.5 in running", False),
    ("lay12", "ip_min <= 1.2", "trades at or below 1.2 in running", False),
    ("dob", "ip_min <= price / 2", "price halves or better from the pre-off price (dob)", True),
    ("dob2", "ip_min <= price / 4", "price quarters or better from the pre-off price (double dob)", True),
]
VERSIONS = [
    ("form", "form-only (speed figures + race conditions, no odds)"),
    ("price", "pre-off price only"),
    ("full", "pre-off price + form"),
]
PRICE_BANDS = [
    ("1-2", 1.0, 2.0), ("2-3", 2.0, 3.0), ("3-5", 3.0, 5.0),
    ("5-8", 5.0, 8.0), ("8-13", 8.0, 13.0), ("13-21", 13.0, 21.0),
    ("21+", 21.0, 1e9),
]
GOING_BUCKET = {
    "hard": "firm", "firm": "firm", "good to firm": "firm",
    "good": "good",
    "good to yielding": "soft", "good to soft": "soft", "yielding": "soft",
    "yielding to soft": "soft", "soft": "soft",
    "soft to heavy": "heavy", "heavy": "heavy",
    "fast": "aw_fast", "standard to fast": "aw_fast",
    "standard": "aw_std",
    "standard to slow": "aw_slow", "slow": "aw_slow",
}
CONT_PRICE = ["log_price", "imp_prob"]
CONT_FORM = [
    "field_size", "dist_f", "class",
    "prev_last", "prev_best", "prev_best3",
    "gap_best3", "rank_best3", "days_since",
    "miss_prev", "miss_days",
]
FIG_COLS = [
    "race_id", "date", "off_time", "course_raw", "course", "surface", "code",
    "dist_f", "going", "class", "horse", "horse_id",
    "prev_last", "prev_best", "prev_best3",
]
PRICE_NUM_COLS = ["bsp", "ip_min", "p15", "p10", "p5", "p3", "p2", "p1", "post"]


def log(msg):
    print(msg, flush=True)


def canon_course(raw):
    s = re.sub(r"\((AW|IRE)\)", "", str(raw or ""), flags=re.I)
    s = re.sub(r"[\s\-]", "", s).strip().lower()
    return s


def norm_horse(s):
    return re.sub(r"\s+", " ", str(s or "").strip().casefold())


def norm_time(s):
    s = str(s or "").strip()
    if not s:
        return ""
    parts = s.split(":")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return s


def going_bucket(s):
    key = re.sub(r"\s+", " ", str(s or "").strip().lower())
    key = re.sub(r"\b(rowley|july course|old course|new course|inner|outer|round|straight)\b", "", key)
    key = re.sub(r"\s+", " ", key).strip(" /-,")
    return GOING_BUCKET.get(key, "other")


def sigmoid(z):
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


def fit_logit(X, y, l2=0.5, max_iter=30, tol=1e-6):
    """Ridge logistic regression via IRLS. Intercept (col 0) is unpenalized."""
    n, p = X.shape
    w = np.zeros(p, dtype=np.float64)
    penalty = np.ones(p, dtype=np.float64) * l2
    penalty[0] = 0.0
    y = y.astype(np.float64)
    for _ in range(max_iter):
        p_hat = sigmoid(X @ w)
        wgt = np.clip(p_hat * (1.0 - p_hat), 1e-5, None)
        H = X.T @ (X * wgt[:, None])
        np.fill_diagonal(H, H.diagonal() + penalty)
        g = X.T @ (y - p_hat) - penalty * w
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(H, g, rcond=None)[0]
        step = np.clip(step, -5.0, 5.0)
        w = w + step
        if float(np.max(np.abs(step))) < tol:
            break
    return w


def predict_logit(X, w):
    return sigmoid(X @ w)


def log_loss(y, p):
    p = np.clip(p, 1e-6, 1.0 - 1e-6)
    y = y.astype(np.float64)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def brier(y, p):
    return float(np.mean((p - y.astype(np.float64)) ** 2))


def calibration_table(y, p, n_bins=10):
    y = np.asarray(y, dtype=np.float64)
    p = np.asarray(p, dtype=np.float64)
    try:
        qs = np.unique(np.quantile(p, np.linspace(0, 1, n_bins + 1)))
    except Exception:
        qs = np.array([0.0, 1.0])
    if len(qs) < 3:
        qs = np.array([0.0, 1.0])
    idx = np.digitize(p, qs[1:-1], right=True)
    rows = []
    for b in range(int(idx.max()) + 1):
        m = idx == b
        if not m.any():
            continue
        lo = qs[b] if b < len(qs) else p[m].min()
        hi = qs[b + 1] if (b + 1) < len(qs) else p[m].max()
        rows.append({
            "bin": b + 1,
            "p_lo": round(float(lo), 4),
            "p_hi": round(float(hi), 4),
            "n": int(m.sum()),
            "pred": round(float(p[m].mean()), 4),
            "actual": round(float(y[m].mean()), 4),
        })
    return rows


def price_band_labels(prices):
    out = []
    for x in prices:
        lab = "21+"
        for name, lo, hi in PRICE_BANDS:
            if (name == "21+" and x >= lo) or (lo <= x < hi):
                lab = name
                break
        out.append(lab)
    return out


def add_const(A):
    return np.column_stack([np.ones(len(A)), A])


def pct(x, d=1):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{100.0 * x:.{d}f}%"


# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
def load_prices(path):
    df = pd.read_csv(path, compression="gzip", dtype=str, keep_default_na=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["time"] = df["time"].map(norm_time)
    df["course_key"] = df["course"].map(canon_course)
    df["horse_key"] = df["horse"].map(norm_horse)
    for c in PRICE_NUM_COLS:
        if c not in df.columns:
            continue
        df[c] = pd.to_numeric(df[c], errors="coerce")
        # Betfair's 1000 is a cap / unmatched, not a usable price
        df.loc[(df[c] < 1.01) | (df[c] >= 999), c] = np.nan
    df = df.dropna(subset=["date", "ip_min"])
    df = df.drop_duplicates(["date", "time", "course_key", "horse_key"], keep="last")
    return df


def load_speed(path, limit_races=None):
    df = pd.read_csv(path, usecols=FIG_COLS, low_memory=False)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["off_time"] = df["off_time"].map(norm_time)
    df["course_key"] = df["course_raw"].map(canon_course)
    df["horse_key"] = df["horse"].map(norm_horse)
    df = df.dropna(subset=["date", "race_id"])
    if limit_races:
        races = df[["race_id", "date"]].drop_duplicates().sort_values("date")
        k = min(int(limit_races), len(races))
        half = max(k // 2, 1)
        keep = pd.concat([races.iloc[:half], races.iloc[-(k - half):]])
        df = df[df["race_id"].isin(keep["race_id"])].copy()
    return df


def join_prices(speed, prices):
    keys = ["date", "off_time", "course_key", "horse_key"]
    keep = keys + [c for c in PRICE_NUM_COLS if c in prices.columns]
    pr = prices.rename(columns={"time": "off_time"})
    m = speed.merge(pr[keep], on=keys, how="left")
    matched = m["ip_min"].notna().mean()
    return m, float(matched)


def add_snapshot_fields(df, price_col):
    df = df.copy()
    df["price"] = df[price_col]
    df = df.dropna(subset=["price", "ip_min"]).copy()
    df["log_price"] = np.log(df["price"].clip(lower=1.01, upper=200.0))
    df["imp_prob"] = (1.0 / df["price"]).clip(upper=1.0)
    df["y_below2"] = (df["ip_min"] <= 2.0).astype(np.int8)
    df["y_lay18"] = (df["ip_min"] <= 1.8).astype(np.int8)
    df["y_lay15"] = (df["ip_min"] <= 1.5).astype(np.int8)
    df["y_lay12"] = (df["ip_min"] <= 1.2).astype(np.int8)
    df["y_dob"] = (df["ip_min"] <= (df["price"] / 2.0)).astype(np.int8)
    df["y_dob2"] = (df["ip_min"] <= (df["price"] / 4.0)).astype(np.int8)
    return df


def add_form_features(df):
    df = df.copy()
    df["field_size"] = df.groupby("race_id")["horse_key"].transform("size")
    df["code"] = df["code"].fillna("UNK").astype(str)
    df["surface"] = df["surface"].fillna("UNK").astype(str)
    df["code_surf"] = df["code"] + "|" + df["surface"]
    df["going_b"] = df["going"].map(going_bucket)
    df["miss_prev"] = df["prev_best3"].isna().astype(np.float64)
    df["rank_best3"] = df.groupby("race_id")["prev_best3"].rank(
        ascending=False, method="average", na_option="bottom"
    )
    best = df.groupby("race_id")["prev_best3"].transform("max")
    df["gap_best3"] = df["prev_best3"] - best
    df = df.sort_values(["horse_id", "date", "off_time"], kind="mergesort")
    prev_date = df.groupby("horse_id")["date"].shift(1)
    df["days_since"] = (df["date"] - prev_date).dt.days
    df["miss_days"] = df["days_since"].isna().astype(np.float64)
    df["days_since"] = df["days_since"].clip(upper=400)
    return df


def dummy_frame(series, levels, prefix):
    s = series.astype(str)
    cols = {f"{prefix}={lv}": (s == lv).astype(np.float64) for lv in levels}
    return pd.DataFrame(cols, index=series.index)


def build_matrix(df, spec=None, mode="full"):
    """mode: 'form', 'price', or 'full'. Spec is fitted on train only."""
    work = df.copy()
    use_price = mode in ("price", "full")
    use_form = mode in ("form", "full")
    cont = (CONT_PRICE if use_price else []) + (CONT_FORM if use_form else [])

    if spec is None:
        levels_cs, levels_g = [], []
        if use_form:
            vc = work["code_surf"].value_counts()
            levels_cs = sorted(vc.loc[lambda s: s >= 50].index.tolist()) or sorted(work["code_surf"].unique())
            levels_g = sorted(work["going_b"].value_counts().index.tolist())
        impute = {c: float(work[c].median()) if work[c].notna().any() else 0.0 for c in cont}
        spec = {
            "mode": mode, "cont": list(cont),
            "levels_cs": levels_cs, "levels_g": levels_g, "impute": impute,
        }
        fit = True
    else:
        fit = False
        cont = list(spec["cont"])

    for c in cont:
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(spec["impute"].get(c, 0.0))

    parts, names = [], []
    if cont:
        Xc = work[cont].to_numpy(dtype=np.float64)
        if fit:
            mean = Xc.mean(axis=0)
            std = Xc.std(axis=0)
            std = np.where(std < 1e-8, 1.0, std)
            spec["mean"] = mean.tolist()
            spec["std"] = std.tolist()
        else:
            mean = np.asarray(spec["mean"], dtype=np.float64)
            std = np.asarray(spec["std"], dtype=np.float64)
        parts.append((Xc - mean) / std)
        names.extend(cont)

    if use_form:
        dcs = dummy_frame(work["code_surf"], spec["levels_cs"], "cs")
        dg = dummy_frame(work["going_b"], spec["levels_g"], "going")
        if len(dg.columns) > 1:
            dg = dg.iloc[:, :-1]
        parts.append(dcs.to_numpy(dtype=np.float64))
        names.extend(list(dcs.columns))
        parts.append(dg.to_numpy(dtype=np.float64))
        names.extend(list(dg.columns))

    X = add_const(np.column_stack(parts) if parts else np.zeros((len(work), 0)))
    names = ["intercept"] + names
    spec["feature_names"] = names
    return X, names, spec


def time_split(df, test_months=12):
    dmax = df["date"].max()
    cut = dmax - pd.DateOffset(months=test_months)
    train = df[df["date"] < cut].copy()
    test = df[df["date"] >= cut].copy()
    if len(train) < 200 or len(test) < 50:
        dates = np.sort(df["date"].unique())
        cut2 = dates[max(int(len(dates) * 0.7), 1)]
        train = df[df["date"] < cut2].copy()
        test = df[df["date"] >= cut2].copy()
        cut = pd.Timestamp(cut2)
    return train, test, pd.Timestamp(cut), pd.Timestamp(dmax)


def metrics_block(y, p):
    return {
        "n": int(len(y)),
        "base_rate": float(np.mean(y)),
        "brier": brier(y, p),
        "logloss": log_loss(y, p),
        "calibration": calibration_table(y, p),
    }


def edge_check(y, p, p_base):
    m = p > p_base
    n = int(m.sum())
    if n == 0:
        return {"n": 0, "hit_rate": None, "avg_pred": None, "share": 0.0}
    return {
        "n": n,
        "hit_rate": float(np.mean(y[m])),
        "avg_pred": float(np.mean(p[m])),
        "share": float(n / len(y)),
    }


def band_table(prices, y, p=None):
    bands = price_band_labels(np.asarray(prices))
    rows = []
    for name, _, _ in PRICE_BANDS:
        m = np.array([b == name for b in bands])
        if not m.any():
            rows.append({"band": name, "n": 0, "hit_rate": None, "avg_pred": None, "avg_price": None})
            continue
        rows.append({
            "band": name,
            "n": int(m.sum()),
            "hit_rate": round(float(np.mean(y[m])), 4),
            "avg_pred": None if p is None else round(float(np.mean(p[m])), 4),
            "avg_price": round(float(np.asarray(prices)[m].mean()), 2),
        })
    return rows


def save_model(out_dir, snap, version, tid, formula, desc, w, names, spec, info):
    payload = {
        "snapshot": snap,
        "version": version,
        "target": tid,
        "formula": formula,
        "description": desc,
        "coefficients": {n: float(v) for n, v in zip(names, w)},
        "feature_names": names,
        "spec": {
            "mode": spec["mode"],
            "cont": spec["cont"],
            "levels_cs": spec["levels_cs"],
            "levels_g": spec["levels_g"],
            "impute": spec["impute"],
            "mean": spec.get("mean", []),
            "std": spec.get("std", []),
        },
        "train_start": info["train_start"],
        "train_end": info["train_end"],
        "test_start": info["test_start"],
        "test_end": info["test_end"],
    }
    (out_dir / f"model_{snap}_{version}_{tid}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def score_cards(cards_path):
    if not cards_path.exists():
        return f"Scoring today's card: skipped ({cards_path} not found)."
    try:
        con = sqlite3.connect(str(cards_path))
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]
        if not tables:
            con.close()
            return f"Scoring today's card: skipped ({cards_path} has no tables)."
        best, best_n, best_cols = None, -1, []
        for t in tables:
            cols = [r[1].lower() for r in con.execute(f"PRAGMA table_info({t})")]
            n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n > best_n:
                best, best_n, best_cols = t, n, cols
        con.close()
        return ("Scoring today's card: cards.sqlite was found "
                f"(table {best}, {best_n} rows, columns: {', '.join(best_cols)}). "
                "A full score needs pre-race speed figures joined onto the card, "
                "so this is skipped for now.")
    except Exception as e:
        return f"Scoring today's card: skipped ({type(e).__name__}: {e})."


def write_summary(path, info, snap_results, cards_note):
    lines = []
    a = lines.append
    a("TRADE / LAY PREDICTIONS")
    a("Models are trained to decide at 5 minutes, 2 minutes and 1 minute before the off.")
    a("BSP is not known at those times, so the BSP model is a reference only.")
    a("")
    a("RBD pre-off price columns (exact names):")
    a("  '15 Mins', '10 mins', '5 mins', '3 mins', '2 mins', '1 min', 'Post Time', 'BSP'")
    a("  In-running low: 'Min Price'.  Not used: 'Last Traded Price' (this is in-running, often 1.01 or 1000).")
    a("  Models use '5 mins', '2 mins', '1 min'.  'BSP' is fitted only as a reference.")
    a("  Also present but not modelled: '15 Mins', '10 mins', '3 mins', 'Post Time'.")
    a("")
    a(f"Speed-figure rows matched to a Betfair in-running price: {pct(info['join_rate'])}")
    a(f"Date range in the joined file: {info['date_min']} to {info['date_max']}")
    a("Features (form): prev_best / prev_last / prev_best3, gap and rank vs the race's best")
    a("prev_best3, field size, code/surface, distance, class, going, days since last run,")
    a("plus missing-figure / first-start flags.")
    a("Features (price): log of the snapshot price and implied probability 1/price.")
    a("Train = older races; test = latest ~12 months. Same runners for all three versions.")
    a("")
    a("Note on targets: the fixed levels (<=2.0 / 1.8 / 1.5 / 1.2) work with a form-only model,")
    a("because they do not depend on the pre-off price. DOB and double DOB still need the")
    a("pre-off snapshot price to define the label (ip_min <= price/2 or price/4), even in")
    a("the form-only version, which then does not use that price as a feature.")
    a("")
    if cards_note:
        a(cards_note)
        a("")

    for snap, col, desc, is_ref in SNAPSHOTS:
        if snap not in snap_results:
            continue
        r = snap_results[snap]
        a("=" * 76)
        tag = "  [REFERENCE ONLY]" if is_ref else ""
        a(f"SNAPSHOT {snap}  —  {desc}{tag}")
        a(f"RBD column: '{RBD_PRICE_COLS[col]}'   coverage {r['n']:,} runners in {r['n_races']:,} races "
          f"({pct(r['coverage'])} of joined runners)")
        a(f"Train: {r['train_start']} to {r['train_end']}  ({r['n_train']:,})")
        a(f"Test:  {r['test_start']} to {r['test_end']}  ({r['n_test']:,})")
        a("")
        for tid, formula, tdesc, needs_price in TARGETS:
            tr = r["targets"][tid]
            a("-" * 76)
            a(f"{tid.upper()}  —  {tdesc}")
            a(f"Target: {formula}" + ("  (label uses this snapshot's price)" if needs_price else ""))
            a(f"Base rate   train {pct(tr['train_rate'])}   test {pct(tr['test_rate'])}   n_test={tr['n_test']:,}")
            a("")
            a(f"  {'version':<22}{'Brier':>10}{'Log loss':>12}{'vs price Brier':>16}")
            brier_price = tr["versions"]["price"]["brier"]
            for ver, _vdesc in VERSIONS:
                vm = tr["versions"][ver]
                delta = vm["brier"] - brier_price
                vs = "same" if abs(delta) < 1e-6 else f"{delta:+.4f}"
                a(f"  {ver:<22}{vm['brier']:>10.4f}{vm['logloss']:>12.4f}{vs:>16}")
            # lower Brier is better — call the winner
            best_ver = min(VERSIONS, key=lambda v: tr["versions"][v[0]]["brier"])[0]
            a(f"  Best Brier on test: {best_ver}")
            ev = tr["edge"]
            if ev["n"]:
                a(f"  When price+form prob > price-only prob: {ev['n']:,} runners "
                  f"({pct(ev['share'])} of test), hit rate {pct(ev['hit_rate'])} "
                  f"(test base rate {pct(tr['test_rate'])}), avg full-model prob {pct(ev['avg_pred'])}.")
            a("")
            a("  Calibration on test, price+form model (equal-count bins):")
            a(f"    {'bin':<5}{'n':>8}{'pred':>10}{'actual':>10}")
            for row in tr["versions"]["full"]["calibration"]:
                a(f"    {row['bin']:<5}{row['n']:>8}{row['pred']:>10.3f}{row['actual']:>10.3f}")
            a("")
            a("  Actual hit rate by snapshot-price band (test; same for all versions):")
            a(f"    {'band':<8}{'n':>8}{'hit rate':>10}{'full pred':>10}{'avg price':>12}")
            for row in tr["bands"]:
                if row["n"] == 0:
                    a(f"    {row['band']:<8}{0:>8}{'n/a':>10}{'n/a':>10}{'n/a':>12}")
                else:
                    a(f"    {row['band']:<8}{row['n']:>8}{pct(row['hit_rate']):>10}"
                      f"{pct(row['avg_pred']):>10}{row['avg_price']:>12.2f}")
            a("")

    a("Notes")
    a("- Official ratings are not in this file; they can be added later from the RBD data.")
    a("- Runners with no in-running min price, or no price at that snapshot, are dropped.")
    a("- Re-run any time; it overwrites data\\predict\\.")
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def parse_args():
    ap = argparse.ArgumentParser(description="Trade-below-2 / dob / lay-low models")
    ap.add_argument("--speeds", default=str(ROOT / "data" / "speed_v3" / "speed_figures.csv"))
    ap.add_argument("--prices", default=str(ROOT / "data" / "rbd_prices.csv.gz"))
    ap.add_argument("--out", default=str(ROOT / "data" / "predict"))
    ap.add_argument("--cards", default=str(ROOT / "data" / "cards.sqlite"))
    ap.add_argument("--limit", type=int, default=0,
                    help="Smoke test: use only this many races (half oldest, half newest).")
    ap.add_argument("--test-months", type=int, default=12)
    ap.add_argument("--score-cards", action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()
    t0 = time.time()
    speeds, prices, out = Path(args.speeds), Path(args.prices), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.score_cards and not speeds.exists():
        log(score_cards(Path(args.cards)))
        return
    if not speeds.exists():
        sys.exit(f"Speed figures not found: {speeds}")
    if not prices.exists():
        sys.exit(f"Prices file not found: {prices}\nExpected data\\rbd_prices.csv.gz in the Speeds folder.")

    log(f"Loading speed figures from {speeds}")
    sp = load_speed(speeds, limit_races=(args.limit or None))
    log(f"  {len(sp):,} runners, {sp['race_id'].nunique():,} races, "
        f"{sp['date'].min().date()} to {sp['date'].max().date()}")
    log(f"Loading Betfair prices from {prices}")
    pr = load_prices(prices)
    log(f"  {len(pr):,} rows with an in-running min price, {pr['date'].min().date()} to {pr['date'].max().date()}")

    joined, join_rate = join_prices(sp, pr)
    joined = joined[joined["ip_min"].notna()].copy()
    log(f"Joined {len(joined):,} runners with an in-running price ({pct(join_rate)} of speed-figure rows)")
    if len(joined) < 100:
        sys.exit("Not enough joined rows to train. Check date/course/horse matching.")

    # form features once, on the full joined set (prev figs / days-since use whole history)
    joined = add_form_features(joined)
    info = {
        "join_rate": join_rate,
        "date_min": str(joined["date"].min().date()),
        "date_max": str(joined["date"].max().date()),
        "n_joined": int(len(joined)),
    }

    snap_results = {}
    cal_rows, band_rows, coef_rows, metric_rows = [], [], [], []

    for snap, col, desc, is_ref in SNAPSHOTS:
        log(f"Snapshot {snap}  (RBD '{RBD_PRICE_COLS[col]}'){'  [reference]' if is_ref else ''}...")
        if col not in joined.columns:
            log(f"  column {col} missing — skipped")
            continue
        df = add_snapshot_fields(joined, col)
        coverage = len(df) / max(len(joined), 1)
        if len(df) < 100:
            log(f"  only {len(df)} priced runners — skipped")
            continue
        train, test, cut, dmax = time_split(df, test_months=args.test_months)
        if len(train) < 50 or len(test) < 20:
            log(f"  split too small (train={len(train)}, test={len(test)}) — skipped")
            continue
        sinfo = {
            "n": int(len(df)), "n_races": int(df["race_id"].nunique()),
            "coverage": float(coverage),
            "n_train": int(len(train)), "n_test": int(len(test)),
            "train_start": str(train["date"].min().date()),
            "train_end": str(train["date"].max().date()),
            "test_start": str(test["date"].min().date()),
            "test_end": str(test["date"].max().date()),
        }

        mats = {}
        for mode, _d in VERSIONS:
            Xtr, names, spec = build_matrix(train, None, mode=mode)
            Xte, _, _ = build_matrix(test, spec, mode=mode)
            mats[mode] = {"Xtr": Xtr, "Xte": Xte, "names": names, "spec": spec}

        targets_out = {}
        for tid, formula, tdesc, _needs_price in TARGETS:
            ycol = f"y_{tid}"
            ytr = train[ycol].to_numpy()
            yte = test[ycol].to_numpy()
            vers = {}
            preds = {}
            for mode, _d in VERSIONS:
                w = fit_logit(mats[mode]["Xtr"], ytr, l2=0.5)
                p_te = predict_logit(mats[mode]["Xte"], w)
                preds[mode] = p_te
                mets = metrics_block(yte, p_te)
                vers[mode] = mets
                save_model(out, snap, mode, tid, formula, tdesc, w,
                           mats[mode]["names"], mats[mode]["spec"], sinfo)
                for name, val in zip(mats[mode]["names"], w):
                    coef_rows.append({"snapshot": snap, "version": mode, "target": tid,
                                      "feature": name, "coef": float(val)})
                for row in mets["calibration"]:
                    cal_rows.append({"snapshot": snap, "version": mode, "target": tid, **row})
                metric_rows.append({
                    "snapshot": snap, "version": mode, "target": tid,
                    "n_test": mets["n"], "base_rate": mets["base_rate"],
                    "brier": mets["brier"], "logloss": mets["logloss"],
                })
            edge = edge_check(yte, preds["full"], preds["price"])
            bands = band_table(test["price"].to_numpy(), yte, preds["full"])
            for row in bands:
                band_rows.append({"snapshot": snap, "target": tid, **row})
            targets_out[tid] = {
                "train_rate": float(ytr.mean()),
                "test_rate": float(yte.mean()),
                "n_test": int(len(yte)),
                "versions": vers,
                "edge": edge,
                "bands": bands,
            }
            log(f"  {tid}: form {vers['form']['brier']:.4f}  price {vers['price']['brier']:.4f}  "
                f"full {vers['full']['brier']:.4f}  base {yte.mean():.1%}")

        snap_results[snap] = {**sinfo, "targets": targets_out}

    if not snap_results:
        sys.exit("No snapshot had enough priced runners to train.")

    pd.DataFrame(cal_rows).to_csv(out / "calibration.csv", index=False)
    pd.DataFrame(band_rows).to_csv(out / "price_bands.csv", index=False)
    pd.DataFrame(coef_rows).to_csv(out / "coefficients.csv", index=False)
    pd.DataFrame(metric_rows).to_csv(out / "metrics.csv", index=False)
    (out / "metrics.json").write_text(json.dumps({
        "info": info,
        "snapshots": {
            s: {k: v for k, v in r.items() if k != "targets"} | {
                "targets": {
                    tid: {
                        "train_rate": t["train_rate"],
                        "test_rate": t["test_rate"],
                        "edge": t["edge"],
                        "versions": {ver: {"brier": t["versions"][ver]["brier"],
                                           "logloss": t["versions"][ver]["logloss"]}
                                     for ver, _ in VERSIONS},
                    } for tid, t in r["targets"].items()
                }
            } for s, r in snap_results.items()
        },
    }, indent=2, default=str), encoding="utf-8")

    cards_note = score_cards(Path(args.cards))
    text = write_summary(out / "summary.txt", info, snap_results, cards_note)
    elapsed = time.time() - t0
    log("")
    log(text)
    log(f"Wrote outputs to {out}")
    log(f"Done in {elapsed/60:.1f} minutes.")


if __name__ == "__main__":
    main()
