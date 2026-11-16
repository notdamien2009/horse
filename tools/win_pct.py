#!/usr/bin/env python3
r"""
Form-only win probability for FurlongIQ.

Trains a conditional logit (softmax within each race) so the probabilities
sum to 100%. Inputs are form features only — no starting price, BSP or
forecast is used to fit or score. Prices from the RBD file are used only
afterwards, to test calibration and whether backing at BSP / 5-minute
prices would have been profitable.

Usage (from the Speeds folder):
    python tools\win_pct.py
    python tools\win_pct.py --score-only
    python tools\win_pct.py --date 2026-11-16
"""
from __future__ import annotations

import argparse, json, math, sqlite3, sys, time
from pathlib import Path

import numpy as np
import pandas as pd
import predict_today as pt

ROOT = pt.ROOT
DATA = pt.DATA
CACHE = pt.CACHE
CARDS = pt.CARDS
OUT_DIR = DATA / "predict_today"
MODEL_PATH = OUT_DIR / "win_pct_model.json"
SUMMARY_PATH = OUT_DIR / "win_pct_summary.txt"
TODAY_PATH = OUT_DIR / "win_pct_today.json"

# Horse-varying features (race-constant terms cancel in a conditional logit).
# Interactions with field size are included so bigger fields can change the slope.
FEATURES = [
    "pred_z", "pred_gap", "pred_rank", "has_pred",
    "best3_z", "best3_gap", "last_z",
    "last_adj_z", "wmean_adj_z",
    "last_low", "last_suspect",
    "cls_chg_last", "or_chg", "has_or",
    "days", "log_days", "has_days",
    "n_runs", "light",
    "going_match", "dist_diff", "same_code",
    "has_form",
    "pred_z_xf", "pred_gap_xf",
]

LAM = 4.0
# Shrink unreliable (pace-affected / suspect) figures toward the recent mean.
REL_W = {"ok": 1.0, "low": 0.35, "suspect": 0.35}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_pace_map() -> dict[tuple[str, str], str]:
    """(date, horse_norm) -> fig_rel, from site_cache.pace. Read-only."""
    out: dict[tuple[str, str], str] = {}
    if not CACHE.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
        if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pace'").fetchone():
            con.close()
            return out
        for date, rel, horses in con.execute("SELECT date, fig_rel, horses FROM pace"):
            d = str(date or "")[:10]
            r = str(rel or "").strip().lower()
            if not d or r not in {"ok", "low", "suspect"}:
                continue
            for name in str(horses or "").split(","):
                n = name.strip()
                if n:
                    out[(d, n)] = r
        con.close()
    except Exception as e:
        log(f"  Pace lookup skipped ({e}). Reliability-adjusted figures will equal raw figures.")
        return {}
    log(f"  Pace reliability map: {len(out):,} horse-runs")
    return out


def rel_of(pace_map: dict, date, horse_norm) -> str:
    if not date or not horse_norm:
        return ""
    return pace_map.get((str(date)[:10], str(horse_norm)), "")


def adj_from_hist(hist: list[dict], today: dict, pace_map: dict, fig_key: str = "fig") -> tuple[float | None, float | None, float | None, str]:
    """Reliability-adjusted last / wmean / best3, plus the last-run fig_rel."""
    if not hist:
        return None, None, None, ""
    fam = pt.is_jumps(today["code"])
    pool_all = [r for r in hist if r.get(fig_key) is not None]
    pool_fam = [r for r in pool_all if pt.is_jumps(r["code"]) == fam]
    pool = pool_fam or pool_all
    if not pool:
        return None, None, None, ""
    last_rel = rel_of(pace_map, pool[-1].get("date"), pool[-1].get("horse_norm"))
    recent = pool[-12:]
    last = recent[-1][fig_key]
    wmean = None
    tail = recent[-8:]
    num = den = 0.0
    for i, r in enumerate(tail):
        decay = 0.7 ** (len(tail) - 1 - i)
        w = decay * REL_W.get(rel_of(pace_map, r.get("date"), r.get("horse_norm")), 1.0)
        num += w * r[fig_key]
        den += w
    if den > 0:
        wmean = num / den
    adj_vals = []
    for r in recent:
        fig = r[fig_key]
        rel = rel_of(pace_map, r.get("date"), r.get("horse_norm"))
        if rel in {"low", "suspect"} and wmean is not None:
            adj_vals.append(0.5 * fig + 0.5 * wmean)
        else:
            adj_vals.append(fig)
    top3 = sorted(adj_vals, reverse=True)[:3]
    best3 = sum(top3) / len(top3) if top3 else None
    if last_rel in {"low", "suspect"} and wmean is not None:
        last_adj = 0.5 * last + 0.5 * wmean
    else:
        last_adj = last
    return last_adj, wmean, best3, last_rel


