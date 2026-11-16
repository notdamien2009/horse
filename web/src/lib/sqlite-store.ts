import "server-only";
import fs from "node:fs";
import path from "node:path";
import type { Row } from "./row";
import { normRow } from "./row";

function findRoot(): string {
  const cands = [process.env.SPEEDS_ROOT, process.cwd(), path.resolve(process.cwd(), "..")].filter(Boolean) as string[];
  for (const d of cands) {
    if (fs.existsSync(path.join(d, "data")) || fs.existsSync(path.join(d, "tools", "sl_cards.py"))) return d;
  }
  return process.cwd();
}

export const ROOT = findRoot();
export const CARDS = path.join(ROOT, "data", "cards.sqlite");
export const CACHE = path.join(ROOT, "data", "site_cache.sqlite");

async function q(file: string, sql: string, args: (string | number | null)[] = []): Promise<Row[]> {
  if (!fs.existsSync(file)) return [];
  const { DatabaseSync } = await import("node:sqlite");
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare(sql).all(...args).map((r) => ({ ...(r as Row) }));
  } finally {
    db.close();
  }
}

async function hasTable(file: string, name: string): Promise<boolean> {
  return (await q(file, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name])).length > 0;
}

function placeholders(n: number): string {
  return Array.from({ length: n }, () => "?").join(",");
}

export async function qHasCards(): Promise<boolean> {
  return await hasTable(CARDS, "races");
}

export async function qHasFigs(): Promise<boolean> {
  return await hasTable(CACHE, "figs");
}

export async function qFigMeta(): Promise<Row[]> {
  if (!(await hasTable(CACHE, "meta"))) return [];
  return await q(CACHE, "SELECT k, v FROM meta");
}

export async function qCardDates(): Promise<string[]> {
  if (!(await hasTable(CARDS, "races"))) return [];
  return (await q(CARDS, "SELECT DISTINCT date FROM races ORDER BY date DESC")).map((r) => String(r.date));
}

export async function qMeetings(date: string): Promise<Row[]> {
  if (!(await hasTable(CARDS, "meetings"))) return [];
  return await q(CARDS, "SELECT * FROM meetings WHERE date=? ORDER BY course", [date]);
}

export async function qRacesByDate(date: string): Promise<Row[]> {
  if (!(await hasTable(CARDS, "races"))) return [];
  return await q(CARDS, "SELECT race_id,meeting_id,time,course,name,race_class,distance,going,ride_count,stage FROM races WHERE date=? ORDER BY time", [date]);
}

export async function qRace(id: number): Promise<Row | null> {
  if (!(await hasTable(CARDS, "races"))) return null;
  return (await q(CARDS, "SELECT * FROM races WHERE race_id=?", [id]))[0] ?? null;
}

export async function qRunners(raceId: number): Promise<Row[]> {
  if (!(await hasTable(CARDS, "runners"))) return [];
  return await q(CARDS, "SELECT * FROM runners WHERE race_id=? ORDER BY cloth", [raceId]);
}

export async function qPrevRuns(rideIds: number[]): Promise<Row[]> {
  if (!rideIds.length || !(await hasTable(CARDS, "prev_runs"))) return [];
  return await q(CARDS, `SELECT * FROM prev_runs WHERE ride_id IN (${placeholders(rideIds.length)}) ORDER BY ride_id, n`, rideIds);
}

export async function qFigs(norms: string[], before: string): Promise<Row[]> {
  if (!norms.length || !(await hasTable(CACHE, "figs"))) return [];
  return (await q(
    CACHE,
    `SELECT horse_norm, race_id, date, foal_year, course, code, surface, dist, dist_f, going, cls, pos, beaten, ran, offr, fig, fig2
     FROM figs WHERE horse_norm IN (${placeholders(norms.length)}) AND date<? ORDER BY date DESC`,
    [...norms, before],
  )).map((r) => normRow(r));
}

export async function qRacesFullByDate(date: string): Promise<Row[]> {
  if (!(await hasTable(CARDS, "races"))) return [];
  return await q(CARDS, "SELECT * FROM races WHERE date=? ORDER BY time", [date]);
}

export async function qRunnersByDate(date: string): Promise<Row[]> {
  if (!(await hasTable(CARDS, "runners"))) return [];
  return await q(CARDS, "SELECT * FROM runners WHERE date=? ORDER BY race_id, cloth", [date]);
}

export async function cacheVersion(): Promise<string> {
  const stamp = (f: string) => { try { return String(fs.statSync(f).mtimeMs); } catch { return "0"; } };
  return `${stamp(CARDS)}:${stamp(CACHE)}`;
}
