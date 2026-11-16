import "server-only";
import bundled from "./pred-model.json";
import type { Row } from "./row";

const JUMPS = new Set(["Hurdle", "Chase", "NHF"]);
const STD = /standard|slow|fast|polytrack|tapeta/i;
const FLOOR = 45, CEIL = 180;
const GOING: [string, number][] = [
  ["soft to heavy", 5.5], ["yielding to soft", 4.5], ["good to yielding", 3.5],
  ["good to soft", 4], ["good to firm", 2],
  ["heavy", 6], ["soft", 5], ["yielding", 4], ["good", 3], ["firm", 1],
];

export type PredModel = {
  features: string[];
  mean: number[];
  std: number[];
  intercept: number;
  coef: number[];
  band?: number;
  residual_mae?: number;
};
export type PredPayload = {
  version?: string;
  trained?: string;
  card_model?: string;
  models: Record<string, { model: PredModel; metrics?: Row; win_rates?: Row }>;
};
export type Pred = {
  pred: number; lo: number; hi: number; best3: number | null; last_fig: number | null; n_prior: number; scale: "all" | "2yo";
};

function goingN(g: any): number | null {
  const s = String(g ?? "").toLowerCase().replace(/\(.*$/, "").trim();
  if (!s || STD.test(s)) return null;
  for (const [k, v] of GOING) if (s.startsWith(k)) return v;
  return null;
}
function codeOf(code: any, surface: any): string {
  const c = String(code ?? "").trim();
  if (JUMPS.has(c)) return c;
  const surf = String(surface ?? "").toLowerCase();
  const aw = surf.startsWith("aw") || surf.includes("all weather") || surf.includes("all-weather") || surf.startsWith("all");
  const k = c.toLowerCase();
  if (k.includes("chase")) return "Chase";
  if (k.includes("hurdle")) return "Hurdle";
  if (k.includes("nhf") || k.includes("bumper")) return "NHF";
  if (k === "aw" || aw) return "AW";
  return c || "Flat";
}
const isJumps = (c: string) => JUMPS.has(c);
function clsN(v: any): number | null {
  const n = parseFloat(String(v ?? ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}
function num(v: any): number | null {
  if (v == null || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}
function slope(ys: number[]): number | null {
  const n = ys.length;
  if (n < 3) return null;
  const xm = (n - 1) / 2, ym = ys.reduce((a, b) => a + b, 0) / n;
  let den = 0, nume = 0;
  for (let i = 0; i < n; i++) { den += (i - xm) ** 2; nume += (i - xm) * (ys[i] - ym); }
  return den <= 0 ? 0 : nume / den;
}

type Hist = {
  date: string; code: string; aw: boolean; surface?: any;
  dist_f: number | null; going_n: number | null; cls: number | null;
  or_: number | null; fig: number | null; fig2: number | null;
};
type Today = {
  date: string; code: string; aw: boolean; dist_f: number | null;
  going_n: number | null; cls: number | null; age: number | null;
  or_: number | null; days?: number | null;
};

export function figsToHist(figs: Row[]): Hist[] {
  const out: Hist[] = [];
  for (const r of figs) {
    const code = codeOf(r.code, r.surface);
    const aw = code === "AW" || String(r.surface ?? "").toLowerCase().startsWith("aw");
    out.push({
      date: String(r.date ?? "").slice(0, 10),
      code, aw, surface: r.surface,
      dist_f: num(r.dist_f), going_n: goingN(r.going), cls: clsN(r.cls),
      or_: num(r.offr), fig: num(r.fig), fig2: num(r.fig2),
    });
  }
  out.sort((a, b) => a.date.localeCompare(b.date));
  return out;
}

function featuresFromHist(hist: Hist[], today: Today, figKey: "fig" | "fig2"): Record<string, number> | null {
  if (!hist.length) return null;
  const fam = isJumps(today.code);
  const key = (r: Hist) => (figKey === "fig2" ? r.fig2 : r.fig);
  const poolAll = hist.filter((r) => key(r) != null);
  const poolFam = poolAll.filter((r) => isJumps(r.code) === fam);
  const pool = poolFam.length ? poolFam : poolAll;
  if (!pool.length) return null;

  const recent = pool.slice(-12);
  const last = key(recent[recent.length - 1])!;
  const last2 = recent.length > 1 ? key(recent[recent.length - 2])! : null;
  const last3 = recent.length > 2 ? key(recent[recent.length - 3])! : null;
  const tail = recent.slice(-8);
  const decay = tail.map((_, i) => 0.7 ** (tail.length - 1 - i));
  const wsum = decay.reduce((a, b) => a + b, 0);
  const wmean = decay.reduce((a, w, i) => a + w * key(tail[i])!, 0) / wsum;
  const top3 = [...recent].map((r) => key(r)!).sort((a, b) => b - a).slice(0, 3);
  const best3 = top3.reduce((a, b) => a + b, 0) / top3.length;
  const tr = recent.slice(-6).map((r) => key(r)!);
  const trend = slope(tr);

  const lastRun = hist[hist.length - 1];
  let days: number | null = today.days ?? null;
  if (days == null && today.date && lastRun.date) {
    const d = (Date.parse(today.date + "T12:00:00") - Date.parse(lastRun.date + "T12:00:00")) / 86400000;
    if (Number.isFinite(d)) days = d;
  }
  if (days != null) days = Math.max(0, Math.min(Math.round(days), 500));

  const tCls = today.cls;
  const lastClsRuns = [...hist].reverse().filter((r) => r.cls != null && isJumps(r.code) === fam);
  const clsSrc = lastClsRuns.length ? lastClsRuns : [...hist].reverse().filter((r) => r.cls != null);
  const lastCls = clsSrc[0]?.cls ?? null;
  const avg3src = clsSrc.slice(0, 3);
  const avg3cls = avg3src.length ? avg3src.reduce((a, r) => a + r.cls!, 0) / avg3src.length : null;
  const clsChgLast = tCls != null && lastCls != null ? tCls - lastCls : null;
  const clsChgAvg3 = tCls != null && avg3cls != null ? tCls - avg3cls : null;

  const tOr = today.or_;
  const lastOrRuns = [...hist].reverse().filter((r) => r.or_ != null && isJumps(r.code) === fam);
  const orSrc = lastOrRuns.length ? lastOrRuns : [...hist].reverse().filter((r) => r.or_ != null);
  const lastOr = orSrc[0]?.or_ ?? null;
  const orChg = tOr != null && lastOr != null ? tOr - lastOr : null;

  const trips = pool.map((r) => r.dist_f).filter((v): v is number => v != null);
  const avgTrip = trips.length ? trips.reduce((a, b) => a + b, 0) / trips.length : null;
  const distDiff = today.dist_f != null && avgTrip != null ? today.dist_f - avgTrip : null;

  const tGo = today.going_n, tAw = !!today.aw;
  const lastGo = lastRun.going_n, lastAw = !!lastRun.aw;
  let goingMatch = 0, goingDiff: number | null = null;
  if (tAw || lastAw) {
    goingMatch = tAw && lastAw ? 1 : 0;
    goingDiff = tAw && lastAw ? 0 : 2;
  } else if (tGo != null && lastGo != null) {
    goingDiff = Math.abs(tGo - lastGo);
    goingMatch = goingDiff <= 1 ? 1 : 0;
  }

  const sim: number[] = [];
  for (const r of pool) {
    const rd = r.dist_f, rg = r.going_n, raw = !!r.aw;
    const distOk = today.dist_f != null && rd != null && Math.abs(rd - today.dist_f) <= Math.max(1, today.dist_f * 0.1) + 1e-6;
    const goOk = (tAw || raw) ? (tAw && raw) : (tGo != null && rg != null && Math.abs(rg - tGo) <= 1);
    if (distOk && goOk) sim.push(key(r)!);
  }
  const simMean = sim.length ? sim.reduce((a, b) => a + b, 0) / sim.length : null;
  const nRuns = pool.length;
  const fill2 = last2 ?? last, fill3 = last3 ?? fill2;
  const code = today.code;
  const age = today.age != null && Number.isFinite(today.age) ? today.age : 5;
  const daysV = days ?? 30;

  return {
    last, last2: fill2, last3: fill3, wmean, best3, trend: trend ?? 0,
    n_runs: nRuns, light: nRuns < 8 ? 1 : 0, age, days: daysV, log_days: Math.log1p(daysV),
    cls: tCls ?? 4, cls_chg_last: clsChgLast ?? 0, cls_chg_avg3: clsChgAvg3 ?? 0,
    or_today: tOr ?? 0, or_chg: orChg ?? 0,
    same_code: lastRun.code === code ? 1 : 0, same_surf: (!!lastRun.aw) === tAw ? 1 : 0,
    dist_diff: distDiff ?? 0, going_diff: goingDiff ?? 1, going_match: goingMatch,
    sim_mean: simMean ?? wmean, n_sim: sim.length,
    is_flat: code === "Flat" ? 1 : 0, is_aw: code === "AW" ? 1 : 0,
    is_hurdle: code === "Hurdle" ? 1 : 0, is_chase: code === "Chase" ? 1 : 0, is_nhf: code === "NHF" ? 1 : 0,
    has_last2: last2 != null ? 1 : 0, has_last3: last3 != null ? 1 : 0,
    has_or: tOr != null ? 1 : 0, has_cls: tCls != null ? 1 : 0, has_sim: sim.length ? 1 : 0,
    has_days: days != null ? 1 : 0, has_trend: trend != null ? 1 : 0,
    best3_raw: best3, last_raw: last,
  };
}

export function parsePayload(raw: any): PredPayload | null {
  if (!raw) return null;
  const obj = typeof raw === "string" ? (() => { try { return JSON.parse(raw); } catch { return null; } })() : raw;
  if (!obj?.models) return null;
  return obj as PredPayload;
}

export function bundledPayload(): PredPayload | null {
  return parsePayload(bundled);
}

function applyModel(model: PredModel, feat: Record<string, number>, zeroOr = false): number {
  const x = { ...feat };
  if (zeroOr) { x.or_today = 0; x.or_chg = 0; x.has_or = 0; }
  let p = model.intercept;
  for (let i = 0; i < model.features.length; i++) {
    const std = model.std[i] < 1e-8 ? 1 : model.std[i];
    const z = (x[model.features[i]] - model.mean[i]) / std;
    p += z * model.coef[i];
  }
  return Math.max(FLOOR, Math.min(CEIL, p));
}

export function predictFromFigs(
  figs: Row[],
  today: Today,
  payload: PredPayload | null,
  juv: boolean,
): Pred | null {
  if (!payload?.models) return null;
  const useJuv = juv && (payload.models.juv_form || payload.models.juv);
  const figKey: "fig" | "fig2" = useJuv ? "fig2" : "fig";
  const formName = useJuv ? (payload.models.juv_form ? "juv_form" : "juv") : (payload.models.form ? "form" : "all");
  const block = payload.models[formName];
  if (!block?.model) return null;
  const hist = figsToHist(figs);
  const feat = featuresFromHist(hist, today, figKey);
  if (!feat) return null;
  const zeroOr = formName === "form" || formName === "juv_form";
  const pred = applyModel(block.model, feat, zeroOr);
  const band = block.model.band ?? 7;
  return {
    pred: Math.round(pred * 10) / 10,
    lo: Math.round(Math.max(FLOOR, pred - band) * 10) / 10,
    hi: Math.round(Math.min(CEIL, pred + band) * 10) / 10,
    best3: feat.best3_raw ?? null,
    last_fig: feat.last_raw ?? null,
    n_prior: feat.n_runs,
    scale: useJuv ? "2yo" : "all",
  };
}

export function storedPreds(raw: any, date: string): Map<number, Pred> {
  const out = new Map<number, Pred>();
  let rows: any[] = [];
  if (typeof raw === "string") {
    try { rows = JSON.parse(raw); } catch { return out; }
  } else if (Array.isArray(raw)) rows = raw;
  for (const r of rows) {
    if (!r || r.pred == null) continue;
    if (date && r.date && String(r.date).slice(0, 10) !== date) continue;
    out.set(Number(r.ride_id), {
      pred: Number(r.pred), lo: num(r.lo) ?? Number(r.pred), hi: num(r.hi) ?? Number(r.pred),
      best3: num(r.best3), last_fig: num(r.last_fig), n_prior: Number(r.n_prior ?? 0),
      scale: r.scale === "2yo" ? "2yo" : "all",
    });
  }
  return out;
}
