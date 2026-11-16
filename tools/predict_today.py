#!/usr/bin/env python3
r"""
Predicted-today speed figures for FurlongIQ.

Trains a ridge model on v3 speed figures using only information known before
each historical run, tests it on the latest ~12 months, then scores today's
race-card runners.

Usage (from the Speeds folder):
    python tools\predict_today.py
    python tools\predict_today.py --score-only
    python tools\predict_today.py --date 2026-11-16
"""
from __future__ import annotations

import argparse, json, math, os, re, sqlite3, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "site_cache.sqlite"
CARDS = DATA / "cards.sqlite"
OUT_DIR = DATA / "predict_today"
MODEL_PATH = OUT_DIR / "model.json"
BUNDLE_PATH = ROOT / "web" / "src" / "lib" / "pred-model.json"
SUMMARY_PATH = OUT_DIR / "summary.txt"
TODAY_PATH = OUT_DIR / "today.json"

CSV_CANDIDATES = [
    DATA / "speed_v3" / "speed_figures.csv",
    DATA / "speed_v2" / "speed_figures.csv",
    DATA / "speed_v1" / "speed_figures.csv",
]
PRICE_CANDIDATES = [
    DATA / "rbd_prices.csv.gz",
    ROOT / "rbd_prices.csv.gz",
    DATA / "rbd" / "rbd_prices.csv.gz",
]

JUMPS = {"Hurdle", "Chase", "NHF"}
STD_RE = re.compile(r"standard|slow|fast|polytrack|tapeta", re.I)
GOING_TABLE = [
    ("soft to heavy", 5.5), ("yielding to soft", 4.5), ("good to yielding", 3.5),
    ("good to soft", 4), ("good to firm", 2),
    ("heavy", 6), ("soft", 5), ("yielding", 4), ("good", 3), ("firm", 1),
]
USECOLS = [
    "race_id", "date", "off_time", "course", "surface", "code", "dist_f", "going",
    "class", "horse", "age", "offr", "place", "weighted_fig", "fig_2yo_weighted",
    "horse_norm", "yob", "horse_id",
]
# Feature order is part of the model file — keep stable.
FEATURES = [
    "last", "last2", "last3", "wmean", "best3", "trend",
    "n_runs", "light", "age", "days", "log_days",
    "cls", "cls_chg_last", "cls_chg_avg3",
    "or_today", "or_chg",
    "same_code", "same_surf", "dist_diff", "going_diff", "going_match",
    "sim_mean", "n_sim",
    "is_flat", "is_aw", "is_hurdle", "is_chase", "is_nhf",
    "has_last2", "has_last3", "has_or", "has_cls", "has_sim", "has_days", "has_trend",
]
LAM = 8.0
FLOOR, CEIL = 45.0, 180.0


