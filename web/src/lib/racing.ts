import "server-only";
import { CACHE, CARDS, hasTable, q, type Row } from "./db";

const JUMPS = ["Hurdle", "Chase", "NHF"];
const isJumps = (code: string | null | undefined) => JUMPS.includes(code ?? "");

export type Ratings = {
  last: number | null; best: number | null; best3: number | null; avg3: number | null;
  best2yo: number | null; best3_2yo: number | null; nfigs: number; family_used: "jumps" | "flat";
};
export type FormRun = {
  date: string; course: string; dist: string; going: string; cls: string; type: string; pos: string;
  ran: number | null; btn: number | null; sp: string | null; or: number | null; fig: number | null;
  fig2: number | null; comment: string | null; matched: boolean;
};
export type Runner = Row & { ratings: Ratings; form_runs: FormRun[]; nr: boolean; rank: number | null };
export type Race = Row & {
  race_id: number; time: string; course: string; name: string; date: string; family: string;
  rank_basis: string; rated: number; active: number; runners: Runner[];
};
export type Meeting = Row & { meeting_id: number; course: string; going: string | null; first: string; races: Row[] };
export type FigMeta = { version?: string; max_date?: string; rows?: string; built?: string; has_2yo?: string };

export function localDate(d = new Date()): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
export function localTime(d = new Date()): string {
  return d.toTimeString().slice(0, 5);
}

export function figMeta(): FigMeta | null {
  if (!hasTable(CACHE, "meta")) return null;
  return Object.fromEntries(q(CACHE, "SELECT k, v FROM meta").map((r) => [r.k, r.v]));
}

export function datesAvailable(): string[] {
  if (!hasTable(CARDS, "races")) return [];
  return q(CARDS, "SELECT DISTINCT date FROM races ORDER BY date DESC").map((r) => r.date);
}

/** Today's date if we have cards for it, otherwise the most recent card date. */
export function cardDate(): { date: string; isToday: boolean } {
  const today = localDate();
  const ds = datesAvailable();
  const date = ds.includes(today) ? today : ds[0] ?? today;
  return { date, isToday: date === today };
}

export function raceFamily(name: string | null): string {
  const n = (name ?? "").toLowerCase();
  if (n.includes("chase")) return "Chase";
  if (n.includes("hurdle")) return "Hurdle";
  if (["bumper", "national hunt flat", "nh flat", "inh flat"].some((k) => n.includes(k))) return "NHF";
  return "Flat";
}

export function card(date: string): Meeting[] {
  if (!hasTable(CARDS, "races")) return [];
  const meetings = q(CARDS, "SELECT * FROM meetings WHERE date=? ORDER BY course", [date]) as Meeting[];
  const races = q(CARDS, "SELECT race_id,meeting_id,time,course,name,race_class,distance,going,ride_count,stage FROM races WHERE date=? ORDER BY time", [date]);
  for (const m of meetings) {
    m.races = races.filter((r) => r.meeting_id === m.meeting_id);
    m.first = m.races[0]?.time ?? "99";
  }
  return meetings.sort((a, b) => a.first.localeCompare(b.first));
}

/** The next race to run today (or the first race of the card). */
export function nextRaceId(date: string, isToday: boolean): number | null {
  const all = card(date).flatMap((m) => m.races).sort((a, b) => a.time.localeCompare(b.time));
  if (!all.length) return null;
  const now = localTime();
  return (isToday ? all.find((r) => r.time >= now) : undefined)?.race_id ?? all[0].race_id;
}

function horseFigs(norm: string | null, foalYear: number | null, before: string): Row[] {
  if (!norm || !hasTable(CACHE, "figs")) return [];
  let rows = q(CACHE, "SELECT * FROM figs WHERE horse_norm=? AND date<? ORDER BY date DESC", [norm, before]);
  // a name clash with a different-aged horse -> keep only the runs from the matching foal year
  if (foalYear && rows.length) rows = rows.filter((r) => r.foal_year != null && Math.abs(r.foal_year - foalYear) < 0.5);
  return rows;
}

const avg = (xs: number[]) => (xs.length ? Math.round((xs.reduce((a, b) => a + b, 0) / xs.length) * 10) / 10 : null);
const nums = (xs: any[]) => xs.filter((v): v is number => typeof v === "number" && !Number.isNaN(v));

