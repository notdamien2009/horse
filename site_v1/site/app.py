"""Local racing site v1 - today's UK/IRE race cards with form, speed figures and ratings.
Run:  python site\\app.py   then open http://localhost:8050
Standard library only (+ pandas once, to build the figure cache)."""
import datetime as dt, json, os, re, sqlite3, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import figcache  # noqa: E402

ROOT = figcache.ROOT
CARDS = os.path.join(ROOT, "data", "cards.sqlite")
STATIC = os.path.join(HERE, "static")
PORT = int(os.environ.get("SITE_PORT", "8050"))
META = {}
JUMPS = ("Hurdle", "Chase", "NHF")


def q(db, sql, args=()):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    finally:
        con.close()


def race_family(name, surface):
    n = (name or "").lower()
    if "chase" in n:
        return "Chase"
    if "hurdle" in n:
        return "Hurdle"
    if "bumper" in n or "national hunt flat" in n or "nh flat" in n or "inh flat" in n:
        return "NHF"
    return "Flat"


def dates_available():
    if not os.path.exists(CARDS):
        return []
    return [r["date"] for r in q(CARDS, "SELECT DISTINCT date FROM races ORDER BY date DESC")]


def card(date):
    meetings = q(CARDS, "SELECT * FROM meetings WHERE date=? ORDER BY course", (date,))
    races = q(CARDS, "SELECT race_id,meeting_id,time,course,name,race_class,distance,going,ride_count,"
                     "stage FROM races WHERE date=? ORDER BY time", (date,))
    for m in meetings:
        m["races"] = [r for r in races if r["meeting_id"] == m["meeting_id"]]
        m["first"] = m["races"][0]["time"] if m["races"] else "99"
    meetings.sort(key=lambda m: m["first"])
    return meetings


def horse_figs(norm, foal_year, before):
    if not META or not norm:
        return []
    rows = q(figcache.CACHE, "SELECT * FROM figs WHERE horse_norm=? AND date<? ORDER BY date DESC", (norm, before))
    if foal_year and rows:
        same = [r for r in rows if r["foal_year"] is not None and abs(r["foal_year"] - foal_year) < 0.5]
        # name clash with a different-aged horse -> keep the matching one only
        rows = same
    return rows


def ratings(figs, family):
    fam = [r for r in figs if (r["code"] in JUMPS) == (family in JUMPS)] or figs
    vals = [r["fig"] for r in fam if r["fig"] is not None]
    recent = [r["fig"] for r in fam[:12] if r["fig"] is not None]
    two = [r["fig2"] for r in figs if r.get("fig2") is not None]
    two3 = sorted(two[:12], reverse=True)[:3]
    top3 = sorted(recent, reverse=True)[:3]
    return {
        "last": vals[0] if vals else None,
        "best": max(vals) if vals else None,
        "best3": round(sum(top3) / len(top3), 1) if top3 else None,
        "avg3": round(sum(vals[:3]) / len(vals[:3]), 1) if vals else None,
        "best2yo": max(two) if two else None,
        "best3_2yo": round(sum(two3) / len(two3), 1) if two3 else None,
        "nfigs": len(vals),
        "family_used": "jumps" if family in JUMPS else "flat",
    }


