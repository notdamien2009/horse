"""Build FurlongIQ market stats from Betfair data only (no bookmaker prices).

Reads the RBD parquet (Betfair BSP and pre-off Betfair prices 15/10/5/3/2/1 mins) read-only
and writes web/src/lib/market-stats.json, used by the home page.

Market move = change in Betfair implied win chance, in percentage points (pp),
from the earliest available pre-off Betfair price (normally 15 mins before the off) to BSP.
  backed   : +3pp or more   (about the top 10% of moves)
  strong   : +5pp or more   (about the top 5%)
  drifted  : -3pp or less
Industry SP ('Ind SP') is deliberately NOT read.
"""
import json, glob, os, sqlite3, datetime as dt
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PQ = sorted(glob.glob(os.path.join(ROOT, "rbsdata*.parquet")))[-1]
OUT = os.path.join(ROOT, "web", "src", "lib", "market-stats.json")
PRE = ["15 Mins", "10 mins", "5 mins", "3 mins", "2 mins", "1 min"]
PRICE_COLS = ["BSP"] + PRE + ["Min Price", "Max Price", "Last Traded Price"]
BACK, STRONG, DRIFT = 3.0, 5.0, -3.0
COMM = 0.05

cols = ["Date", "Place", "Time", "Track Name", "Race Name", "Horse", "Trainer", "Jockey"] + PRICE_COLS
d = pd.read_parquet(PQ, columns=cols)
for c in PRICE_COLS:
    d[c] = pd.to_numeric(d[c], errors="coerce")
d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
d["race"] = d["Date"] + "|" + d["Track Name"].astype(str) + "|" + d["Time"].astype(str)
price_points = int(d[PRICE_COLS].notna().sum().sum())

d["p0"] = d[PRE].bfill(axis=1).iloc[:, 0]
d["p0_col"] = d[PRE].notna().idxmax(axis=1).where(d[PRE].notna().any(axis=1))
m = d[(d["BSP"] > 1) & (d["p0"] > 1) & d["Place"].notna()].copy()
m["win"] = (m["Place"] == 1).astype(int)
m["move"] = 100 * (1 / m["BSP"] - 1 / m["p0"])
m["pl"] = np.where(m["win"] == 1, (m["BSP"] - 1) * (1 - COMM), -1.0)
m["exp"] = 1 / m["BSP"]

def grp(x):
    n = int(len(x))
    if n == 0:
        return {"runners": 0, "wins": 0, "sr": None, "ae": None, "roi": None}
    w = int(x["win"].sum())
    return {"runners": n, "wins": w, "sr": round(100 * w / n, 1),
            "ae": round(w / x["exp"].sum(), 2), "roi": round(100 * x["pl"].mean(), 1)}

backed, strong, drifted = m["move"] >= BACK, m["move"] >= STRONG, m["move"] <= DRIFT
overall = {"all": grp(m), "backed": grp(m[backed]), "strong": grp(m[strong]),
           "drifted": grp(m[drifted]), "steady": grp(m[~backed & ~drifted])}

# ---- trainer profiles
rows = []
for t, x in m.groupby("Trainer"):
    if len(x) < 150 or not isinstance(t, str) or not t.strip():
        continue
    rows.append({"trainer": t, "all": grp(x), "backed": grp(x[x["move"] >= BACK]),
                 "strong": grp(x[x["move"] >= STRONG]), "drifted": grp(x[x["move"] <= DRIFT])})

def pick_lift(rows, key, min_n, used):
    c = [r for r in rows if r[key]["runners"] >= min_n and r["trainer"] not in used]
    return max(c, key=lambda r: r[key]["sr"] - r["all"]["sr"]) if c else None

used = set()
ex_backed = pick_lift(rows, "backed", 60, used); used.add(ex_backed["trainer"])
c = [r for r in rows if r["drifted"]["runners"] >= 80 and r["all"]["sr"] >= 15 and r["trainer"] not in used]
ex_drift = min(c, key=lambda r: abs(r["drifted"]["sr"] - r["all"]["sr"])); used.add(ex_drift["trainer"])
ex_strong = pick_lift(rows, "strong", 25, used)
top_trainers = sorted(rows, key=lambda r: -r["all"]["runners"])[:40]