function ratings(figs: Row[], family: string): Ratings {
  const jumps = JUMPS.includes(family);
  const famRows = figs.filter((r) => isJumps(r.code) === jumps);
  const fam = famRows.length ? famRows : figs;
  const vals = nums(fam.map((r) => r.fig));
  const recent = nums(fam.slice(0, 12).map((r) => r.fig));
  const two = nums(figs.map((r) => r.fig2));
  const top3 = [...recent].sort((a, b) => b - a).slice(0, 3);
  const two3 = two.slice(0, 12).sort((a, b) => b - a).slice(0, 3);
  return {
    last: vals[0] ?? null,
    best: vals.length ? Math.max(...vals) : null,
    best3: avg(top3),
    avg3: avg(vals.slice(0, 3)),
    best2yo: two.length ? Math.max(...two) : null,
    best3_2yo: avg(two3),
    nfigs: vals.length,
    family_used: jumps ? "jumps" : "flat",
  };
}

const OUTCOME: Record<string, string> = {
  PulledUp: "PU", Fell: "F", UnseatedRider: "UR", RefusedToRace: "RR", BroughtDown: "BD",
  Refused: "REF", SlippedUp: "SU", RanOut: "RO", CarriedOut: "CO",
};
const cls = (c: any) => (c == null || c === "" ? "" : Number.isFinite(Number(c)) ? String(Math.trunc(Number(c))) : String(c));
const int = (x: any) => (x == null || x === "" || !Number.isFinite(Number(x)) ? null : Math.trunc(Number(x)));

/** Sporting Life previous runs merged with our figures (by date). Last 6 runs. */
function buildForm(prev: Row[], figs: Row[]): FormRun[] {
  const byDate = new Map<string, Row>();
  for (const f of figs) if (!byDate.has(f.date)) byDate.set(f.date, f);
  if (prev.length) {
    return prev.slice(0, 6).map((p) => {
      const f = byDate.get(p.date);
      const pos = p.position ? String(p.position) : OUTCOME[p.outcome ?? ""] ?? (p.outcome ?? "-").slice(0, 3);
      return {
        date: p.date, course: p.course, dist: p.distance, going: p.going, cls: p.race_class ?? "",
        type: (p.run_type ?? "").replace(/\w\S*/g, (w: string) => w[0].toUpperCase() + w.slice(1).toLowerCase()),
        pos, ran: p.runners, btn: f?.beaten ?? null, sp: p.odds, or: p.bha, fig: f?.fig ?? null,
        fig2: f?.fig2 ?? null, comment: p.comment, matched: !!f,
      };
    });
  }
  return figs.slice(0, 6).map((f) => ({
    date: f.date, course: f.course, dist: f.dist, going: f.going, cls: cls(f.cls), type: f.code ?? "",
    pos: f.pos == null ? "" : String(f.pos), ran: f.ran, btn: f.beaten, sp: null, or: int(f.offr), fig: f.fig,
    fig2: f.fig2 ?? null, comment: null, matched: true,
  }));
}

export function race(raceId: number): Race | null {
  const rs = q(CARDS, "SELECT * FROM races WHERE race_id=?", [raceId]);
  if (!rs.length) return null;
  const r = rs[0] as Race;
  const fam = raceFamily(r.name);
  r.family = fam;
  const yr = Number(r.date.slice(0, 4));
  const runners = q(CARDS, "SELECT * FROM runners WHERE race_id=? ORDER BY cloth", [raceId]) as Runner[];
  for (const h of runners) {
    const prev = q(CARDS, "SELECT * FROM prev_runs WHERE ride_id=? ORDER BY n", [h.ride_id]);
    const figs = horseFigs(h.horse_norm, h.age ? yr - h.age : null, r.date);
    h.ratings = ratings(figs, fam);
    h.form_runs = buildForm(prev, figs);
    h.nr = !["RUNNER", ""].includes(String(h.status ?? "RUNNER").toUpperCase());
    h.rank = null;
  }
  const act = runners.filter((h) => !h.nr);
  const juv = String(r.age_band ?? "").toUpperCase().startsWith("2YO") && act.some((h) => h.ratings.best3_2yo != null);
  r.rank_basis = juv ? "2yo scale, best-3 avg" : "best-3 avg";
  const key = (h: Runner) => (juv ? h.ratings.best3_2yo : h.ratings.best3 ?? h.ratings.best);
  act.filter((h) => key(h) != null).sort((a, b) => key(b)! - key(a)!).forEach((h, i) => (h.rank = i + 1));
  r.rated = runners.filter((h) => h.rank != null).length;
  r.active = act.length;
  r.runners = runners;
  return r;
}
