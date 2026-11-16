"""Builds/refreshes data\\site_cache.sqlite from the speed-figure CSV (v3 preferred, v2 fallback).
Rebuilt automatically when the CSV changes. Tolerant of missing columns."""
import os, re, sqlite3, time
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CACHE = os.path.join(DATA, "site_cache.sqlite")
CANDIDATES = ["speed_v3", "speed_v2", "speed_v1", "speed"]


def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\([a-z]{2,4}\)", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def find_source():
    for d in CANDIDATES:
        p = os.path.join(DATA, d, "speed_figures.csv")
        if os.path.exists(p):
            return d, p
    return None, None


def _pick(cols, *names, contains=None):
    for n in names:
        if n in cols:
            return n
    if contains:
        for c in cols:
            if all(k in c.lower() for k in contains):
                return c
    return None


def build(force=False, log=print):
    ver, src = find_source()
    if not src:
        log("No speed_figures.csv found in data\\speed_v3 or data\\speed_v2 - site will show cards without figures.")
        return None
    mtime = str(os.path.getmtime(src))
    if os.path.exists(CACHE) and not force:
        try:
            con = sqlite3.connect(CACHE)
            meta = dict(con.execute("SELECT k,v FROM meta"))
            con.close()
            if meta.get("src") == src and meta.get("mtime") == mtime:
                return meta
        except Exception:
            pass
    t0 = time.time()
    log(f"Building figure cache from {src} (one-off, ~1 minute)...")
    cols = list(pd.read_csv(src, nrows=0).columns)
    m = {
        "race_id": _pick(cols, "race_id"), "date": _pick(cols, "date"), "time": _pick(cols, "off_time"),
        "course": _pick(cols, "course_raw", "course"), "code": _pick(cols, "code"),
        "surface": _pick(cols, "surface"), "dist": _pick(cols, "distance_raw", "distance"),
        "dist_f": _pick(cols, "dist_f"), "going": _pick(cols, "going"), "cls": _pick(cols, "class"),
        "race_name": _pick(cols, "race_name"), "horse": _pick(cols, "horse"), "age": _pick(cols, "age"),
        "weight": _pick(cols, "weight_raw"), "offr": _pick(cols, "offr", "or"),
        "pos": _pick(cols, "place_raw", "place"), "place": _pick(cols, "place"),
        "beaten": _pick(cols, "beaten_l", "beaten_l_eff"),
        "fig": _pick(cols, "weighted_fig", "figure", "speed_fig"),
        "nat": _pick(cols, "natural_fig"),
        "fig2": _pick(cols, "fig_2yo_weighted", "fig_2yo", "weighted_fig_2yo", contains=("2yo", "fig")),
        "fieldfig": _pick(cols, "field_avg_fig"),
    }
    m = {k: v for k, v in m.items() if v}
    if "horse" not in m or "date" not in m:
        log("speed_figures.csv has no horse/date columns - skipping figures.")
        return None
    use = sorted(set(m.values()))
    df = pd.read_csv(src, usecols=use, low_memory=False)
    out = pd.DataFrame({k: df[v] for k, v in m.items()})
    for k in ["race_id", "time", "course", "code", "surface", "dist", "dist_f", "going", "cls", "race_name",
              "age", "weight", "offr", "pos", "place", "beaten", "fig", "nat", "fig2", "fieldfig"]:
        if k not in out:
            out[k] = None
    if out["race_id"].isna().all():
        out["race_id"] = out["date"].astype(str) + "_" + out["course"].astype(str) + "_" + out["time"].astype(str)
    out["ran"] = out.groupby("race_id")["horse"].transform("size")
    out["horse_norm"] = out["horse"].map(norm_name)
    out["date"] = out["date"].astype(str).str[:10]
    yr = pd.to_numeric(out["date"].str[:4], errors="coerce")
    out["foal_year"] = yr - pd.to_numeric(out["age"], errors="coerce")
    for c in ["fig", "nat", "fig2", "fieldfig", "beaten"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").round(1)
    out = out.drop(columns=["place"])
    tmp = CACHE + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    out.to_sql("figs", con, index=False, chunksize=50000)
    con.execute("CREATE INDEX ix_h ON figs(horse_norm, date)")
    meta = {"src": src, "mtime": mtime, "version": ver, "rows": str(len(out)),
            "max_date": str(out["date"].max()), "has_2yo": "1" if "fig2" in m else "0",
            "built": time.strftime("%Y-%m-%d %H:%M")}
    con.execute("CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT)")
    con.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    con.commit()
    con.close()
    if os.path.exists(CACHE):
        os.remove(CACHE)
    os.replace(tmp, CACHE)
    log(f"Figure cache ready: {len(out):,} runs from {ver} in {time.time()-t0:.0f}s")
    return meta


if __name__ == "__main__":
    import sys
    build(force="--force" in sys.argv)