def build_win_dataset(df: pd.DataFrame, pace_map: dict) -> pd.DataFrame:
    """One row per run, including first-starters (has_form=0). Prior-run features only."""
    recs = []
    n_h = df["horse_id"].nunique()
    done = 0
    t0 = time.time()
    for horse_id, g in df.groupby("horse_id", sort=False):
        hist: list[dict] = []
        done += 1
        if done % 20000 == 0:
            log(f"    … {done:,}/{n_h:,} horses ({time.time() - t0:.0f}s)")
        for _, r in g.iterrows():
            row = pt.row_from_csv(r)
            feat = pt.features_from_hist(hist, row, fig_key="fig")
            rec = {
                "race_id": row["race_id"],
                "date": str(row["date"])[:10],
                "horse_id": horse_id,
                "horse_norm": row["horse_norm"],
                "horse": row["horse"],
                "course": row["course"],
                "off_time": row["off_time"],
                "place": row["place"],
                "code": row["code"],
                "has_form": 0.0,
                "last_adj": None,
                "wmean_adj": None,
                "best3_adj": None,
                "last_rel": "",
            }
            if feat is not None:
                rec.update(feat)
                rec["has_form"] = 1.0
                last_adj, wmean_adj, best3_adj, last_rel = adj_from_hist(hist, row, pace_map, "fig")
                rec["last_adj"] = last_adj
                rec["wmean_adj"] = wmean_adj
                rec["best3_adj"] = best3_adj
                rec["last_rel"] = last_rel
            recs.append(rec)
            hist.append(row)
    if not recs:
        return pd.DataFrame()
    return pd.DataFrame.from_records(recs)


def apply_pred(feat: pd.DataFrame, form_model: dict) -> np.ndarray:
    """Form-only predicted figure (OR features zeroed, matching the race card)."""
    pred = np.full(len(feat), np.nan)
    mask = feat["has_form"].to_numpy(float) > 0.5
    if not mask.any():
        return pred
    sub = feat.loc[mask].copy()
    for c in ("or_today", "or_chg", "has_or"):
        if c in sub.columns:
            sub[c] = 0.0
    X = pt.matrix(sub)
    pred[mask] = _apply_form(form_model, X)
    return pred


def _apply_form(model: dict, X: np.ndarray) -> np.ndarray:
    mean = np.array(model["mean"], dtype=float)
    std = np.array(model["std"], dtype=float)
    std = np.where(std < 1e-8, 1.0, std)
    z = (X - mean) / std
    p = model["intercept"] + z @ np.array(model["coef"], dtype=float)
    return np.clip(p, pt.FLOOR, pt.CEIL)


def add_race_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["field_size"] = out.groupby("race_id")["race_id"].transform("size")
    p = pd.to_numeric(out.get("pred"), errors="coerce")
    has_form = pd.to_numeric(out["has_form"], errors="coerce").fillna(0.0) if "has_form" in out.columns else 0.0
    out["has_pred"] = (p.notna() & (has_form > 0.5)).astype(float)
    race_min = p.groupby(out["race_id"]).transform("min")
    out["pred_fill"] = p.fillna((race_min - 8.0).fillna(70.0))
    gpred = out.groupby("race_id")["pred_fill"]
    out["pred_z"] = out["pred_fill"] - gpred.transform("mean")
    out["pred_gap"] = gpred.transform("max") - out["pred_fill"]
    out["pred_rank"] = gpred.rank(ascending=False, method="min")

    def centred(src: str, zname: str, gname: str | None = None) -> None:
        s = pd.to_numeric(out[src], errors="coerce") if src in out.columns else pd.Series(np.nan, index=out.index)
        med = s.groupby(out["race_id"]).transform("median")
        fill = s.fillna(med).fillna(0.0)
        out[zname] = fill - fill.groupby(out["race_id"]).transform("mean")
        if gname:
            out[gname] = fill.groupby(out["race_id"]).transform("max") - fill

    centred("best3_raw", "best3_z", "best3_gap")
    centred("last_raw", "last_z")
    centred("last_adj", "last_adj_z")
    centred("wmean_adj", "wmean_adj_z")
    xf = np.log1p(out["field_size"].astype(float))
    out["pred_z_xf"] = out["pred_z"] * xf
    out["pred_gap_xf"] = out["pred_gap"] * xf
    rel = out["last_rel"].astype(str) if "last_rel" in out.columns else ""
    out["last_low"] = (rel == "low").astype(float) if "last_rel" in out.columns else 0.0
    out["last_suspect"] = (rel == "suspect").astype(float) if "last_rel" in out.columns else 0.0
    defaults = {
        "cls_chg_last": 0.0, "or_chg": 0.0, "has_or": 0.0,
        "days": 30.0, "log_days": math.log1p(30.0), "has_days": 0.0,
        "n_runs": 0.0, "light": 1.0,
        "going_match": 0.0, "dist_diff": 0.0, "same_code": 0.0,
        "has_form": 0.0,
    }
    for c, default in defaults.items():
        if c not in out.columns:
            out[c] = default
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(default)
    return out