def build_form(prev, figs):
    """Merge Sporting Life previous runs with our figures (by date). Last 6 runs."""
    byd = {r["date"]: r for r in figs}
    out = []
    if prev:
        for p in prev[:6]:
            f = byd.get(p["date"])
            pos = str(p["position"]) if p["position"] else {
                "PulledUp": "PU", "Fell": "F", "UnseatedRider": "UR", "RefusedToRace": "RR", "BroughtDown": "BD",
                "Refused": "REF", "SlippedUp": "SU", "RanOut": "RO", "CarriedOut": "CO"}.get(p["outcome"] or "", (p["outcome"] or "-")[:3])
            out.append({"date": p["date"], "course": p["course"], "dist": p["distance"], "going": p["going"],
                        "cls": p["race_class"], "type": (p["run_type"] or "").title(), "pos": pos,
                        "ran": p["runners"], "btn": f["beaten"] if f else None, "sp": p["odds"],
                        "or": p["bha"], "fig": f["fig"] if f else None, "fig2": f.get("fig2") if f else None,
                        "comment": p["comment"], "matched": bool(f)})
    else:
        for f in figs[:6]:
            out.append({"date": f["date"], "course": f["course"], "dist": f["dist"], "going": f["going"],
                        "cls": _cls(f["cls"]), "type": f["code"], "pos": f["pos"], "ran": f["ran"],
                        "btn": f["beaten"], "sp": None, "or": _int(f["offr"]), "fig": f["fig"],
                        "fig2": f.get("fig2"), "comment": None, "matched": True})
    return out


def _cls(c):
    try:
        return str(int(float(c)))
    except (TypeError, ValueError):
        return c or ""


def _int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def race(race_id):
    rs = q(CARDS, "SELECT * FROM races WHERE race_id=?", (race_id,))
    if not rs:
        return None
    r = rs[0]
    fam = race_family(r["name"], r["surface"])
    r["family"] = fam
    yr = int(r["date"][:4])
    runners = q(CARDS, "SELECT * FROM runners WHERE race_id=? ORDER BY cloth", (race_id,))
    for h in runners:
        prev = q(CARDS, "SELECT * FROM prev_runs WHERE ride_id=? ORDER BY n", (h["ride_id"],))
        foal = yr - h["age"] if h["age"] else None
        figs = horse_figs(h["horse_norm"], foal, r["date"])
        h["ratings"] = ratings(figs, fam)
        h["form_runs"] = build_form(prev, figs)
        h["nr"] = (h["status"] or "RUNNER").upper() not in ("RUNNER", "")
    # rankings on best-3 (fallback best) among declared runners
    act = [h for h in runners if not h["nr"]]
    juv = (r.get("age_band") or "").upper().startswith("2YO") and any(
        h["ratings"]["best3_2yo"] is not None for h in act)
    r["rank_basis"] = "2yo scale, best-3 avg" if juv else "best-3 avg"

    def key(h):
        rt = h["ratings"]
        if juv:
            return rt["best3_2yo"]
        return rt["best3"] if rt["best3"] is not None else rt["best"]
    ranked = sorted([h for h in act if key(h) is not None], key=key, reverse=True)
    for i, h in enumerate(ranked):
        h["rank"] = i + 1
    for h in runners:
        h.setdefault("rank", None)
    r["rated"] = len(ranked)
    r["active"] = len(act)
    r["runners"] = runners
    return r


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path == "/api/meta":
                ds = dates_available()
                today = dt.date.today().isoformat()
                return self.send(200, json.dumps({"today": today, "dates": ds, "figs": META}))
            if u.path == "/api/card":
                d = qs.get("date", [dt.date.today().isoformat()])[0]
                return self.send(200, json.dumps(card(d)))
            m = re.match(r"^/api/race/(\d+)$", u.path)
            if m:
                r = race(int(m.group(1)))
                return self.send(200 if r else 404, json.dumps(r))
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            fp = os.path.normpath(os.path.join(STATIC, path))
            if fp.startswith(STATIC) and os.path.isfile(fp):
                ct = {"html": "text/html", "js": "application/javascript", "css": "text/css",
                      "png": "image/png", "svg": "image/svg+xml"}.get(fp.rsplit(".", 1)[-1], "application/octet-stream")
                with open(fp, "rb") as f:
                    return self.send(200, f.read(), ct)
            return self.send(404, "not found", "text/plain")
        except Exception as e:  # keep the server alive
            return self.send(500, json.dumps({"error": str(e)}))


def main():
    global META
    META = figcache.build() or {}
    if not os.path.exists(CARDS):
        print("No data\\cards.sqlite yet - run GET_TODAYS_CARDS.bat first.")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://localhost:{PORT}"
    print(f"Racing site running at {url}  (close this window to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
