import "server-only";
import {
  cacheVersion, qCardDates, qFigMeta, qFigs, qHasCards, qMeetings, qPace, qPredToday, qPrevRuns, qRace, qRacesByDate, qRacesFullByDate, qRunners, qRunnersByDate, qSectionals, qWinPct,
  type Row,
} from "./store";
import { bundledPayload, parsePayload, predictFromFigs, storedPreds, type Pred, type PredPayload } from "./predict";

const JUMPS = ["Hurdle", "Chase", "NHF"];
const isJumps = (code: string | null | undefined) => JUMPS.includes(code ?? "");

export type Ratings = {
  last: number | null; best: number | null; best3: number | null; avg3: number | null;
  best2yo: number | null; best3_2yo: number | null; nfigs: number; family_used: "jumps" | "flat";
};
export type PaceInfo = {
  label: "true" | "steady" | "slow" | "fast-early" | "unknown";
  figRel: "ok" | "low" | "suspect";
  reason: string;
  source: string;
  fsp: number | null;
  fieldDef: number | null;
};
export type SectionPoint = { k: number; vs: number };
export type SectionalRun = {
  date: string; course: string; n: number; pace_label: string;
  fin_speed_pct: number | null; fig_adj: number | null; fig: number | null;
  run_style: string | null; style_pct: number | null; sectors: SectionPoint[];
};
export type FormRun = {
  date: string; course: string; dist: string; going: string; cls: string; type: string; pos: string;
  ran: number | null; btn: number | null; sp: string | null; or: number | null; fig: number | null;
  fig2: number | null; comment: string | null; matched: boolean;
  /** race conditions of that run, normalised for comparing with today's race */
  code: string; dist_f: number | null; going_n: number | null; aw: boolean; cls_n: number | null;
  /** how that run compares with today's race (cls null = class unknown) */
  fit: Fit;
  pace: PaceInfo | null;
  fin_speed_pct: number | null; fig_adj: number | null;
  run_style: string | null; sectors: SectionPoint[];
};
export type Fit = { code: boolean; dist: boolean; going: boolean; cls: boolean | null; all: boolean };
export type Conditions = { code: string; dist_f: number | null; going_n: number | null; aw: boolean; cls_n: number | null };
export type CondBest = { fig: number; n: number; date: string; course: string } | null;
export type ClassChange = {
  dir: "drop" | "rise"; today: number; last: number | null; avg: number | null; n: number;
};
export type Runner = Row & {
  ratings: Ratings; form_runs: FormRun[]; nr: boolean; rank: number | null; cond_best: CondBest;
  class_change: ClassChange | null; or_delta: number | null;
  pred: number | null; pred_lo: number | null; pred_hi: number | null;
  win_pct: number | null; fair_odds: number | null;
  sectionals: SectionalRun[];
};
export type Race = Row & {
  race_id: number; time: string; course: string; name: string; date: string; family: string;
  rank_basis: string; rated: number; active: number; runners: Runner[]; cond: Conditions;
};
export type Meeting = Row & { meeting_id: number; course: string; going: string | null; first: string; races: Row[] };
export type FigMeta = { version?: string; max_date?: string; rows?: string; built?: string; has_2yo?: string };

const LONDON = "Europe/London";

export function localDate(d = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: LONDON, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(d);
  const g = (t: string) => parts.find((p) => p.type === t)!.value;
  return `${g("year")}-${g("month")}-${g("day")}`;
}
export function localTime(d = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: LONDON, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d);
  const g = (t: string) => parts.find((p) => p.type === t)!.value;
  return `${g("hour")}:${g("minute")}`;
}

export async function figMeta(): Promise<FigMeta | null> {
  const rows = await qFigMeta();
  if (!rows.length) return null;
  return Object.fromEntries(rows.map((r) => [r.k, r.v]));
}

export async function datesAvailable(): Promise<string[]> {
  if (!(await qHasCards())) return [];
  return qCardDates();
}