def matrix_win(df: pd.DataFrame) -> np.ndarray:
    cols = []
    for k in FEATURES:
        if k not in df.columns:
            cols.append(np.zeros(len(df)))
        else:
            cols.append(pd.to_numeric(df[k], errors="coerce").fillna(0.0).to_numpy(float))
    return np.column_stack(cols)


def standardize(X: np.ndarray, mean: np.ndarray | None = None, std: np.ndarray | None = None):
    if mean is None:
        mean = X.mean(axis=0)
        std = X.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return (X - mean) / std, mean, std


def softmax_by_race(u: np.ndarray, race: np.ndarray) -> np.ndarray:
    s = pd.Series(u)
    g = pd.Series(race)
    mx = s.groupby(g).transform("max").to_numpy()
    e = np.exp(np.clip(u - mx, -50, 50))
    z = pd.Series(e).groupby(g).transform("sum").to_numpy()
    z = np.where(z <= 0, 1.0, z)
    return e / z


def nll_grad(beta: np.ndarray, X: np.ndarray, race: np.ndarray, y: np.ndarray, lam: float):
    u = X @ beta
    p = softmax_by_race(u, race)
    # one winner per race; y is 0/1
    eps = 1e-15
    win_mask = y > 0.5
    loss = -np.log(np.clip(p[win_mask], eps, 1.0)).sum() + 0.5 * lam * float(beta @ beta)
    # dNLL/dbeta = X' (p - y) + lam * beta
    grad = X.T @ (p - y) + lam * beta
    return loss, grad


def fit_clogit(X: np.ndarray, race: np.ndarray, y: np.ndarray, lam: float = LAM) -> np.ndarray:
    from scipy.optimize import minimize
    p = X.shape[1]
    beta0 = np.zeros(p)
    res = minimize(
        lambda b: nll_grad(b, X, race, y, lam),
        beta0,
        jac=True,
        method="L-BFGS-B",
        options={"maxiter": 250, "ftol": 1e-8},
    )
    if not res.success:
        log(f"  Warning: optimiser said {res.message}. Using the last coefficients anyway.")
    log(f"  Conditional logit: NLL {res.fun:.1f}, {res.nit} iterations")
    return res.x


def eligible_races(df: pd.DataFrame) -> pd.DataFrame:
    """Keep races with a recorded winner and at least two runners."""
    keep = []
    for rid, g in df.groupby("race_id", sort=False):
        if len(g) < 2:
            continue
        if not (g["place"] == 1).any():
            continue
        keep.append(g)
    if not keep:
        return df.iloc[0:0].copy()
    return pd.concat(keep, ignore_index=True)


def predict_proba(df: pd.DataFrame, model: dict) -> np.ndarray:
    X = matrix_win(df)
    mean = np.array(model["mean"], dtype=float)
    std = np.array(model["std"], dtype=float)
    std = np.where(std < 1e-8, 1.0, std)
    z = (X - mean) / std
    beta = np.array(model["coef"], dtype=float)
    u = z @ beta
    race = df["race_id"].to_numpy()
    return softmax_by_race(u, race)


def calibration(df: pd.DataFrame, pcol: str = "p") -> list[dict]:
    bands = [
        (0, 0.05, "0–5%"),
        (0.05, 0.10, "5–10%"),
        (0.10, 0.15, "10–15%"),
        (0.15, 0.20, "15–20%"),
        (0.20, 0.30, "20–30%"),
        (0.30, 0.40, "30–40%"),
        (0.40, 0.50, "40–50%"),
        (0.50, 1.01, "50%+"),
    ]
    rows = []
    p = df[pcol].to_numpy(float)
    y = (df["place"] == 1).to_numpy()
    for lo, hi, label in bands:
        m = (p >= lo) & (p < hi) if hi < 1.01 else (p >= lo) & (p <= 1.0)
        n = int(m.sum())
        if n == 0:
            rows.append({"band": label, "n": 0, "pred": None, "actual": None})
            continue
        rows.append({
            "band": label, "n": n,
            "pred": float(p[m].mean()),
            "actual": float(y[m].mean()),
        })
    return rows


