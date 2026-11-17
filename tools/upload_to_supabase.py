#!/usr/bin/env python3
"""Upload local FurlongIQ cards + figure history to the horse Supabase project.

Reads data/cards.sqlite and data/site_cache.sqlite, then replaces the public
tables in Supabase. Auth is the service role key from a local .env file
(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY). That key must never be committed
or added to Vercel.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIG_COLS = [
    "horse_norm", "race_id", "date", "foal_year", "course", "code", "surface",
    "dist", "dist_f", "going", "cls", "pos", "beaten", "ran", "offr", "fig", "fig2",
]
PRED_COLS = [
    "ride_id", "race_id", "date", "horse_norm", "horse", "pred", "lo", "hi",
    "best3", "last_fig", "n_prior", "rank", "rank_best3", "scale",
]
PACE_COLS = [
    "date", "course_norm", "course", "off_hhmm", "dist_f", "code", "label",
    "fig_rel", "reason", "source", "fsp", "field_def", "n_field", "horses",
    "fig_race_id", "rtv_race_id",
]
WIN_COLS = [
    "ride_id", "race_id", "date", "horse_norm", "horse", "win_pct", "fair_odds", "win_rank",
]
SEC_COLS = [
    "horse_norm", "date", "course", "rtv_race_id", "n", "pace_label",
    "fin_speed_pct", "fig_adj", "fig", "run_style", "style_pct", "sectors",
]
CARD_ORDER = ("meetings", "races", "runners", "prev_runs", "scrape_log")
BATCH = 800


def fail(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    for path in (ROOT / ".env", Path.cwd() / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            env.setdefault(k.strip(), v)
    return env


def connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        fail(f"Missing {path}. Run GET_TODAYS_CARDS.bat and npm run figures first.")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def rows(con: sqlite3.Connection, sql: str, cols: list[str] | None = None) -> list[dict]:
    out = []
    for r in con.execute(sql):
        d = dict(r)
        if cols:
            d = {k: d.get(k) for k in cols}
        out.append(d)
    return out


def clean_meta(items: list[dict]) -> list[dict]:
    out = []
    for row in items:
        k, v = row["k"], row["v"]
        if k == "src" and v:
            p = Path(str(v))
            v = str(Path(p.parent.name) / p.name) if p.parent.name else p.name
        out.append({"k": k, "v": v})
    return out


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def load_all() -> tuple[dict[str, list[dict]], list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    cards = connect(ROOT / "data" / "cards.sqlite")
    cache = connect(ROOT / "data" / "site_cache.sqlite")
    card_data = {
        "meetings": rows(cards, "SELECT * FROM meetings"),
        "races": rows(cards, "SELECT * FROM races"),
        "runners": rows(cards, "SELECT * FROM runners"),
        "prev_runs": rows(cards, "SELECT * FROM prev_runs"),
        "scrape_log": rows(cards, "SELECT * FROM scrape_log"),
    }
    figs = rows(cache, "SELECT " + ", ".join(FIG_COLS) + " FROM figs", FIG_COLS)
    meta = clean_meta(rows(cache, "SELECT k, v FROM meta"))
    preds = rows(cache, "SELECT " + ", ".join(PRED_COLS) + " FROM pred_today", PRED_COLS) if table_exists(cache, "pred_today") else []
    pace = rows(cache, "SELECT " + ", ".join(PACE_COLS) + " FROM pace", PACE_COLS) if table_exists(cache, "pace") else []
    wins = rows(cache, "SELECT " + ", ".join(WIN_COLS) + " FROM win_pct", WIN_COLS) if table_exists(cache, "win_pct") else []
    sectionals = rows(cache, "SELECT " + ", ".join(SEC_COLS) + " FROM sectionals", SEC_COLS) if table_exists(cache, "sectionals") else []
    return card_data, figs, meta, preds, pace, wins, sectionals


def request(method: str, url: str, key: str, body: bytes | None = None, extra: dict | None = None) -> tuple[int, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=minimal"
    if extra:
        headers.update(extra)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def call(method: str, url: str, key: str, body: bytes | None = None, extra: dict | None = None, tries: int = 6) -> None:
    last = ""
    for i in range(tries):
        status, text = request(method, url, key, body, extra)
        if 200 <= status < 300:
            return
        last = f"{status} {text[:500]}"
        if status in {429, 500, 502, 503, 504} or status >= 520:
            time.sleep(min(2 ** i, 20))
            continue
        fail(f"{method} {url} failed: {last}")
    fail(f"{method} {url} failed after retries: {last}")


def post_batches(base: str, table: str, key: str, items: list[dict], batch: int = BATCH) -> None:
    if not items:
        print(f"  {table}: 0 rows")
        return
    url = f"{base}/rest/v1/{table}"
    total = len(items)
    for i in range(0, total, batch):
        chunk = items[i:i + batch]
        call("POST", url, key, json.dumps(chunk, default=str).encode("utf-8"))
        done = min(i + batch, total)
        print(f"  {table}: {done:,} / {total:,}", flush=True)


def cell(v) -> str:
    if v is None:
        return ""
    return str(v).replace("\\", " ").replace("\t", " ").replace("\r", " ").replace("\n", " ")


def sql_insert_json(table: str, items: list[dict], coltypes: dict[str, str]) -> str:
    payload = json.dumps(items, default=str, ensure_ascii=False).replace("'", "''")
    cols = list(coltypes)
    col_list = ", ".join(cols)
    typ_list = ", ".join(f"{c} {coltypes[c]}" for c in cols)
    return (
        f"insert into public.{table} ({col_list}) "
        f"select {col_list} from jsonb_to_recordset('{payload}'::jsonb) as x({typ_list});\n"
    )


FIG_SQL = """
insert into public.figs (
  horse_norm, race_id, date, foal_year, course, code, surface, dist, dist_f,
  going, cls, pos, beaten, ran, offr, fig, fig2
)
select
  nullif(x[1], ''),
  nullif(x[2], ''),
  nullif(x[3], '')::date,
  nullif(x[4], '')::smallint,
  nullif(x[5], ''),
  nullif(x[6], ''),
  nullif(x[7], ''),
  nullif(x[8], ''),
  nullif(x[9], '')::real,
  nullif(x[10], ''),
  nullif(x[11], '')::real,
  nullif(x[12], ''),
  nullif(x[13], '')::real,
  nullif(x[14], '')::smallint,
  nullif(x[15], '')::real,
  nullif(x[16], '')::real,
  nullif(x[17], '')::real
