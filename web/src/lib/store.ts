import "server-only";
import { usingSupabase } from "./env";
import type { Row } from "./row";

export type { Row };
export { usingSupabase };

type Store = typeof import("./supabase-store");

async function store(): Promise<Store> {
  if (usingSupabase()) return import("./supabase-store");
  if (process.env.VERCEL) {
    throw new Error("SQLite is not available on Vercel. Set SUPABASE_URL and SUPABASE_ANON_KEY.");
  }
  return import("./sqlite-store");
}

export async function qHasCards(): Promise<boolean> { return (await store()).qHasCards(); }
export async function qHasFigs(): Promise<boolean> { return (await store()).qHasFigs(); }
export async function qFigMeta(): Promise<Row[]> { return (await store()).qFigMeta(); }
export async function qCardDates(): Promise<string[]> { return (await store()).qCardDates(); }
export async function qMeetings(date: string): Promise<Row[]> { return (await store()).qMeetings(date); }
export async function qRacesByDate(date: string): Promise<Row[]> { return (await store()).qRacesByDate(date); }
export async function qRace(id: number): Promise<Row | null> { return (await store()).qRace(id); }
export async function qRunners(raceId: number): Promise<Row[]> { return (await store()).qRunners(raceId); }
export async function qPrevRuns(rideIds: number[]): Promise<Row[]> { return (await store()).qPrevRuns(rideIds); }
export async function qFigs(norms: string[], before: string): Promise<Row[]> { return (await store()).qFigs(norms, before); }
export async function qRacesFullByDate(date: string): Promise<Row[]> { return (await store()).qRacesFullByDate(date); }
export async function qRunnersByDate(date: string): Promise<Row[]> { return (await store()).qRunnersByDate(date); }
export async function qPredToday(date: string): Promise<Row[]> { return (await store()).qPredToday(date); }
export async function qPace(dates: string[]): Promise<Row[]> { return (await store()).qPace(dates); }
export async function qSectionals(norms: string[]): Promise<Row[]> { return (await store()).qSectionals(norms); }
export async function qWinPct(date: string): Promise<Row[]> { return (await store()).qWinPct(date); }
export async function cacheVersion(): Promise<string> { return (await store()).cacheVersion(); }