def top_pick_rate(df: pd.DataFrame, pcol: str = "p") -> tuple[float, int]:
    hits = races = 0
    for rid, g in df.groupby("race_id", sort=False):
        if not (g["place"] == 1).any():
            continue
        races += 1
        top = g[pcol].max()
        leaders = g[g[pcol] >= top - 1e-12]
        if (leaders["place"] == 1).any():
            hits += 1
    return (hits / races if races else float("nan"), races)


def load_eval_prices() -> pd.DataFrame | None:
    p = pt.find_prices()
    if not p:
        log("No RBD prices file found — value test will be skipped.")
        return None
    log(f"Loading prices from {p} for the value test only…")
    df = pd.read_csv(p, usecols=["date", "time", "course", "horse", "bsp", "p5"], low_memory=False)
    df["bsp"] = pd.to_numeric(df["bsp"], errors="coerce")
    df["p5"] = pd.to_numeric(df["p5"], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    df["horse_norm"] = df["horse"].map(pt.norm_name)
    df["course_key"] = df["course"].astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    log(f"  {len(df):,} priced runners, {df['date'].min()} → {df['date'].max()}")
    return df


def attach_prices(test: pd.DataFrame, prices: pd.DataFrame | None) -> pd.DataFrame:
    out = test.copy()
    out["bsp"] = np.nan
    out["p5"] = np.nan
    if prices is None or prices.empty:
        return out
    t = out[["date", "horse_norm", "course"]].copy()
    t["date"] = t["date"].astype(str).str[:10]
    t["horse_norm"] = t["horse_norm"].astype(str)
    t["course_key"] = t["course"].astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    t["_i"] = np.arange(len(t))
    p = prices[["date", "horse_norm", "course_key", "bsp", "p5"]].copy()
    # Prefer date + name + course; fall back to date + name.
    m1 = t.merge(p, on=["date", "horse_norm", "course_key"], how="left", suffixes=("", "_p"))
    m1 = m1.drop_duplicates("_i", keep="first")
    miss = m1["bsp"].isna()
    if miss.any():
        m2 = t.loc[miss.values].merge(
            p.drop(columns=["course_key"]),
            on=["date", "horse_norm"],
            how="left",
        )
        m2 = m2.drop_duplicates("_i", keep="first").set_index("_i")
        m1 = m1.set_index("_i")
        m1.loc[m2.index, "bsp"] = m2["bsp"]
        m1.loc[m2.index, "p5"] = m2["p5"]
        m1 = m1.reset_index()
    out["bsp"] = m1["bsp"].to_numpy()
    out["p5"] = m1["p5"].to_numpy()
    return out


def value_report(df: pd.DataFrame, price_col: str, comms=(0.02, 0.05), edges=(1.0, 1.2, 1.5)) -> list[dict]:
    """Back when the price is longer than our fair odds, at a few edge thresholds."""
    rows = []
    fair = 1.0 / np.clip(df["p"].to_numpy(float), 1e-6, 0.999)
    price = pd.to_numeric(df[price_col], errors="coerce").to_numpy(float)
    won = (df["place"] == 1).to_numpy()
    for edge in edges:
        take = np.isfinite(price) & (price > 1.01) & (price > fair * edge)
        n = int(take.sum())
        rec = {"price": price_col, "edge": edge, "n": n, "wins": 0, "by_comm": {}}
        if n == 0:
            for c in comms:
                rec["by_comm"][f"{c:.0%}"] = {"profit": 0.0, "roi": None}
            rows.append(rec)
            continue
        w = won[take]
        rec["wins"] = int(w.sum())
        px = price[take]
        for c in comms:
            pnl = np.where(w, (px - 1.0) * (1.0 - c), -1.0)
            profit = float(pnl.sum())
            rec["by_comm"][f"{c:.0%}"] = {"profit": profit, "roi": profit / n}
        rows.append(rec)
    return rows


def fmt_pct(x, digits=1) -> str:
    if x is None or not (isinstance(x, (int, float)) and math.isfinite(x)):
        return "n/a"
    return f"{100 * x:.{digits}f}%"


def fmt_roi(x) -> str:
    if x is None or not math.isfinite(x):
        return "n/a"
    return f"{100 * x:+.1f}%"


def write_summary(payload: dict, today_n: int, today_races: int) -> str:
    ev = payload.get("eval") or {}
    lines = []
    a = lines.append
    a("FurlongIQ — Form-only win probability")
    a("=" * 72)
    a(f"Trained: {payload.get('trained')}")
    a("Method:  conditional logit (softmax within each race). Probabilities sum to 100%.")
    a("Inputs:  predicted-today figure (form only), its rank and gap to the top,")
    a("         Best of last 3, last figure, pace-reliability-adjusted recent figures,")
    a("         class move, OR change, days since last run, field size (as an")
    a("         interaction), trip/going/code match. No prices are used as inputs.")
    a(f"Split:   test = latest ~12 months from {payload.get('test_start')} (never used in training).")
    a("")
    a(f"  Train: {payload.get('n_train_rows'):,} runners in {payload.get('n_train_races'):,} races")
    a(f"  Test:  {payload.get('n_test_rows'):,} runners in {payload.get('n_test_races'):,} races")
    a("")
    a("Top-pick strike rate (test)")
    a("-" * 72)
    a(f"  Our top win-% horse won  {fmt_pct(ev.get('top_rate'))}  of {ev.get('top_n', 0):,} races")
    a(f"  Top predicted-today fig  {fmt_pct(ev.get('top_pred_rate'))}  of {ev.get('top_pred_n', 0):,} races")
    if ev.get("fav_n"):
        a(f"  Favourite (lowest BSP)   {fmt_pct(ev.get('fav_rate'))}  of {ev.get('fav_n'):,} priced races")
    a("")
    a("Calibration by predicted win % (test)")
    a("-" * 72)
    a(f"  {'Band':<10}{'N':>8}{'Predicted':>12}{'Actual':>10}")
    for row in ev.get("calibration") or []:
        if not row["n"]:
            a(f"  {row['band']:<10}{0:>8}{'–':>12}{'–':>10}")
        else:
            a(f"  {row['band']:<10}{row['n']:>8,}{fmt_pct(row['pred']):>12}{fmt_pct(row['actual']):>10}")
    a("")
    a("Value test — back when the price is longer than our fair odds")
    a("-" * 72)
    a("  Prices are used only for this check (never as model inputs).")
    a("  Stake £1; Betfair-style commission taken on net winnings only.")
    a(f"  BSP matched on {fmt_pct(ev.get('bsp_cov'), 0)} of test runners; 5-minute price on {fmt_pct(ev.get('p5_cov'), 0)}.")
    if ev.get("value"):
        a(f"  {'Price':<8}{'Edge':>6}{'Bets':>8}{'Wins':>6}  {'ROI after 2%':>14}  {'ROI after 5%':>14}")
        for row in ev["value"]:
            c2 = row["by_comm"]["2%"]
            c5 = row["by_comm"]["5%"]
            a(f"  {row['price']:<8}{row['edge']:>5.1f}x{row['n']:>8,}{row['wins']:>6,}  "
              f"{fmt_roi(c2['roi']):>14}  {fmt_roi(c5['roi']):>14}")
        a("")
        # Honest one-liner
        bsp = [r for r in ev["value"] if r["price"] == "bsp" and r["edge"] == 1.0]
        if bsp and bsp[0]["n"]:
            roi2 = bsp[0]["by_comm"]["2%"]["roi"]
            if roi2 is not None and roi2 > 0.01:
                a("  On this test, backing every horse whose BSP was longer than our fair")
                a(f"  odds made a profit after 2% commission ({fmt_roi(roi2)}). That is not a guarantee.")
            else:
                a("  On this test there was no clear edge: backing when BSP was longer than")
                a("  our fair odds was not profitable after commission. Treat the win % as a")
                a("  form guide to compare with the live price, not as a ready-made bet.")
    else:
        a("  No priced runners in the test window, so the value check was skipped.")
    a("")
    a("Today's cards")
    a("-" * 72)
    a(f"  Scored {today_n} runners in {today_races} races.")
    a("  Stored in data\\site_cache.sqlite (win_pct table and fig_meta keys)")
    a("  and data\\predict_today\\win_pct_today.json.")
    a("  Re-run this script with --score-only (or PREDICT_TODAY.bat) after new cards.")
    a("")
    a("Notes")
    a("-" * 72)
    a("- Fair odds are 1 / win probability, shown as a decimal (for example 5.50).")
    a("- Compare with the live price: if the price is bigger than our fair odds,")
    a("  it may be value. The test above says whether that rule actually paid.")
    coef = list(zip(payload.get("features") or FEATURES, payload.get("coef") or []))
    coef.sort(key=lambda kv: abs(kv[1]), reverse=True)
    if coef:
        a("- Largest weights (standardised features):")
        for k, v in coef[:8]:
            a(f"    {k:<16} {v:+.3f}")
    text = "\n".join(lines) + "\n"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(text, encoding="utf-8")
    return text


def load_form_model() -> dict:
    src = pt.MODEL_PATH if pt.MODEL_PATH.is_file() else pt.BUNDLE_PATH
    if not src.is_file():
        fail("No predicted-today model found. Run PREDICT_TODAY.bat once first.")
    payload = json.loads(src.read_text(encoding="utf-8"))
    models = payload.get("models") or {}
    form = (models.get("form") or models.get("all") or {}).get("model")
    if not form:
        fail("The predicted-today model file has no 'form' (or 'all') block.")
    return form


def load_win_model() -> dict:
    if not MODEL_PATH.is_file():
        fail(f"No trained win-% model at {MODEL_PATH}. Run tools\\win_pct.py once without --score-only.")
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def train(test_start: str | None = None) -> dict:
    form_model = load_form_model()
    src = pt.find_csv()
    df = pt.load_csv(src)
    max_date = str(df["date"].max())
    if not test_start:
        # Same split as Predicted today: latest 12 months held out.
        pred_payload_path = pt.MODEL_PATH if pt.MODEL_PATH.is_file() else pt.BUNDLE_PATH
        try:
            test_start = json.loads(pred_payload_path.read_text(encoding="utf-8")).get("test_start")
        except Exception:
            test_start = None
        if not test_start:
            test_start = str(pd.Timestamp(max_date) - pd.DateOffset(years=1))[:10]
    log(f"Building win-probability features (test from {test_start})… this is the slow step.")
    pace_map = load_pace_map()
    t1 = time.time()
    feat = build_win_dataset(df, pace_map)
    log(f"  {len(feat):,} runner-rows in {time.time() - t1:.1f}s")
    log("  Scoring each run with the form-only predicted-today model…")
    feat["pred"] = apply_pred(feat, form_model)
    log("  Adding within-race features…")
    feat = add_race_features(feat)
    feat = eligible_races(feat)
    train_df = feat[feat["date"] < test_start].copy()
    test_df = feat[feat["date"] >= test_start].copy()
    if len(train_df) < 5000 or train_df["race_id"].nunique() < 200:
        fail(f"Not enough train races ({len(train_df):,} rows, {train_df['race_id'].nunique():,} races).")
    Xtr, mean, std = standardize(matrix_win(train_df))
    ytr = (train_df["place"] == 1).to_numpy(float)
    rtr = train_df["race_id"].to_numpy()
    log("Training conditional logit…")
    beta = fit_clogit(Xtr, rtr, ytr, LAM)
    model = {
        "version": "win_pct_v1",
        "trained": time.strftime("%Y-%m-%d %H:%M"),
        "test_start": test_start,
        "max_date": max_date,
        "features": FEATURES,
        "mean": [float(x) for x in mean],
        "std": [float(x) for x in std],
        "coef": [float(x) for x in beta],
        "lam": LAM,
        "n_train_rows": int(len(train_df)),
        "n_train_races": int(train_df["race_id"].nunique()),
        "n_test_rows": int(len(test_df)),
        "n_test_races": int(test_df["race_id"].nunique()),
    }
    # Evaluate on the held-out year
    test_df = test_df.copy()
    test_df["p"] = predict_proba(test_df, model)
    top, top_n = top_pick_rate(test_df, "p")
    top_pred, top_pred_n = top_pick_rate(test_df.assign(p=test_df["pred_fill"]), "p")
    cal = calibration(test_df)
    prices = load_eval_prices()
    test_df = attach_prices(test_df, prices)
    bsp_cov = float(test_df["bsp"].notna().mean()) if len(test_df) else 0.0
    p5_cov = float(test_df["p5"].notna().mean()) if len(test_df) else 0.0
    value = value_report(test_df, "bsp") + value_report(test_df, "p5")
    # favourite strike rate on priced races
    fav_hits = fav_n = 0
    for rid, g in test_df.groupby("race_id", sort=False):
        gg = g.dropna(subset=["bsp"])
        if len(gg) < 2 or not (g["place"] == 1).any():
            continue
        fav_n += 1
        fav = gg[gg["bsp"] == gg["bsp"].min()]
        if (fav["place"] == 1).any():
            fav_hits += 1
    model["eval"] = {
        "top_rate": top, "top_n": top_n,
        "top_pred_rate": top_pred, "top_pred_n": top_pred_n,
        "fav_rate": (fav_hits / fav_n) if fav_n else None,
        "fav_n": fav_n,
        "calibration": cal,
        "value": value,
        "bsp_cov": bsp_cov,
        "p5_cov": p5_cov,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.write_text(json.dumps(model, indent=2), encoding="utf-8")
    log(f"Wrote model to {MODEL_PATH}")
    log(f"  Top-pick strike rate: {fmt_pct(top)} of {top_n:,} test races")
    log(f"  BSP coverage: {fmt_pct(bsp_cov, 0)}; 5-minute coverage: {fmt_pct(p5_cov, 0)}")
    return model


def score_cards(model: dict, date: str | None) -> list[dict]:
    if not CARDS.is_file():
        fail(f"Missing {CARDS}. Run GET_TODAYS_CARDS.bat first.")
    if not CACHE.is_file():
        fail(f"Missing {CACHE}. Run npm run figures (or RUN_SITE.bat) first.")
    form_model = load_form_model()
    pace_map = load_pace_map()

    cards = sqlite3.connect(f"file:{CARDS}?mode=ro", uri=True)
    cards.row_factory = sqlite3.Row
    dates = [r[0] for r in cards.execute("SELECT DISTINCT date FROM races ORDER BY date DESC")]
    if not dates:
        fail("No races in cards.sqlite.")
    if date is None:
        date = str(dates[0])
    elif date not in {str(d) for d in dates}:
        fail(f"No cards for {date}. Available: {', '.join(str(d) for d in dates[:8])}")
    races = [dict(r) for r in cards.execute("SELECT * FROM races WHERE date=? ORDER BY time", (date,))]
    runners = [dict(r) for r in cards.execute("SELECT * FROM runners WHERE date=? ORDER BY race_id, cloth", (date,))]
    cards.close()
    log(f"Scoring win % for {len(runners)} runners in {len(races)} races on {date}…")

    cache = sqlite3.connect(f"file:{CACHE}?mode=ro", uri=True)
    cache.row_factory = sqlite3.Row
    norms = sorted({r["horse_norm"] for r in runners if r.get("horse_norm")})
    figs_by: dict[str, list[dict]] = {n: [] for n in norms}
    if norms:
        q = "SELECT horse_norm,race_id,date,foal_year,course,code,surface,dist,dist_f,going,cls,pos,beaten,ran,offr,fig,fig2 FROM figs WHERE horse_norm IN ({}) AND date<? ORDER BY date".format(
            ",".join("?" * len(norms))
        )
        for r in cache.execute(q, [*norms, date]):
            figs_by[r["horse_norm"]].append(dict(r))
    cache.close()

    recs = []
    for h in runners:
        race = next((r for r in races if r["race_id"] == h["race_id"]), None)
        if not race:
            continue
        low = str(race.get("name") or "").lower()
        if "chase" in low:
            fam = "Chase"
        elif "hurdle" in low:
            fam = "Hurdle"
        elif any(k in low for k in ("bumper", "national hunt flat", "nh flat", "inh flat")):
            fam = "NHF"
        else:
            fam = "Flat"
        going = race.get("going")
        aw = str(race.get("surface") or "").upper().startswith("ALL") or (pt.STD_RE.search(str(going or "")) is not None)
        code = pt.code_of(fam, "AW" if aw else race.get("surface"))
        dist_f = None
        d = str(race.get("distance") or "")
        m, f, y = pt.re.search(r"(\d+)\s*m", d, pt.re.I), pt.re.search(r"(\d+)\s*f", d, pt.re.I), pt.re.search(r"(\d+)\s*y", d, pt.re.I)
        if m or f or y:
            dist_f = (int(m.group(1)) * 8 if m else 0) + (int(f.group(1)) if f else 0) + (0.5 if "½" in d else 0) + ((int(y.group(1)) / 220) if y else 0)
        hist = pt.hist_from_figs(figs_by.get(h.get("horse_norm") or "", []), "fig")
        today = {
            "date": date, "code": code, "aw": code == "AW" or aw,
            "surface": race.get("surface"), "dist_f": dist_f, "going": going,
            "going_n": pt.going_n(going), "cls": pt.cls_n(race.get("race_class")),
            "age": h.get("age"), "or_": h.get("official_rating"), "days": h.get("last_ran_days"),
        }
        feat = pt.features_from_hist(hist, today, fig_key="fig")
        nr = str(h.get("status") or "RUNNER").upper() not in {"RUNNER", ""}
        rec = {
            "ride_id": int(h["ride_id"]),
            "race_id": int(h["race_id"]),
            "date": date,
            "horse": h.get("horse"),
            "horse_norm": h.get("horse_norm"),
            "cloth": h.get("cloth"),
            "nr": nr,
            "place": None,
            "has_form": 0.0,
            "pred": None,
            "best3_raw": None,
            "last_raw": None,
            "last_adj": None,
            "wmean_adj": None,
            "best3_adj": None,
            "last_rel": "",
            "code": code,
        }
        if feat and not nr:
            rec.update({k: feat[k] for k in feat})
            rec["has_form"] = 1.0
            rec["best3_raw"] = feat.get("best3_raw")
            rec["last_raw"] = feat.get("last_raw")
            last_adj, wmean_adj, best3_adj, last_rel = adj_from_hist(hist, today, pace_map, "fig")
            rec["last_adj"] = last_adj
            rec["wmean_adj"] = wmean_adj
            rec["best3_adj"] = best3_adj
            rec["last_rel"] = last_rel
            feat_use = dict(feat)
            feat_use["or_today"] = 0.0
            feat_use["or_chg"] = 0.0
            feat_use["has_or"] = 0.0
            rec["pred"] = pt.predict_row(form_model, feat_use)
        recs.append(rec)

    feat = pd.DataFrame.from_records(recs)
    if feat.empty:
        return []
    # Softmax over active (non-NR) runners only; NRs get no percentage.
    active = feat.loc[~feat["nr"]].copy()
    if active.empty:
        return []
    active = add_race_features(active)
    p = predict_proba(active, model)
    # Numerical cleanup: renormalise per race to sum to 1
    active = active.copy()
    active["p"] = p
    active["p"] = active.groupby("race_id")["p"].transform(lambda s: s / s.sum() if s.sum() else s)
    out = []
    for rid, g in active.groupby("race_id", sort=False):
        g = g.sort_values("p", ascending=False)
        for i, (_, r) in enumerate(g.iterrows(), 1):
            wp = float(r["p"])
            fair = round(1.0 / wp, 2) if wp > 0 else None
            if fair is not None:
                fair = max(1.01, min(fair, 999.0))
            out.append({
                "ride_id": int(r["ride_id"]),
                "race_id": int(r["race_id"]),
                "date": r["date"],
                "horse_norm": r.get("horse_norm"),
                "horse": r.get("horse"),
                "win_pct": round(100.0 * wp, 1),
                "fair_odds": fair,
                "win_rank": i,
            })
    return out


def save_scores(rows: list[dict], model: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TODAY_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if not CACHE.is_file():
        log(f"Saved {len(rows)} win-% rows to {TODAY_PATH} (no site_cache.sqlite to update)")
        return
    con = sqlite3.connect(CACHE)
    con.execute(
        """CREATE TABLE IF NOT EXISTS win_pct (
            ride_id INTEGER PRIMARY KEY,
            race_id INTEGER,
            date TEXT,
            horse_norm TEXT,
            horse TEXT,
            win_pct REAL,
            fair_odds REAL,
            win_rank INTEGER
        )"""
    )
    dates = {r["date"] for r in rows}
    for d in dates:
        con.execute("DELETE FROM win_pct WHERE date=?", (d,))
    cols = ["ride_id", "race_id", "date", "horse_norm", "horse", "win_pct", "fair_odds", "win_rank"]
    con.executemany(
        f"INSERT INTO win_pct ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r.get(c) for c in cols) for r in rows],
    )
    con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    slim_model = {k: model[k] for k in model if k != "eval"}
    if "eval" in model:
        # keep eval in the file, a compact copy in meta (no huge arrays)
        slim_model["eval"] = model["eval"]
    meta = {
        "win_pct_built": time.strftime("%Y-%m-%d %H:%M"),
        "win_pct_version": model.get("version", "win_pct_v1"),
        "win_pct_model": json.dumps(slim_model, separators=(",", ":")),
        "win_pct_today": json.dumps(rows, separators=(",", ":")),
    }
    con.executemany("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", meta.items())
    con.commit()
    con.close()
    log(f"Saved {len(rows)} win-% rows to {CACHE} (win_pct + meta) and {TODAY_PATH}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train and score FurlongIQ form-only win probabilities.")
    ap.add_argument("--score-only", action="store_true", help="Skip training; score today's cards with the saved model.")
    ap.add_argument("--train", action="store_true", help="Force a retrain even if a model already exists.")
    ap.add_argument("--date", help="Card date to score (default: latest date in cards.sqlite).")
    args = ap.parse_args()
    t0 = time.time()

    if args.score_only and not args.train:
        if not MODEL_PATH.is_file():
            log("No win-% model yet — skipping score. Run: python tools\\win_pct.py")
            return
        model = load_win_model()
        log(f"Loaded win-% model trained {model.get('trained')} from {MODEL_PATH}")
    else:
        model = train()

    rows = score_cards(model, args.date)
    save_scores(rows, model)
    races = len({r["race_id"] for r in rows})
    text = write_summary(model, len(rows), races)
    log("")
    log(text.rstrip())
    log("")
    log(f"Done in {time.time()-t0:.1f}s. Summary: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