from (
  select string_to_array(line, E'\\t') as x
  from unnest(string_to_array({payload}, E'\\n')) as line
  where line <> ''
) s;
"""

CARD_TYPES = {
    "meetings": {
        "meeting_id": "bigint", "date": "date", "course": "text", "country": "text",
        "going": "text", "surface": "text", "weather": "text",
    },
    "races": {
        "race_id": "bigint", "meeting_id": "bigint", "date": "date", "time": "text",
        "course": "text", "name": "text", "race_class": "text", "distance": "text",
        "going": "text", "age_band": "text", "surface": "text", "handicap": "smallint",
        "ride_count": "smallint", "stage": "text", "betting_forecast": "text",
        "verdict": "text", "url": "text",
    },
    "runners": {
        "ride_id": "bigint", "race_id": "bigint", "date": "date", "cloth": "smallint",
        "draw": "smallint", "status": "text", "horse": "text", "horse_norm": "text",
        "sl_horse_id": "bigint", "age": "smallint", "sex": "text", "weight": "text",
        "weight_lb": "smallint", "official_rating": "smallint", "jockey": "text",
        "jockey_claim": "smallint", "trainer": "text", "owner": "text",
        "headgear": "text", "form": "text", "last_ran_days": "smallint",
        "odds": "text", "forecast_odds": "text", "runs": "smallint", "wins": "smallint",
        "places": "smallint", "silk": "text", "commentary": "text",
    },
    "prev_runs": {
        "ride_id": "bigint", "n": "smallint", "horse_norm": "text", "sl_race_id": "bigint",
        "date": "date", "course": "text", "distance": "text", "run_type": "text",
        "going": "text", "race_class": "text", "position": "smallint", "outcome": "text",
        "runners": "smallint", "weight": "text", "bha": "smallint", "odds": "text",
        "comment": "text",
    },
    "scrape_log": {
        "date": "date", "ts": "timestamptz", "meetings": "integer",
        "races": "integer", "runners": "integer",
    },
}


def dump_sql(dest: Path, card_data: dict[str, list[dict]], figs: list[dict], meta: list[dict], preds: list[dict] | None = None, pace: list[dict] | None = None, wins: list[dict] | None = None, sectionals: list[dict] | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for f in dest.glob("*.sql"):
        f.unlink()
    (dest / "000_wipe.sql").write_text(
        "truncate table public.prev_runs, public.runners, public.races, public.meetings, "
        "public.scrape_log, public.figs, public.fig_meta restart identity cascade;\n",
        encoding="utf-8",
    )
    n = 1
    for table in CARD_ORDER:
        items = card_data.get(table) or []
        if not items:
            continue
        typed = CARD_TYPES[table]
        # keep only known columns, in type order
        slim = [{k: row.get(k) for k in typed} for row in items]
        (dest / f"{n:03d}_{table}.sql").write_text(sql_insert_json(table, slim, typed), encoding="utf-8")
        n += 1
    if meta:
        (dest / f"{n:03d}_fig_meta.sql").write_text(
            sql_insert_json("fig_meta", meta, {"k": "text", "v": "text"}),
            encoding="utf-8",
        )
        n += 1
    if preds:
        pred_types = {
            "ride_id": "bigint", "race_id": "bigint", "date": "date", "horse_norm": "text",
            "horse": "text", "pred": "real", "lo": "real", "hi": "real", "best3": "real",
            "last_fig": "real", "n_prior": "smallint", "rank": "smallint", "rank_best3": "smallint",
            "scale": "text",
        }
        slim = [{k: row.get(k) for k in pred_types} for row in preds]
        (dest / f"{n:03d}_pred_today.sql").write_text(sql_insert_json("pred_today", slim, pred_types), encoding="utf-8")
        n += 1
    if pace:
        pace_types = {
            "date": "date", "course_norm": "text", "course": "text", "off_hhmm": "text",
            "dist_f": "real", "code": "text", "label": "text", "fig_rel": "text",
            "reason": "text", "source": "text", "fsp": "real", "field_def": "real",
            "n_field": "smallint", "horses": "text", "fig_race_id": "text", "rtv_race_id": "bigint",
        }
        slim = [{k: row.get(k) for k in pace_types} for row in pace]
        (dest / f"{n:03d}_pace.sql").write_text(sql_insert_json("pace", slim, pace_types), encoding="utf-8")
        n += 1
    if wins:
        win_types = {
            "ride_id": "bigint", "race_id": "bigint", "date": "date", "horse_norm": "text",
            "horse": "text", "win_pct": "real", "fair_odds": "real", "win_rank": "smallint",
        }
        slim = [{k: row.get(k) for k in win_types} for row in wins]
        (dest / f"{n:03d}_win_pct.sql").write_text(sql_insert_json("win_pct", slim, win_types), encoding="utf-8")
        n += 1
    if sectionals:
        sec_types = {
            "horse_norm": "text", "date": "date", "course": "text", "rtv_race_id": "bigint",
            "n": "smallint", "pace_label": "text", "fin_speed_pct": "real", "fig_adj": "real",
            "fig": "real", "run_style": "text", "style_pct": "real", "sectors": "text",
        }
        slim = [{k: row.get(k) for k in sec_types} for row in sectionals]
        (dest / f"{n:03d}_sectionals.sql").write_text(sql_insert_json("sectionals", slim, sec_types), encoding="utf-8")
        n += 1
    per = 12000
    tag = "FIGTSV"
    for i in range(0, len(figs), per):
        chunk = figs[i:i + per]
        lines = ["\t".join(cell(r[c]) for c in FIG_COLS) for r in chunk]
        body = "\n".join(lines)
        sql = FIG_SQL.format(payload=f"${tag}$\n{body}\n${tag}$")
        (dest / f"{n:03d}_figs_{i // per:03d}.sql").write_text(sql, encoding="utf-8")
        n += 1
    print(f"Wrote {n} SQL files to {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload FurlongIQ SQLite data to the horse Supabase project.")
    parser.add_argument("--dump-sql", metavar="DIR", help="Write SQL batches instead of uploading.")
    args = parser.parse_args()

    card_data, figs, meta, preds, pace, wins, sectionals = load_all()
    print(f"Loaded cards: {len(card_data['meetings'])} meetings, {len(card_data['races'])} races, "
          f"{len(card_data['runners'])} runners, {len(card_data['prev_runs'])} form runs")
    print(f"Loaded figures: {len(figs):,} rows, {len(meta)} meta keys, {len(preds)} predicted-today rows, "
          f"{len(pace):,} pace rows, {len(wins)} win-% rows, {len(sectionals)} sectional rows")

    if args.dump_sql:
        dump_sql(Path(args.dump_sql), card_data, figs, meta, preds, pace, wins, sectionals)
        return

    env = load_env()
    base = (env.get("SUPABASE_URL") or "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not key:
        fail(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in a .env file in the Speeds folder.\n"
            "Copy .env.example to .env and paste the service role key from the horse Supabase project:\n"
            "  Project Settings -> API -> service_role  (secret).\n"
            "Do not put that key in git or in Vercel."
        )

    print(f"Uploading to {base}")
    print("Wiping existing site dataâ€¦")
    call("POST", f"{base}/rest/v1/rpc/wipe_site_data", key, b"{}")
    # scrape_log is keyed by date: keep only the latest row per date (cards can be fetched several times a day).
    if card_data.get("scrape_log"):
        latest = {}
        for r in card_data["scrape_log"]:
            latest[r.get("date")] = r
        card_data["scrape_log"] = list(latest.values())
    for table in CARD_ORDER:
        post_batches(base, table, key, card_data[table])
    post_batches(base, "fig_meta", key, meta)
    post_batches(base, "figs", key, figs, batch=1000)
    if preds:
        # Optional table â€” predictions are also in fig_meta so the site works without it.
        status, text = request("DELETE", f"{base}/rest/v1/pred_today?ride_id=gt.0", key, extra={"Prefer": "return=minimal"})
        if status in {200, 204} or (200 <= status < 300):
            post_batches(base, "pred_today", key, preds)
        elif status == 404:
            print("  pred_today table is not on Supabase yet. Predictions are already in fig_meta,")
            print("  so the live site will still show them. To add the table, run tools/pred_today.sql")
            print("  in the horse Supabase SQL editor, then re-run this upload.")
        else:
            print(f"  pred_today skipped ({status} {text[:200]}). Predictions are already in fig_meta.")
    if pace:
        # Optional table â€” the site hides pace badges if it is missing.
        status, text = request("DELETE", f"{base}/rest/v1/pace?date=gte.2000-01-01", key, extra={"Prefer": "return=minimal"})
        if status in {200, 204} or (200 <= status < 300):
            post_batches(base, "pace", key, pace)
        elif status == 404:
            print("  pace table is not on Supabase yet. Run tools/pace.sql in the horse")
            print("  Supabase SQL editor, then re-run this upload. The live site works without")
            print("  it (form runs just will not show precomputed pace badges).")
        else:
            print(f"  pace skipped ({status} {text[:200]}). The live site will hide pace badges.")
    if wins:
        status, text = request("DELETE", f"{base}/rest/v1/win_pct?date=gte.2000-01-01", key, extra={"Prefer": "return=minimal"})
        if status in {200, 204} or (200 <= status < 300):
            post_batches(base, "win_pct", key, wins)
        elif status == 404:
            print("  win_pct table is not on Supabase yet. Win percentages are already in fig_meta,")
            print("  so the live site will still show them. To add the table, run tools/win_pct.sql")
            print("  in the horse Supabase SQL editor, then re-run this upload.")
        else:
            print(f"  win_pct skipped ({status} {text[:200]}). Win percentages are already in fig_meta.")
    if sectionals:
        # Optional compact table — the site hides the sectional panel if it is missing.
        status, text = request("DELETE", f"{base}/rest/v1/sectionals?n=gte.0", key, extra={"Prefer": "return=minimal"})
        if status in {200, 204} or (200 <= status < 300):
            post_batches(base, "sectionals", key, sectionals)
        elif status == 404:
            print("  sectionals table is not on Supabase yet. Run tools/sectionals.sql in the horse")
            print("  Supabase SQL editor, then re-run this upload. The live site works without")
            print("  it (the sectional panel just will not show).")
        else:
            print(f"  sectionals skipped ({status} {text[:200]}). The live site will hide the sectional panel.")
    print("Done. The Vercel site will pick this up on the next page load (no redeploy needed).")


if __name__ == "__main__":
    main()