# ---- horse profiles: horses backed most often (3pp+), min 10 runs
hrows = []
for h, x in m.groupby("Horse"):
    if len(x) < 10:
        continue
    b = x[x["move"] >= BACK]
    if len(b) < 3:
        continue
    hrows.append({"horse": h, "trainer": str(x.sort_values("Date")["Trainer"].iloc[-1]), "last": x["Date"].max(),
                  "all": grp(x), "backed": grp(b), "drifted": grp(x[x["move"] <= DRIFT])})
top_horses = sorted(hrows, key=lambda r: (-r["backed"]["runners"], -r["backed"]["wins"]))[:40]

# ---- how unusual is a move: percentile within its BSP band
bands = [(1, 3), (3, 6), (6, 12), (12, 25), (25, 1001)]
band_moves = {}
for lo, hi in bands:
    band_moves[(lo, hi)] = np.sort(m.loc[(m["BSP"] >= lo) & (m["BSP"] < hi), "move"].abs().to_numpy())

def unusual(bsp, mv):
    for lo, hi in bands:
        if lo <= bsp < hi:
            arr = band_moves[(lo, hi)]
            pct = 100 * (1 - np.searchsorted(arr, abs(mv), side="left") / len(arr))
            return round(max(pct, 0.1), 1)
    return None

# ---- Betfair movers grid: latest day in the data
last = m["Date"].max()
day = m[m["Date"] == last].copy()
def mover_rows(x):
    out = []
    for _, r in x.iterrows():
        out.append({"time": str(r["Time"])[:5], "course": r["Track Name"], "horse": r["Horse"], "trainer": r["Trainer"],
                    "p0": round(float(r["p0"]), 2), "p0_col": r["p0_col"], "sp": round(float(r["BSP"]), 2),
                    "move": round(float(r["move"]), 1), "top_pct": unusual(float(r["BSP"]), float(r["move"])),
                    "pos": int(r["Place"]) if pd.notna(r["Place"]) else None})
    return out
supporters = mover_rows(day.sort_values("move", ascending=False).head(10))
drifters = mover_rows(day.sort_values("move").head(10))

# ---- speed figure meta (from the existing figure cache, read-only)
figs = {}
try:
    con = sqlite3.connect(f"file:{os.path.join(ROOT, 'data', 'site_cache.sqlite')}?mode=ro", uri=True)
    figs = {k: v for k, v in con.execute("select k, v from meta")}
    figs["with_fig"] = con.execute("select count(*) from figs where fig is not null").fetchone()[0]
except Exception as e:
    figs = {"error": str(e)}

out = {
    "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "source": "furlongiq-history",
    "rules": {"back_pp": BACK, "strong_pp": STRONG, "drift_pp": DRIFT, "commission": COMM,
              "from": "early price (earliest pre-off exchange price, normally 15 mins before the off)", "to": "FIQ SP (final exchange starting price)"},
    "counts": {"runners": int(len(d)), "races": int(d["race"].nunique()), "horses": int(d["Horse"].nunique()),
               "trainers": int(d["Trainer"].nunique()), "jockeys": int(d["Jockey"].nunique()),
               "courses": int(d["Track Name"].nunique()), "price_points": price_points,
               "with_move": int(len(m)), "first_date": d["Date"].min(), "last_date": d["Date"].max(),
               "fig_runs": int(figs.get("with_fig", 0) or 0)},
    "overall": overall,
    "examples": {"backed": ex_backed, "drift": ex_drift, "strong": ex_strong},
    "trainers": top_trainers, "horses": top_horses,
    "movers": {"date": last, "supporters": supporters, "drifters": drifters},
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
print("wrote", OUT)
print(json.dumps({"counts": out["counts"], "overall": overall}, indent=1))
for k, v in out["examples"].items():
    print(k, v["trainer"], v["all"], v[k if k != "drift" else "drifted"])
print("supporters", supporters[:3]); print("drifters", drifters[:3])