/** Today's date if we have cards for it, otherwise the most recent card date. */
export async function cardDate(): Promise<{ date: string; isToday: boolean }> {
  const today = localDate();
  const ds = await datesAvailable();
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

export async function card(date: string): Promise<Meeting[]> {
  if (!(await qHasCards())) return [];
  const meetings = (await qMeetings(date)) as Meeting[];
  const races = await qRacesByDate(date);
  for (const m of meetings) {
    m.races = races.filter((r) => r.meeting_id === m.meeting_id);
    m.first = m.races[0]?.time ?? "99";
  }
  return meetings.sort((a, b) => a.first.localeCompare(b.first));
}

/** The next race to run today (or the first race of the card). */
export async function nextRaceId(date: string, isToday: boolean): Promise<number | null> {
  const all = (await card(date)).flatMap((m) => m.races).sort((a, b) => a.time.localeCompare(b.time));
  if (!all.length) return null;
  const now = localTime();
  return (isToday ? all.find((r) => r.time >= now) : undefined)?.race_id ?? all[0].race_id;
}

function figsForHorse(all: Row[], norm: string | null, foalYear: number | null): Row[] {
  if (!norm) return [];
  let rows = all.filter((r) => r.horse_norm === norm);
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

const FORM_N = 8; // runs shown on the card (oldest -> newest in the chart)

/** "2m 4f 116y" / "1m 142y" / "6f 20y" -> furlongs */
export function distF(d: string | null | undefined): number | null {
  const s = String(d ?? "").toLowerCase();
  const m = /(\d+)\s*m/.exec(s), f = /(\d+)\s*f/.exec(s), y = /(\d+)\s*y/.exec(s);
  if (!m && !f && !y) return null;
  return (m ? +m[1] * 8 : 0) + (f ? +f[1] : 0) + (s.includes("\u00bd") ? 0.5 : 0) + (y ? +y[1] / 220 : 0);
}
const STD = /standard|slow|fast|polytrack|tapeta/i;
/** Turf going on a 1 (firm) .. 6 (heavy) scale; null for all-weather / unknown. Uses the main description, not "(... in places)". */
export function goingN(g: string | null | undefined): number | null {
  const s = String(g ?? "").toLowerCase().replace(/\(.*$/, "").trim();
  if (!s || STD.test(s)) return null;
  const T: [string, number][] = [
    ["soft to heavy", 5.5], ["yielding to soft", 4.5], ["good to yielding", 3.5], ["good to soft", 4], ["good to firm", 2],
    ["heavy", 6], ["soft", 5], ["yielding", 4], ["good", 3], ["firm", 1],
  ];
  for (const [k, v] of T) if (s.startsWith(k)) return v;
  return null;
}
const titleCase = (t: string) => t.replace(/\w\S*/g, (w: string) => w[0].toUpperCase() + w.slice(1).toLowerCase());
/** Flat / AW / Hurdle / Chase / NHF */
function codeOf(kind: string | null | undefined, aw: boolean): string {
  const k = String(kind ?? "").toUpperCase().replace(/[^A-Z]/g, "");
  if (k.includes("CHASE")) return "Chase";
  if (k.includes("HURDLE")) return "Hurdle";
  if (k.includes("NHF") || k.includes("NHFLAT") || k.includes("BUMPER")) return "NHF";
  return aw ? "AW" : "Flat";
}
const clsN = (c: any) => { const n = parseInt(String(c ?? ""), 10); return Number.isFinite(n) && n > 0 ? n : null; };

function fit(run: Conditions, today: Conditions): Fit {
  const code = run.code === today.code;
  const dist = run.dist_f != null && today.dist_f != null && Math.abs(run.dist_f - today.dist_f) <= Math.max(1, today.dist_f * 0.1) + 1e-6;
  const going = run.aw || today.aw ? run.aw === today.aw
    : run.going_n != null && today.going_n != null && Math.abs(run.going_n - today.going_n) <= 1;
  const cls = run.cls_n == null || today.cls_n == null ? null : Math.abs(run.cls_n - today.cls_n) <= 1;
  return { code, dist, going, cls, all: code && dist && going && cls !== false };
}

function figConditions(f: Row): Conditions {
  const aw = f.surface === "AW";
  return { code: codeOf(f.code, aw), dist_f: f.dist_f ?? distF(f.dist), going_n: goingN(f.going), aw, cls_n: clsN(f.cls) };
}

/** Best figure (and how many runs) at today's conditions, over the horse's whole history before today. */
function condBest(figs: Row[], today: Conditions, juv: boolean): CondBest {
  let best: CondBest = null, n = 0;
  const seen = new Set<string>();
  for (const f of figs) {
    if (seen.has(f.date)) continue;
    seen.add(f.date);
    const v = juv ? f.fig2 : f.fig;
    if (typeof v !== "number" || Number.isNaN(v) || !fit(figConditions(f), today).all) continue;
    n++;
    if (!best || v > best.fig) best = { fig: v, n: 0, date: f.date, course: f.course };
  }
  return best ? { ...best, n } : null;
}

/** Sporting Life previous runs merged with our figures (by date), topped up with older runs from our figures. Last 8 runs. */
function buildForm(prev: Row[], figs: Row[], today: Conditions): FormRun[] {
  const byDate = new Map<string, Row>();
  for (const f of figs) if (!byDate.has(f.date)) byDate.set(f.date, f);
  const out: FormRun[] = [];
  for (const p of prev.slice(0, FORM_N)) {
    const f = byDate.get(p.date);
    const pos = p.position ? String(p.position) : OUTCOME[p.outcome ?? ""] ?? (p.outcome ?? "-").slice(0, 3);
    const aw = f ? f.surface === "AW" : STD.test(String(p.going ?? ""));
    const c: Conditions = {
      code: codeOf(p.run_type, aw), dist_f: distF(p.distance) ?? f?.dist_f ?? null, going_n: goingN(p.going), aw,
      cls_n: clsN(p.race_class) ?? clsN(f?.cls),
    };
    out.push({
      date: p.date, course: p.course, dist: p.distance, going: p.going, cls: p.race_class ?? "",
      type: titleCase(p.run_type ?? "").replace("N_h_flat", "NH Flat"),
      pos, ran: p.runners, btn: f?.beaten ?? null, sp: p.odds, or: p.bha, fig: f?.fig ?? null,
      fig2: f?.fig2 ?? null, comment: p.comment, matched: !!f, ...c, fit: fit(c, today), pace: null, fin_speed_pct: null, fig_adj: null, run_style: null, sectors: [],
    });
  }
  const oldest = out.length ? out[out.length - 1].date : "9999";
  const used = new Set(out.map((r) => r.date));
  for (const f of figs) {
    if (out.length >= FORM_N) break;
    if (used.has(f.date) || f.date >= oldest) continue;
    used.add(f.date);
    const c = figConditions(f);
    out.push({
      date: f.date, course: String(f.course ?? "").replace(/\s*\((IRE|FR|GB|USA)\)$/, ""), dist: f.dist, going: f.going, cls: cls(f.cls), type: f.code ?? "",
      pos: f.pos == null ? "" : String(f.pos), ran: f.ran, btn: f.beaten, sp: null, or: int(f.offr), fig: f.fig,
      fig2: f.fig2 ?? null, comment: null, matched: true, ...c, fit: fit(c, today), pace: null, fin_speed_pct: null, fig_adj: null, run_style: null, sectors: [],
    });
  }
  return out;
}


/** Class 1 is the highest grade. A "drop" means today is easier (a higher class number) than recent runs. */
export function classChange(form: FormRun[], todayCls: number | null, todayCode: string): ClassChange | null {
  if (todayCls == null) return null;
  const last3 = form.slice(0, 3);
  const withCls = last3.filter((f) => f.cls_n != null);
  const same = withCls.filter((f) => isJumps(f.code) === isJumps(todayCode));
  const used = same.length ? same : withCls;
  if (!used.length) return null;
  const last = used[0].cls_n!;
  const n = used.length;
  const avg = Math.round((used.reduce((a, f) => a + f.cls_n!, 0) / n) * 10) / 10;
  const lastDelta = todayCls - last;
  const avgDelta = todayCls - avg;
  let dir: "drop" | "rise" | null = null;
  // Prefer the last run when it differs by a full class; otherwise use the recent average.
  if (Math.abs(lastDelta) >= 1) dir = lastDelta > 0 ? "drop" : "rise";
  else if (avgDelta >= 0.5) dir = "drop";
  else if (avgDelta <= -0.5) dir = "rise";
  if (!dir) return null;
  return { dir, today: todayCls, last, avg, n };
}

/** Official-rating change since the last run in the same discipline (jumps or Flat/AW). */
export function orChange(form: FormRun[], todayOr: number | null, todayCode: string): number | null {
  if (todayOr == null) return null;
  const last = form.find((f) => f.or != null && isJumps(f.code) === isJumps(todayCode));
  if (last?.or == null) return null;
  const d = todayOr - last.or;
  return d === 0 ? null : d;
}




/** 'Fontwell Park' / 'Fontwell', 'Market Rasen' / 'MarketRasen', 'Gowran Park' / 'GowranPark' -> same key. */
export function normCourse(name: string | null | undefined): string {
  let n = String(name ?? "").toLowerCase().replace(/\(.*?\)/g, " ");
  n = n.split(/[^a-z]+/).filter((w) => w && !["park", "the", "downs", "city", "racecourse", "aw"].includes(w)).join("");
  // 'GowranPark' comes through as one word; still drop a trailing park/downs/city.
  return n.replace(/(park|downs|city|racecourse)$/, "");
}

const dayOf = (d: unknown) => String(d ?? "").slice(0, 10);

function courseKeys(name: string | null | undefined): string[] {
  const cn = normCourse(name);
  const keys = [cn, String(name ?? "").toLowerCase().replace(/\(.*?\)/g, "").replace(/[^a-z]/g, "")];
  if (cn) keys.push(cn + "park");
  return [...new Set(keys.filter(Boolean))];
}

const SLOW_CMT = /slowly[\s-]?run|sedate(?:ly)?(?:\s+run|\s+pace)?|false pace|no pace|lack of pace|crawled|crawling early|steadily[\s-]?run|steady(?:ish)? pace|dictated (?:a |the )?(?:slow |steady )?pace|set (?:a |the )?modest pace|uncontested (?:lead|pace)/i;
const KEEN_CMT = /keen hold|pulled hard|took a keen hold|took keen hold|racing keenly|ran too freely|too freely/i;
const SPRINT_CMT = /sprint finish|turned into a sprint/i;

/** Weak fallback from the in-running comment, used only when we have no precomputed pace. */
export function commentPace(comment: string | null | undefined): PaceInfo | null {
  const s = String(comment ?? "");
  if (!s) return null;
  const slow = SLOW_CMT.test(s), keen = KEEN_CMT.test(s), sprint = SPRINT_CMT.test(s);
  if (!slow && !keen && !sprint) return null;
  const hardSlow = slow && /slowly|false pace|crawl|sedate|no pace|lack of pace/i.test(s);
  const label: PaceInfo["label"] = hardSlow || sprint ? "slow" : "steady";
  const figRel: PaceInfo["figRel"] = hardSlow || sprint ? "low" : "ok";
  const reason = hardSlow ? "Comment suggests a slowly run race"
    : sprint ? "Comment mentions a sprint finish"
    : slow ? "Comment suggests a steadily run race"
    : "Comment suggests a keen / pulling horse (often a slow pace)";
  return { label, figRel, reason, source: "comments", fsp: null, fieldDef: null };
}

function rowToPace(r: Row): PaceInfo {
  let label: PaceInfo["label"] = r.label === "slow" || r.label === "steady" || r.label === "true" || r.label === "fast-early" ? r.label : "unknown";
  const figRel = r.fig_rel === "low" || r.fig_rel === "suspect" ? r.fig_rel : "ok";
  const fieldDef = r.field_def != null && Number.isFinite(Number(r.field_def)) ? Number(r.field_def) : null;
  // A mid-range field check is still evidence: the race was not a slow-run or a soft standard.
  if (label === "unknown" && fieldDef != null) label = "true";
  return {
    label, figRel,
    reason: String(r.reason ?? ""),
    source: String(r.source ?? ""),
    fsp: r.fsp != null && Number.isFinite(Number(r.fsp)) ? Number(r.fsp) : null,
    fieldDef,
  };
}

function matchPace(run: FormRun, horseNorm: string, list: Row[]): PaceInfo | null {
  const keys = courseKeys(run.course);
  const day = list.filter((r) => dayOf(r.date) === dayOf(run.date) && keys.includes(String(r.course_norm ?? "")));
  const pickFrom = (rows: Row[]): Row | null => {
    let pick = rows;
    if (pick.length > 1 && run.dist_f != null) {
      const close = pick.filter((r) => r.dist_f != null && Math.abs(Number(r.dist_f) - run.dist_f!) <= 0.6);
      if (close.length) pick = close;
    }
    if (pick.length > 1 && run.code) {
      const same = pick.filter((r) => r.code === run.code);
      if (same.length) pick = same;
    }
    return pick[0] ?? null;
  };
  const byHorse = horseNorm ? day.filter((r) => String(r.horses ?? "").split(",").includes(horseNorm)) : [];
  const hit = pickFrom(byHorse.length ? byHorse : day);
  const cmt = commentPace(run.comment);
  if (!hit) return cmt;
  const p = rowToPace(hit);
  if (p.label === "unknown") return cmt;
  if (cmt && (cmt.label === "slow" || cmt.label === "steady") && p.reason && !/comment/i.test(p.reason)) {
    p.reason = `${p.reason}. ${cmt.reason}`;
  }
  return p;
}

function attachPace(race: Race, rows: Row[]): void {
  for (const h of race.runners) {
    const norm = String(h.horse_norm ?? "");
    for (const f of h.form_runs) f.pace = matchPace(f, norm, rows);
  }
}

async function withPace(races: Race[]): Promise<Race[]> {
  const dates = [...new Set(
    races.flatMap((r) => r.runners.flatMap((h) => h.form_runs.map((f) => dayOf(f.date))))
      .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)),
  )];
  let rows: Row[] = [];
  try { rows = await qPace(dates); } catch { rows = []; }
  for (const r of races) attachPace(r, rows);
  return races;
}


function parseSectors(raw: unknown): SectionPoint[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.filter((p) => p && Number.isFinite(Number(p.k)) && Number.isFinite(Number(p.vs))).map((p) => ({ k: Number(p.k), vs: Number(p.vs) }));
  try {
    const v = JSON.parse(String(raw));
    return Array.isArray(v) ? parseSectors(v) : [];
  } catch { return []; }
}

function paceFromSec(s: SectionalRun): PaceInfo | null {
  const raw = (s.pace_label || "").toLowerCase().replace(/\s+/g, "-");
  const label: PaceInfo["label"] = raw === "true" || raw === "steady" || raw === "slow" || raw === "fast-early" ? raw : "unknown";
  if (label === "unknown") return null;
  const figRel: PaceInfo["figRel"] = label === "slow" ? "low" : label === "fast-early" ? "suspect" : "ok";
  const reason = label === "true" ? "Truly run race (sectional pace)."
    : label === "steady" ? "Steady early pace (sectional)."
    : label === "slow" ? "Slow-run race; finishing speed high relative to a modest early pace."
    : "Went too fast early; the raw figure may overstate the performance.";
  return { label, figRel, reason, source: "sectionals", fsp: s.fin_speed_pct, fieldDef: null };
}

function toSectional(r: Row): SectionalRun {
  const n = (v: unknown) => (v != null && v !== "" && Number.isFinite(Number(v)) ? Number(v) : null);
  return {
    date: String(r.date ?? "").slice(0, 10),
    course: String(r.course ?? ""),
    n: Number(r.n) || 0,
    pace_label: String(r.pace_label ?? ""),
    fin_speed_pct: n(r.fin_speed_pct),
    fig_adj: n(r.fig_adj),
    fig: n(r.fig),
    run_style: r.run_style ? String(r.run_style) : null,
    style_pct: n(r.style_pct),
    sectors: parseSectors(r.sectors),
  };
}

function attachSectionals(race: Race, rows: Row[]): void {
  const byHorse = new Map<string, SectionalRun[]>();
  for (const r of rows) {
    const s = toSectional(r);
    const list = byHorse.get(String(r.horse_norm ?? "")) ?? [];
    list.push(s);
    byHorse.set(String(r.horse_norm ?? ""), list);
  }
  for (const list of byHorse.values()) list.sort((a, b) => a.n - b.n);
  for (const h of race.runners) {
    const list = byHorse.get(String(h.horse_norm ?? "")) ?? [];
    h.sectionals = list;
    for (const f of h.form_runs) {
      const day = String(f.date).slice(0, 10);
      const hit = list.find((s) => s.date === day);
      if (!hit) continue;
      f.fin_speed_pct = hit.fin_speed_pct;
      f.fig_adj = hit.fig_adj;
      f.run_style = hit.run_style;
      f.sectors = hit.sectors;
      const secPace = paceFromSec(hit);
      if (!secPace) {
        if (f.pace && f.pace.fsp == null && hit.fin_speed_pct != null) f.pace = { ...f.pace, fsp: hit.fin_speed_pct };
        continue;
      }
      if (!f.pace || f.pace.label === "unknown" || f.pace.source === "comments" || secPace.label === "fast-early") {
        if (f.pace?.reason && f.pace.source !== "comments" && secPace.label !== "fast-early") {
          secPace.reason = f.pace.reason;
          secPace.figRel = f.pace.figRel;
        }
        if (secPace.fsp == null) secPace.fsp = f.pace?.fsp ?? null;
        f.pace = secPace;
      } else if (f.pace.fsp == null && hit.fin_speed_pct != null) {
        f.pace = { ...f.pace, fsp: hit.fin_speed_pct };
      }
    }
  }
}

async function withSectionals(races: Race[]): Promise<void> {
  const norms = [...new Set(races.flatMap((r) => r.runners.map((h) => String(h.horse_norm ?? "")).filter(Boolean)))];
  if (!norms.length) return;
  let rows: Row[] = [];
  try { rows = await qSectionals(norms); } catch { rows = []; }
  for (const r of races) attachSectionals(r, rows);
}


type WinRow = { win_pct: number; fair_odds: number | null };
type PredCtx = { payload: PredPayload | null; stored: Map<number, Pred>; win: Map<number, WinRow> };

async function loadPredContext(date: string): Promise<PredCtx> {
  const metaRows = await qFigMeta();
  const meta = Object.fromEntries(metaRows.map((r) => [r.k, r.v]));
  const payload = parsePayload(meta.pred_model) ?? bundledPayload();
  const stored = storedPreds(meta.pred_today, date);
  try {
    for (const r of await qPredToday(date)) {
      if (r?.pred == null) continue;
      stored.set(Number(r.ride_id), {
        pred: Number(r.pred),
        lo: r.lo != null ? Number(r.lo) : Number(r.pred),
        hi: r.hi != null ? Number(r.hi) : Number(r.pred),
        best3: r.best3 != null ? Number(r.best3) : null,
        last_fig: r.last_fig != null ? Number(r.last_fig) : null,
        n_prior: Number(r.n_prior ?? 0),
        scale: r.scale === "2yo" ? "2yo" : "all",
      });
    }
  } catch { /* pred_today table is optional */ }
  const win = new Map<number, WinRow>();
  try {
    const raw = meta.win_pct_today;
    if (raw) {
      const arr = JSON.parse(String(raw));
      if (Array.isArray(arr)) {
        for (const row of arr) {
          if (!row || row.win_pct == null || row.ride_id == null) continue;
          if (row.date && String(row.date).slice(0, 10) !== date) continue;
          win.set(Number(row.ride_id), {
            win_pct: Number(row.win_pct),
            fair_odds: row.fair_odds != null ? Number(row.fair_odds) : null,
          });
        }
      }
    }
  } catch { /* optional fig_meta fallback */ }
  try {
    for (const r of await qWinPct(date)) {
      if (r?.win_pct == null) continue;
      win.set(Number(r.ride_id), {
        win_pct: Number(r.win_pct),
        fair_odds: r.fair_odds != null ? Number(r.fair_odds) : null,
      });
    }
  } catch { /* win_pct table is optional */ }
  return { payload, stored, win };
}

function decorateRace(r: Row, runners: Runner[], prevByRide: Map<number, Row[]>, figsByHorse: Map<string, Row[]>, ctx: PredCtx): Race {
  const race = r as Race;
  const fam = raceFamily(race.name);
  race.family = fam;
  const yr = Number(String(race.date).slice(0, 4));
  const aw = String(race.surface ?? "").toUpperCase().startsWith("ALL") || STD.test(String(race.going ?? ""));
  race.cond = { code: codeOf(fam, aw), dist_f: distF(race.distance), going_n: goingN(race.going), aw, cls_n: clsN(race.race_class) };
  for (const h of runners) {
    const prev = prevByRide.get(h.ride_id) ?? [];
    const figs = figsForHorse(figsByHorse.get(h.horse_norm) ?? [], h.horse_norm, h.age ? yr - h.age : null);
    h.ratings = ratings(figs, fam);
    h.form_runs = buildForm(prev, figs, race.cond);
    h.class_change = classChange(h.form_runs, race.cond.cls_n, race.cond.code);
    h.or_delta = orChange(h.form_runs, int(h.official_rating), race.cond.code);
    (h as Row)._figs = figs;
    h.nr = !["RUNNER", ""].includes(String(h.status ?? "RUNNER").toUpperCase());
    h.rank = null;
    h.pred = null; h.pred_lo = null; h.pred_hi = null;
    h.win_pct = null; h.fair_odds = null;
    h.sectionals = [];
  }
  const act = runners.filter((h) => !h.nr);
  const juv = String(race.age_band ?? "").toUpperCase().startsWith("2YO") && act.some((h) => h.ratings.best3_2yo != null);
  race.rank_basis = juv ? "2yo scale, predicted today" : "predicted today";
  for (const h of runners) {
    const figs = ((h as Row)._figs ?? []) as Row[];
    h.cond_best = condBest(figs, race.cond, juv);
    const fromStore = ctx.stored.get(h.ride_id);
    const computed = predictFromFigs(figs, {
      date: String(race.date), code: race.cond.code, aw: race.cond.aw, dist_f: race.cond.dist_f,
      going_n: race.cond.going_n, cls: race.cond.cls_n, age: h.age ?? null,
      or_: int(h.official_rating), days: h.last_ran_days ?? null,
    }, ctx.payload, juv);
    const p = fromStore ?? computed;
    h.pred = p?.pred ?? null;
    h.pred_lo = p?.lo ?? null;
    h.pred_hi = p?.hi ?? null;
    const w = ctx.win.get(h.ride_id);
    h.win_pct = w?.win_pct ?? null;
    h.fair_odds = w?.fair_odds ?? null;
    delete (h as Row)._figs;
  }
  const key = (h: Runner) => h.pred;
  act.filter((h) => key(h) != null).sort((a, b) => key(b)! - key(a)! || (a.cloth ?? 0) - (b.cloth ?? 0)).forEach((h, i) => (h.rank = i + 1));
  race.rated = runners.filter((h) => h.rank != null).length;
  race.active = act.length;
  race.runners = runners;
  return race;
}

function groupPrev(rows: Row[]): Map<number, Row[]> {
  const m = new Map<number, Row[]>();
  for (const r of rows) {
    const list = m.get(r.ride_id) ?? [];
    list.push(r);
    m.set(r.ride_id, list);
  }
  return m;
}

function groupFigs(rows: Row[]): Map<string, Row[]> {
  const m = new Map<string, Row[]>();
  for (const r of rows) {
    const list = m.get(r.horse_norm) ?? [];
    list.push(r);
    m.set(r.horse_norm, list);
  }
  for (const list of m.values()) list.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return m;
}

export async function race(raceId: number): Promise<Race | null> {
  const r = await qRace(raceId);
  if (!r) return null;
  const runners = (await qRunners(raceId)) as Runner[];
  const prev = await qPrevRuns(runners.map((h) => h.ride_id));
  const norms = [...new Set(runners.map((h) => h.horse_norm).filter(Boolean))];
  const figs = await qFigs(norms, r.date);
  const ctx = await loadPredContext(String(r.date));
  const race = decorateRace(r, runners, groupPrev(prev), groupFigs(figs), ctx);
  await withPace([race]);
  await withSectionals([race]);
  return race;
}

/** All races on a date, with runners/form/figures, in as few store reads as possible. */
export async function racesOn(date: string): Promise<Race[]> {
  const full = await qRacesFullByDate(date);
  if (!full.length) return [];
  const runners = (await qRunnersByDate(date)) as Runner[];
  const prev = await qPrevRuns(runners.map((h) => h.ride_id));
  const norms = [...new Set(runners.map((h) => h.horse_norm).filter(Boolean))];
  const figs = await qFigs(norms, full[0].date);
  const prevBy = groupPrev(prev);
  const figsBy = groupFigs(figs);
  const ctx = await loadPredContext(String(full[0].date));
  const byRace = new Map<number, Runner[]>();
  for (const h of runners) {
    const list = byRace.get(h.race_id) ?? [];
    list.push(h);
    byRace.set(h.race_id, list);
  }
  const out = full
    .sort((a, b) => String(a.time).localeCompare(String(b.time)))
    .map((r) => decorateRace(r, (byRace.get(r.race_id) ?? []).slice(), prevBy, figsBy, ctx));
  await withPace(out);
  await withSectionals(out);
  return out;
}

export { cacheVersion };