def log(msg: str = "") -> None:
    print(msg, flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def norm_name(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def going_n(g) -> float | None:
    s = str(g or "").lower().replace(r"(.*", " ").split("(")[0].strip()
    if not s or STD_RE.search(s):
        return None
    for k, v in GOING_TABLE:
        if s.startswith(k):
            return v
    return None


def code_of(code, surface) -> str:
    c = str(code or "").strip()
    if c in JUMPS:
        return c
    surf = str(surface or "").lower()
    if surf.startswith("aw") or "all weather" in surf or "all-weather" in surf:
        return "AW"
    if c.lower() in {"flat", "aw"}:
        return "AW" if c.lower() == "aw" or surf.startswith("aw") else "Flat"
    if "chase" in c.lower():
        return "Chase"
    if "hurdle" in c.lower():
        return "Hurdle"
    if "nhf" in c.lower() or "bumper" in c.lower():
        return "NHF"
    return "AW" if surf.startswith("aw") else (c or "Flat")


def is_jumps(code: str) -> bool:
    return code in JUMPS


def cls_n(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        s = str(v or "")
        m = re.search(r"(\d+)", s)
        n = float(m.group(1)) if m else None
    if n is None or not math.isfinite(n) or n <= 0:
        return None
    return n


def find_csv() -> Path:
    for p in CSV_CANDIDATES:
        if p.is_file():
            return p
    fail("No speed_figures.csv found in data\\speed_v3 (or speed_v2). Run RUN_SPEED_FIGURES_V3.bat first.")
    raise AssertionError


def find_prices() -> Path | None:
    for p in PRICE_CANDIDATES:
        if p.is_file():
            return p
    return None


def slope(ys: list[float]) -> float | None:
    n = len(ys)
    if n < 3:
        return None
    xs = np.arange(n, dtype=float)
    y = np.asarray(ys, dtype=float)
    xm, ym = xs.mean(), y.mean()
    den = ((xs - xm) ** 2).sum()
    if den <= 0:
        return 0.0
    return float(((xs - xm) * (y - ym)).sum() / den)


def features_from_hist(hist: list[dict], today: dict, fig_key: str = "fig") -> dict | None:
    """Build one feature row from prior runs only. hist is oldest -> newest."""
    if not hist:
        return None
    fam = is_jumps(today["code"])
    pool_all = [r for r in hist if r.get(fig_key) is not None]
    pool_fam = [r for r in pool_all if is_jumps(r["code"]) == fam]
    pool = pool_fam or pool_all
    if not pool:
        return None

    recent = pool[-12:]
    last = recent[-1][fig_key]
    last2 = recent[-2][fig_key] if len(recent) > 1 else None
    last3 = recent[-3][fig_key] if len(recent) > 2 else None
    tail = recent[-8:]
    decay = [0.7 ** (len(tail) - 1 - i) for i in range(len(tail))]
    wmean = sum(w * r[fig_key] for w, r in zip(decay, tail)) / sum(decay)
    top3 = sorted((r[fig_key] for r in recent), reverse=True)[:3]
    best3 = sum(top3) / len(top3)
    tr = [r[fig_key] for r in recent[-6:]]
    trend = slope(tr)

    last_run = hist[-1]
    days = None
    if today.get("date") is not None and last_run.get("date") is not None:
        try:
            days = int((pd.Timestamp(today["date"]) - pd.Timestamp(last_run["date"])).days)
        except Exception:
            days = today.get("days")
    if days is not None:
        days = max(0, min(int(days), 500))

    t_cls = cls_n(today.get("cls"))
    last_cls_runs = [r for r in reversed(hist) if r.get("cls") is not None and is_jumps(r["code"]) == fam]
    if not last_cls_runs:
        last_cls_runs = [r for r in reversed(hist) if r.get("cls") is not None]
    last_cls = last_cls_runs[0]["cls"] if last_cls_runs else None
    avg3_src = last_cls_runs[:3]
    avg3_cls = (sum(r["cls"] for r in avg3_src) / len(avg3_src)) if avg3_src else None
    cls_chg_last = (t_cls - last_cls) if (t_cls is not None and last_cls is not None) else None
    cls_chg_avg3 = (t_cls - avg3_cls) if (t_cls is not None and avg3_cls is not None) else None

    t_or = today.get("or_")
    if t_or is not None:
        try:
            t_or = float(t_or)
            if not math.isfinite(t_or):
                t_or = None
        except (TypeError, ValueError):
            t_or = None
    last_or_runs = [r for r in reversed(hist) if r.get("or_") is not None and is_jumps(r["code"]) == fam]
    if not last_or_runs:
        last_or_runs = [r for r in reversed(hist) if r.get("or_") is not None]
    last_or = last_or_runs[0]["or_"] if last_or_runs else None
    or_chg = (t_or - last_or) if (t_or is not None and last_or is not None) else None

    trips = [r["dist_f"] for r in pool if r.get("dist_f") is not None]
    avg_trip = sum(trips) / len(trips) if trips else None
    t_dist = today.get("dist_f")
    dist_diff = (t_dist - avg_trip) if (t_dist is not None and avg_trip is not None) else None

    t_go, t_aw = today.get("going_n"), bool(today.get("aw"))
    last_go, last_aw = last_run.get("going_n"), bool(last_run.get("aw"))
    if t_aw or last_aw:
        going_match = 1.0 if t_aw and last_aw else 0.0
        going_diff = 0.0 if (t_aw and last_aw) else 2.0
    elif t_go is not None and last_go is not None:
        going_diff = abs(t_go - last_go)
        going_match = 1.0 if going_diff <= 1 else 0.0
    else:
        going_diff = None
        going_match = 0.0

    sim = []
    for r in pool:
        rd, rg, raw = r.get("dist_f"), r.get("going_n"), bool(r.get("aw"))
        if t_dist is None or rd is None:
            dist_ok = False
        else:
            dist_ok = abs(rd - t_dist) <= max(1.0, t_dist * 0.1) + 1e-6
        if t_aw or raw:
            go_ok = bool(t_aw and raw)
        elif t_go is not None and rg is not None:
            go_ok = abs(rg - t_go) <= 1
        else:
            go_ok = False
        if dist_ok and go_ok:
            sim.append(r[fig_key])
    sim_mean = (sum(sim) / len(sim)) if sim else None

    code = today["code"]
    last_code, last_surf = last_run.get("code"), last_run.get("surface")
    same_code = 1.0 if last_code == code else 0.0
    same_surf = 1.0 if (bool(last_run.get("aw")) == t_aw) else 0.0

    age = today.get("age")
    try:
        age = float(age) if age is not None and math.isfinite(float(age)) else None
    except (TypeError, ValueError):
        age = None

    n_runs = len(pool)
    fill_last2 = last2 if last2 is not None else last
    fill_last3 = last3 if last3 is not None else fill_last2

    return {
        "last": last,
        "last2": fill_last2,
        "last3": fill_last3,
        "wmean": wmean,
        "best3": best3,
        "trend": trend if trend is not None else 0.0,
        "n_runs": n_runs,
        "light": 1.0 if n_runs < 8 else 0.0,
        "age": age if age is not None else 5.0,
        "days": days if days is not None else 30.0,
        "log_days": math.log1p(days if days is not None else 30.0),
        "cls": t_cls if t_cls is not None else 4.0,
        "cls_chg_last": cls_chg_last if cls_chg_last is not None else 0.0,
        "cls_chg_avg3": cls_chg_avg3 if cls_chg_avg3 is not None else 0.0,
        "or_today": t_or if t_or is not None else 0.0,
        "or_chg": or_chg if or_chg is not None else 0.0,
        "same_code": same_code,
        "same_surf": same_surf,
        "dist_diff": dist_diff if dist_diff is not None else 0.0,
        "going_diff": going_diff if going_diff is not None else 1.0,
        "going_match": going_match,
        "sim_mean": sim_mean if sim_mean is not None else wmean,
        "n_sim": len(sim),
        "is_flat": 1.0 if code == "Flat" else 0.0,
        "is_aw": 1.0 if code == "AW" else 0.0,
        "is_hurdle": 1.0 if code == "Hurdle" else 0.0,
        "is_chase": 1.0 if code == "Chase" else 0.0,
        "is_nhf": 1.0 if code == "NHF" else 0.0,
        "has_last2": 1.0 if last2 is not None else 0.0,
        "has_last3": 1.0 if last3 is not None else 0.0,
        "has_or": 1.0 if t_or is not None else 0.0,
        "has_cls": 1.0 if t_cls is not None else 0.0,
        "has_sim": 1.0 if sim else 0.0,
        "has_days": 1.0 if days is not None else 0.0,
        "has_trend": 1.0 if trend is not None else 0.0,
        "best3_raw": best3,
        "last_raw": last,
    }


def row_from_csv(r: pd.Series) -> dict:
    surf = r["surface"]
    code = code_of(r["code"], surf)
    aw = code == "AW" or str(surf or "").lower().startswith("aw")
    fig = r["weighted_fig"]
    fig = float(fig) if pd.notna(fig) else None
    fig2 = r["fig_2yo_weighted"]
    fig2 = float(fig2) if pd.notna(fig2) else None
    offr = r["offr"]
    offr = float(offr) if pd.notna(offr) else None
    dist = r["dist_f"]
    dist = float(dist) if pd.notna(dist) else None
    age = r["age"]
    age = float(age) if pd.notna(age) else None
    place = r["place"]
    try:
        place = int(place) if pd.notna(place) else None
    except (TypeError, ValueError):
        place = None
    return {
        "race_id": r["race_id"],
        "date": r["date"],
        "off_time": r.get("off_time"),
        "course": r.get("course"),
        "horse": r.get("horse"),
        "horse_id": r["horse_id"],
        "horse_norm": r["horse_norm"],
        "surface": surf,
        "code": code,
        "aw": aw,
        "dist_f": dist,
        "going": r.get("going"),
        "going_n": going_n(r.get("going")),
        "cls": cls_n(r.get("class")),
        "age": age,
        "or_": offr,
        "place": place,
        "fig": fig,
        "fig2": fig2,
    }


def build_dataset(df: pd.DataFrame, fig_key: str = "fig") -> pd.DataFrame:
    """Walk each horse's history and emit one feature row per run that has a target and prior figs."""
    recs = []
    for horse_id, g in df.groupby("horse_id", sort=False):
        hist: list[dict] = []
        for _, r in g.iterrows():
            row = row_from_csv(r)
            key = fig_key
            feat = features_from_hist(hist, row, fig_key=("fig" if key == "fig" else "fig2"))
            y = row["fig"] if fig_key == "fig" else row["fig2"]
            if feat is not None and y is not None:
                feat["y"] = y
                feat["place"] = row["place"]
                feat["race_id"] = row["race_id"]
                feat["date"] = str(row["date"])[:10]
                feat["horse_id"] = horse_id
                feat["horse_norm"] = row["horse_norm"]
                feat["horse"] = row["horse"]
                feat["course"] = row["course"]
                feat["off_time"] = row["off_time"]
                recs.append(feat)
            hist.append(row)
    if not recs:
        return pd.DataFrame()
    return pd.DataFrame.from_records(recs)


def fit_ridge(X: np.ndarray, y: np.ndarray, lam: float = LAM) -> np.ndarray:
    n, p = X.shape
    Xb = np.column_stack([np.ones(n), X])
    A = Xb.T @ Xb
    I = np.eye(p + 1)
    I[0, 0] = 0.0
    A = A + lam * I
    b = Xb.T @ y
    try:
        return np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(A, b, rcond=None)[0]


def apply_ridge(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    return Xb @ w


def standardize(X: np.ndarray, mean: np.ndarray | None = None, std: np.ndarray | None = None):
    if mean is None:
        mean = X.mean(axis=0)
    if std is None:
        std = X.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    return (X - mean) / std, mean, std


def matrix(df: pd.DataFrame) -> np.ndarray:
    return df[FEATURES].to_numpy(dtype=float)


def mae(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.mean(np.abs(a[m] - b[m]))) if m.any() else float("nan")


def clip_pred(p: np.ndarray) -> np.ndarray:
    return np.clip(p, FLOOR, CEIL)


def train_one(feat: pd.DataFrame, label: str, test_start: str) -> dict:
    feat = feat.copy()
    feat["date"] = feat["date"].astype(str).str[:10]
    train = feat[feat["date"] < test_start]
    test = feat[feat["date"] >= test_start]
    if len(train) < 1000 or len(test) < 200:
        fail(f"{label}: not enough rows to train ({len(train):,} train, {len(test):,} test).")

    Xtr_raw, ytr = matrix(train), train["y"].to_numpy(float)
    Xte_raw, yte = matrix(test), test["y"].to_numpy(float)
    Xtr, mean, std = standardize(Xtr_raw)
    Xte, _, _ = standardize(Xte_raw, mean, std)
    w = fit_ridge(Xtr, ytr, LAM)
    pred_tr = clip_pred(apply_ridge(w, Xtr))
    pred_te = clip_pred(apply_ridge(w, Xte))
    resid = yte - pred_te
    resid_std = float(np.std(resid))
    resid_mae = mae(yte, pred_te)
    # 50%-ish band
    band = float(np.quantile(np.abs(resid), 0.5)) if len(resid) else resid_mae

    naive_last = test["last_raw"].to_numpy(float)
    naive_b3 = test["best3_raw"].to_numpy(float)
    metrics = {
        "label": label,
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "test_start": test_start,
        "train_mae": round(mae(ytr, pred_tr), 3),
        "test_mae": round(resid_mae, 3),
        "test_mae_last": round(mae(yte, naive_last), 3),
        "test_mae_best3": round(mae(yte, naive_b3), 3),
        "residual_std": round(resid_std, 3),
        "band": round(band, 2),
    }
    model = {
        "features": FEATURES,
        "mean": [round(float(x), 6) for x in mean],
        "std": [round(float(x), 6) for x in std],
        "intercept": round(float(w[0]), 6),
        "coef": [round(float(x), 6) for x in w[1:]],
        "lam": LAM,
        "band": metrics["band"],
        "residual_std": metrics["residual_std"],
        "residual_mae": metrics["test_mae"],
    }
    test = test.copy()
    test["pred"] = pred_te
    return {"model": model, "metrics": metrics, "test": test}


def top_hit_rate(test: pd.DataFrame, col: str) -> tuple[float, int]:
    """Share of races where a horse tied for the top of `col` actually won."""
    hits = races = 0
    for rid, g in test.groupby("race_id", sort=False):
        if g["place"].isna().all():
            continue
        gg = g.dropna(subset=[col])
        if len(gg) < 2 or not (gg["place"] == 1).any():
            continue
        top = gg[col].max()
        leaders = gg[gg[col] >= top - 1e-9]
        races += 1
        if (leaders["place"] == 1).any():
            hits += 1
    return (hits / races if races else float("nan"), races)


def favourite_hit_rate(test: pd.DataFrame, prices: pd.DataFrame | None) -> tuple[float, int, float]:
    """Favourite (lowest BSP) win rate on test races, plus coverage."""
    if prices is None or prices.empty:
        return float("nan"), 0, 0.0
    t = test[["race_id", "date", "horse_norm", "place", "course", "off_time"]].copy()
    t["date"] = t["date"].astype(str).str[:10]
    t["horse_norm"] = t["horse_norm"].astype(str)
    p = prices.copy()
    p["date"] = p["date"].astype(str).str[:10]
    p["horse_norm"] = p["horse"].map(norm_name)
    merged = t.merge(p[["date", "horse_norm", "bsp"]], on=["date", "horse_norm"], how="left")
    # if a horse matched more than once that day, keep the row with a bsp closest... just first
    merged = merged.drop_duplicates(["race_id", "horse_norm"], keep="first")
    cov = float(merged["bsp"].notna().mean())
    hits = races = 0
    for rid, g in merged.groupby("race_id", sort=False):
        gg = g.dropna(subset=["bsp"])
        if len(gg) < 2 or not (g["place"] == 1).any():
            continue
        fav = gg[gg["bsp"] == gg["bsp"].min()]
        races += 1
        if (fav["place"] == 1).any():
            hits += 1
    return (hits / races if races else float("nan"), races, cov)


def load_prices() -> pd.DataFrame | None:
    p = find_prices()
    if not p:
        log("No RBD prices file found — favourite comparison will be skipped.")
        return None
    log(f"Loading prices from {p} for the favourite comparison…")
    df = pd.read_csv(p, usecols=["date", "time", "course", "horse", "bsp"], low_memory=False)
    df = df[pd.to_numeric(df["bsp"], errors="coerce").notna()].copy()
    df["bsp"] = pd.to_numeric(df["bsp"], errors="coerce")
    log(f"  {len(df):,} priced runners")
    return df


def load_csv(path: Path) -> pd.DataFrame:
    log(f"Loading {path} ({path.stat().st_size / 1e6:.0f} MB)…")
    df = pd.read_csv(path, usecols=lambda c: c in USECOLS, low_memory=False)
    df["date"] = df["date"].astype(str).str[:10]
    df = df.sort_values(["horse_id", "date", "off_time"], kind="mergesort")
    log(f"  {len(df):,} runs, {df['horse_id'].nunique():,} horses, {df['date'].min()} → {df['date'].max()}")
    return df


def predict_row(model: dict, feat: dict) -> float:
    x = np.array([feat[k] for k in model["features"]], dtype=float)
    mean = np.array(model["mean"], dtype=float)
    std = np.array(model["std"], dtype=float)
    std = np.where(std < 1e-8, 1.0, std)
    z = (x - mean) / std
    p = model["intercept"] + float(z @ np.array(model["coef"], dtype=float))
    return float(np.clip(p, FLOOR, CEIL))


def load_model(path: Path) -> dict:
    if not path.is_file():
        fail(f"No trained model at {path}. Run PREDICT_TODAY.bat once without --score-only.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_model(payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2)
    MODEL_PATH.write_text(text, encoding="utf-8")
    BUNDLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE_PATH.write_text(text, encoding="utf-8")
    log(f"Wrote model to {MODEL_PATH} and {BUNDLE_PATH.relative_to(ROOT)}")


def hist_from_figs(rows: list[dict], fig_key: str) -> list[dict]:
    """Normalise site-cache / cards figure rows to the hist schema, oldest first."""
    out = []
    for r in rows:
        code = code_of(r.get("code"), r.get("surface"))
        aw = code == "AW" or str(r.get("surface") or "").lower().startswith("aw")
        fig = r.get("fig") if fig_key == "fig" else r.get("fig2")
        try:
            fig = float(fig) if fig is not None and str(fig) != "" else None
        except (TypeError, ValueError):
            fig = None
        dist = r.get("dist_f")
        try:
            dist = float(dist) if dist is not None and str(dist) != "" else None
        except (TypeError, ValueError):
            dist = None
        item = {
            "date": str(r.get("date") or "")[:10],
            "code": code,
            "aw": aw,
            "surface": r.get("surface"),
            "dist_f": dist,
            "going": r.get("going"),
            "going_n": going_n(r.get("going")),
            "cls": cls_n(r.get("cls") if "cls" in r else r.get("class")),
            "or_": None,
            "fig": None,
            "fig2": None,
        }
        offr = r.get("offr")
        try:
            item["or_"] = float(offr) if offr is not None and str(offr) != "" else None
        except (TypeError, ValueError):
            item["or_"] = None
        item[fig_key] = fig
        # keep both when present so fallbacks work
        if fig_key == "fig":
            try:
                item["fig2"] = float(r["fig2"]) if r.get("fig2") is not None and str(r.get("fig2")) != "" else None
            except (TypeError, ValueError):
                item["fig2"] = None
        else:
            try:
                item["fig"] = float(r["fig"]) if r.get("fig") is not None and str(r.get("fig")) != "" else None
            except (TypeError, ValueError):
                item["fig"] = None
        out.append(item)
    out.sort(key=lambda r: r["date"])
    return out


def score_cards(model_payload: dict, date: str | None) -> list[dict]:
    if not CARDS.is_file():
        fail(f"Missing {CARDS}. Run GET_TODAYS_CARDS.bat first.")
    if not CACHE.is_file():
        fail(f"Missing {CACHE}. Run npm run figures (or RUN_SITE.bat) first.")

    cards = sqlite3.connect(f"file:{CARDS}?mode=ro", uri=True)
    cards.row_factory = sqlite3.Row
    dates = [r[0] for r in cards.execute("SELECT DISTINCT date FROM races ORDER BY date DESC")]
    if not dates:
        fail("No races in cards.sqlite.")
    if date is None:
        date = str(dates[0])
    elif date not in dates:
        fail(f"No cards for {date}. Available: {', '.join(dates[:8])}")

    races = [dict(r) for r in cards.execute("SELECT * FROM races WHERE date=? ORDER BY time", (date,))]
    runners = [dict(r) for r in cards.execute("SELECT * FROM runners WHERE date=? ORDER BY race_id, cloth", (date,))]
    cards.close()
    log(f"Scoring {len(runners)} runners in {len(races)} races on {date}…")

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

    models = model_payload["models"]
    out = []
    by_race: dict[int, list] = {}
    for h in runners:
        race = next((r for r in races if r["race_id"] == h["race_id"]), None)
        if not race:
            continue
        fam_name = race.get("name") or ""
        # race family from the race name, matching the site
        low = fam_name.lower()
        if "chase" in low:
            fam = "Chase"
        elif "hurdle" in low:
            fam = "Hurdle"
        elif any(k in low for k in ("bumper", "national hunt flat", "nh flat", "inh flat")):
            fam = "NHF"
        else:
            fam = "Flat"
        going = race.get("going")
        aw = str(race.get("surface") or "").upper().startswith("ALL") or (STD_RE.search(str(going or "")) is not None)
        code = code_of(fam, "AW" if aw else race.get("surface"))
        # distance: parse if needed
        dist_f = None
        d = str(race.get("distance") or "")
        m, f, y = re.search(r"(\d+)\s*m", d, re.I), re.search(r"(\d+)\s*f", d, re.I), re.search(r"(\d+)\s*y", d, re.I)
        if m or f or y:
            dist_f = (int(m.group(1)) * 8 if m else 0) + (int(f.group(1)) if f else 0) + (0.5 if "½" in d else 0) + ((int(y.group(1)) / 220) if y else 0)
        age_band = str(race.get("age_band") or "")
        juv = age_band.upper().startswith("2YO")
        use_key = "fig2" if juv and ("juv_form" in models or "juv" in models) else "fig"
        if use_key == "fig2":
            model = (models.get("juv_form") or models["juv"])["model"]
        else:
            model = (models.get("form") or models["all"])["model"]
        band = float(model.get("band") or (models.get("form") or models["all"])["model"].get("band") or 7)
        hist = hist_from_figs(figs_by.get(h.get("horse_norm") or "", []), "fig" if use_key == "fig" else "fig2")
        today = {
            "date": date,
            "code": code,
            "aw": code == "AW" or aw,
            "surface": race.get("surface"),
            "dist_f": dist_f,
            "going": going,
            "going_n": going_n(going),
            "cls": cls_n(race.get("race_class")),
            "age": h.get("age"),
            "or_": h.get("official_rating"),
            "days": h.get("last_ran_days"),
        }
        # if last_ran_days is present, still pass date so days can be computed; either is fine
        feat = features_from_hist(hist, today, fig_key=("fig" if use_key == "fig" else "fig2"))
        nr = str(h.get("status") or "RUNNER").upper() not in {"RUNNER", ""}
        rec = {
            "ride_id": int(h["ride_id"]),
            "race_id": int(h["race_id"]),
            "date": date,
            "time": race.get("time"),
            "course": race.get("course"),
            "race_name": race.get("name"),
            "horse": h.get("horse"),
            "horse_norm": h.get("horse_norm"),
            "cloth": h.get("cloth"),
            "nr": nr,
            "odds": h.get("odds") or h.get("forecast_odds"),
            "pred": None,
            "lo": None,
            "hi": None,
            "best3": feat["best3_raw"] if feat else None,
            "last_fig": feat["last_raw"] if feat else None,
            "n_prior": int(feat["n_runs"]) if feat else 0,
            "scale": "2yo" if use_key == "fig2" else "all",
        }
        if feat and not nr:
            feat_use = dict(feat)
            if (use_key == "fig" and "form" in models) or (use_key == "fig2" and "juv_form" in models):
                feat_use["or_today"] = 0.0
                feat_use["or_chg"] = 0.0
                feat_use["has_or"] = 0.0
            pred = predict_row(model, feat_use)
            rec["pred"] = round(pred, 1)
            rec["lo"] = round(max(FLOOR, pred - band), 1)
            rec["hi"] = round(min(CEIL, pred + band), 1)
        out.append(rec)
        by_race.setdefault(int(h["race_id"]), []).append(rec)

    # ranks within the race
    for rid, recs in by_race.items():
        act = [r for r in recs if not r["nr"] and r["pred"] is not None]
        act.sort(key=lambda r: (-r["pred"], r.get("cloth") or 99))
        for i, r in enumerate(act, 1):
            r["rank"] = i
        b3 = [r for r in recs if not r["nr"] and r["best3"] is not None]
        b3.sort(key=lambda r: (-r["best3"], r.get("cloth") or 99))
        for i, r in enumerate(b3, 1):
            r["rank_best3"] = i
    return out


def save_preds(preds: list[dict], model_payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TODAY_PATH.write_text(json.dumps(preds, indent=2), encoding="utf-8")
    slim = [
        {
            "ride_id": r["ride_id"], "race_id": r["race_id"], "date": r["date"],
            "horse_norm": r["horse_norm"], "horse": r["horse"],
            "pred": r["pred"], "lo": r["lo"], "hi": r["hi"],
            "best3": r["best3"], "last_fig": r["last_fig"], "n_prior": r["n_prior"],
            "rank": r.get("rank"), "rank_best3": r.get("rank_best3"), "scale": r.get("scale"),
        }
        for r in preds
    ]
    if CACHE.is_file():
        con = sqlite3.connect(CACHE)
        con.execute(
            """CREATE TABLE IF NOT EXISTS pred_today (
                ride_id INTEGER PRIMARY KEY,
                race_id INTEGER,
                date TEXT,
                horse_norm TEXT,
                horse TEXT,
                pred REAL,
                lo REAL,
                hi REAL,
                best3 REAL,
                last_fig REAL,
                n_prior INTEGER,
                rank INTEGER,
                rank_best3 INTEGER,
                scale TEXT
            )"""
        )
        dates = {r["date"] for r in slim}
        for d in dates:
            con.execute("DELETE FROM pred_today WHERE date=?", (d,))
        cols = ["ride_id","race_id","date","horse_norm","horse","pred","lo","hi","best3","last_fig","n_prior","rank","rank_best3","scale"]
        con.executemany(
            f"INSERT INTO pred_today ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
            [tuple(r.get(c) for c in cols) for r in slim],
        )
        # meta keys for the site + Supabase upload (existing fig_meta pattern)
        con.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        meta = {
            "pred_built": time.strftime("%Y-%m-%d %H:%M"),
            "pred_version": model_payload.get("version", "pred_today_v1"),
            "pred_model": json.dumps(model_payload, separators=(",", ":")),
            "pred_today": json.dumps(slim, separators=(",", ":")),
        }
        con.executemany("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", meta.items())
        con.commit()
        con.close()
        log(f"Saved {len(slim)} predictions to {CACHE} (pred_today + meta) and {TODAY_PATH}")
    else:
        log(f"Saved {len(slim)} predictions to {TODAY_PATH} (no site_cache.sqlite to update)")


def fmt_pct(x: float) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{100 * x:.1f}%"


def write_summary(payload: dict, preds: list[dict], plumpton_lines: list[str]) -> str:
    lines = []
    a = lines.append
    a("FurlongIQ — Predicted today (interim model)")
    a("=" * 72)
    a(f"Trained: {payload.get('trained')}")
    a(f"Source:  {payload.get('src')}")
    a(f"Method:  ridge regression (lambda={LAM}) on prior-run features only.")
    a("Target:  the speed figure the horse actually ran that day.")
    a("Split:   time-based; test = the latest ~12 months (never used in training).")
    a("")
    titles = (
        ("form", "All-age figures — form only (what the race card uses)"),
        ("all", "All-age figures — form + official rating (comparison)"),
        ("juv_form", "2yo-scale figures — form only (2yo races)"),
        ("juv", "2yo-scale figures — form + official rating (comparison)"),
    )
    for key, title in titles:
        block = payload["models"].get(key)
        if not block:
            a(f"{title}: not trained (not enough rows).")
            a("")
            continue
        m = block["metrics"]
        wr = block.get("win_rates") or {}
        a(title)
        a("-" * 72)
        a(f"  Train rows: {m['n_train']:,}    Test rows: {m['n_test']:,}    from {m['test_start']}")
        a(f"  MAE on test   predicted today : {m['test_mae']:.2f} lb")
        a(f"                last figure     : {m['test_mae_last']:.2f} lb")
        a(f"                Best 3          : {m['test_mae_best3']:.2f} lb")
        a(f"  Train MAE (sanity)            : {m['train_mae']:.2f} lb")
        a(f"  Typical error band (±)        : {m['band']:.1f} lb")
        if wr:
            a(f"  Test races where the top horse won:")
            a(f"    Top predicted today : {fmt_pct(wr.get('pred'))}  ({wr.get('pred_n', 0):,} races)")
            a(f"    Top Best 3          : {fmt_pct(wr.get('best3'))}  ({wr.get('best3_n', 0):,} races)")
            if wr.get("fav_n"):
                a(f"    Favourite (BSP)     : {fmt_pct(wr.get('fav'))}  ({wr.get('fav_n'):,} races, {wr.get('fav_cov', 0)*100:.0f}% priced)")
            else:
                a("    Favourite (BSP)     : n/a (no prices file, or too few matches)")
        a("")
    a("Today's cards")
    a("-" * 72)
    scored = [r for r in preds if r.get("pred") is not None]
    a(f"  {len(scored)} of {len(preds)} runners have a predicted figure.")
    a("  Stored in data\\site_cache.sqlite (pred_today table and fig_meta keys)")
    a("  and data\\predict_today\\today.json.")
    a("  Re-run this script (or npm run figures) after new cards are downloaded.")
    a("")
    if plumpton_lines:
        a("Sanity check — 14:15 Plumpton (today)")
        a("-" * 72)
        lines.extend(plumpton_lines)
        a("")
    a("Notes")
    a("-" * 72)
    a("- This is an interim rating: recent form, trend, class/OR change, trip, going")
    a("  and conditions-fit, learned from past results. It does not yet check whether")
    a("  a past figure was inflated by a soft race standard (that needs the full")
    a("  Racing TV / sectional data).")
    a("- The race card ranks by Predicted today, and still shows Best 3 next to it.")
    text = "\n".join(lines) + "\n"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(text, encoding="utf-8")
    return text


def plumpton_block(preds: list[dict]) -> list[str]:
    rows = [r for r in preds if str(r.get("time") or "") == "14:15" and "plumpton" in str(r.get("course") or "").lower()]
    if not rows:
        return []
    lines = []
    race = rows[0]
    lines.append(f"  {race['time']} {race['course']} — {race['race_name']}")
    lines.append(f"  {'Rk':<4}{'Horse':<24}{'Pred':>7}{'±':>8}{'B3':>7}{'B3 rk':>6}  odds")
    ordered = sorted(rows, key=lambda r: (r["nr"], r.get("rank") or 99, r.get("cloth") or 99))
    for r in ordered:
        if r["nr"]:
            continue
        lohi = f"{r['lo']:.0f}–{r['hi']:.0f}" if r["pred"] is not None else ""
        pred = f"{r['pred']:.1f}" if r["pred"] is not None else "–"
        b3 = f"{r['best3']:.1f}" if r["best3"] is not None else "–"
        br = str(r.get("rank_best3") or "–")
        rk = str(r.get("rank") or "–")
        mark = ""
        name = r["horse"] or ""
        if "Norman Fletcher" in name or "Kamille" in name:
            mark = "  <--"
        lines.append(f"  {rk:<4}{name:<24}{pred:>7}{lohi:>8}{b3:>7}{br:>6}  {r.get('odds') or ''}{mark}")
    # call out the two named horses
    def find(part: str):
        return next((r for r in rows if part.lower() in str(r.get("horse") or "").lower()), None)
    nf, ka = find("Norman Fletcher"), find("Kamille")
    if nf and ka:
        lines.append(
            f"  Norman Fletcher: predicted #{nf.get('rank') or '–'} (Best 3 #{nf.get('rank_best3') or '–'}). "
            f"Kamille Au Kanada: predicted #{ka.get('rank') or '–'} (Best 3 #{ka.get('rank_best3') or '–'})."
        )
    return lines


def print_top_weights(model: dict, n: int = 8) -> None:
    coef = list(zip(model["features"], model["coef"]))
    coef.sort(key=lambda kv: abs(kv[1]), reverse=True)
    log("  Largest weights (standardised features):")
    for k, v in coef[:n]:
        log(f"    {k:<16} {v:+.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train and score FurlongIQ 'predicted today' figures.")
    ap.add_argument("--score-only", action="store_true", help="Skip training; score today's cards with the saved model.")
    ap.add_argument("--date", help="Card date to score (default: latest date in cards.sqlite).")
    ap.add_argument("--limit-horses", type=int, default=0, help="Debug: use at most N horses when training.")
    args = ap.parse_args()
    t0 = time.time()

    if args.score_only:
        src = MODEL_PATH if MODEL_PATH.is_file() else BUNDLE_PATH
        payload = load_model(src)
        log(f"Loaded model trained {payload.get('trained')} from {src}")
    else:
        src = find_csv()
        df = load_csv(src)
        if args.limit_horses:
            keep = df["horse_id"].drop_duplicates().head(args.limit_horses)
            df = df[df["horse_id"].isin(keep)]
            log(f"  [debug] limited to {args.limit_horses} horses, {len(df):,} runs")
        max_date = str(df["date"].max())
        test_start = str(pd.Timestamp(max_date) - pd.DateOffset(years=1))[:10]
        log(f"Building features (test from {test_start})… this is the slow step.")
        t1 = time.time()
        feat_all = build_dataset(df, "fig")
        log(f"  All-age feature rows: {len(feat_all):,} in {time.time()-t1:.1f}s")
        t2 = time.time()
        # 2yo model: runs that have a 2yo figure (typically 2yos)
        feat_juv = build_dataset(df, "fig2")
        log(f"  2yo-scale feature rows: {len(feat_juv):,} in {time.time()-t2:.1f}s")

        log("Training ridge models…")
        all_block = train_one(feat_all, "all", test_start)
        # Form-only: drop official-rating features so the card rating is driven by
        # speed figures, trend and conditions — not just the handicap mark.
        form_df = feat_all.copy()
        for c in ("or_today", "or_chg", "has_or"):
            form_df[c] = 0.0
        form_block = train_one(form_df, "form", test_start)
        juv_block = train_one(feat_juv, "juv", test_start) if len(feat_juv) > 5000 else None
        juv_form = None
        if juv_block is not None:
            jf = feat_juv.copy()
            for c in ("or_today", "or_chg", "has_or"):
                jf[c] = 0.0
            juv_form = train_one(jf, "juv_form", test_start)

        prices = load_prices()
        for block in (all_block, form_block, juv_block, juv_form):
            if not block:
                continue
            pred_hr, pred_n = top_hit_rate(block["test"], "pred")
            b3_hr, b3_n = top_hit_rate(block["test"], "best3_raw")
            fav_hr, fav_n, fav_cov = favourite_hit_rate(block["test"], prices)
            block["win_rates"] = {
                "pred": pred_hr, "pred_n": pred_n,
                "best3": b3_hr, "best3_n": b3_n,
                "fav": fav_hr, "fav_n": fav_n, "fav_cov": fav_cov,
            }
            # drop the bulky test frame from the saved model
            m = block["metrics"]
            wr = block["win_rates"]
            log(f"  {block['metrics']['label']}: test MAE {m['test_mae']:.2f}  (last {m['test_mae_last']:.2f}, Best 3 {m['test_mae_best3']:.2f})")
            log(f"         top-pred won {fmt_pct(wr['pred'])} of {wr['pred_n']:,}  |  top-Best3 won {fmt_pct(wr['best3'])} of {wr['best3_n']:,}"
                + (f"  |  fav won {fmt_pct(wr['fav'])} of {wr['fav_n']:,}" if wr["fav_n"] else ""))
            print_top_weights(block["model"])

        # The card uses the form-only model (no official rating). The with-OR
        # version is kept in the file for comparison — it is usually a bit
        # more accurate but mostly follows the handicap marks.
        payload = {
            "version": "pred_today_v1",
            "trained": time.strftime("%Y-%m-%d %H:%M"),
            "src": str(Path(src.parent.name) / src.name),
            "test_start": test_start,
            "max_date": max_date,
            "card_model": "form",
            "models": {
                "all": {"model": all_block["model"], "metrics": all_block["metrics"], "win_rates": all_block["win_rates"]},
                "form": {"model": form_block["model"], "metrics": form_block["metrics"], "win_rates": form_block["win_rates"]},
            },
        }
        if juv_block:
            payload["models"]["juv"] = {
                "model": juv_block["model"], "metrics": juv_block["metrics"], "win_rates": juv_block["win_rates"],
            }
        if juv_form:
            payload["models"]["juv_form"] = {
                "model": juv_form["model"], "metrics": juv_form["metrics"], "win_rates": juv_form["win_rates"],
            }
        write_model(payload)

    preds = score_cards(payload, args.date)
    save_preds(preds, payload)
    plum = plumpton_block(preds)
    text = write_summary(payload, preds, plum)
    log("")
    log(text.rstrip())
    log("")
    log(f"Done in {time.time()-t0:.1f}s. Summary: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
