import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { supabaseConfig } from "./env";
import type { Row } from "./row";
import { normRow } from "./row";

const PAGE = 1000;

let client: SupabaseClient | null = null;

function sb(): SupabaseClient {
  const cfg = supabaseConfig();
  if (!cfg) throw new Error("Supabase is not configured");
  if (!client) {
    client = createClient(cfg.url, cfg.key, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return client;
}

async function pages<T extends Row>(
  run: (from: number, to: number) => PromiseLike<{ data: T[] | null; error: { message: string } | null }>,
): Promise<T[]> {
  const out: T[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await run(from, from + PAGE - 1);
    if (error) throw new Error(`Supabase: ${error.message}`);
    if (!data?.length) break;
    out.push(...data);
    if (data.length < PAGE) break;
  }
  return out;
}

function chunks<T>(xs: T[], n = 200): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
  return out;
}

export async function qHasCards(): Promise<boolean> {
  const { count, error } = await sb().from("races").select("race_id", { head: true, count: "exact" });
  if (error) throw new Error(`Supabase: ${error.message}`);
  return (count ?? 0) > 0;
}

export async function qHasFigs(): Promise<boolean> {
  const { count, error } = await sb().from("figs").select("horse_norm", { head: true, count: "exact" });
  if (error) throw new Error(`Supabase: ${error.message}`);
  return (count ?? 0) > 0;
}

export async function qFigMeta(): Promise<Row[]> {
  const { data, error } = await sb().from("fig_meta").select("k, v");
  if (error) throw new Error(`Supabase: ${error.message}`);
  return data ?? [];
}

export async function qCardDates(): Promise<string[]> {
  const rows = await pages((from, to) =>
    sb().from("races").select("date").order("date", { ascending: false }).range(from, to),
  );
  return [...new Set(rows.map((r) => String(r.date).slice(0, 10)))];
}

export async function qMeetings(date: string): Promise<Row[]> {
  const { data, error } = await sb().from("meetings").select("*").eq("date", date).order("course");
  if (error) throw new Error(`Supabase: ${error.message}`);
  return (data ?? []).map((r) => normRow(r));
}

export async function qRacesByDate(date: string): Promise<Row[]> {
  const { data, error } = await sb()
    .from("races")
    .select("race_id,meeting_id,time,course,name,race_class,distance,going,ride_count,stage")
    .eq("date", date)
    .order("time");
  if (error) throw new Error(`Supabase: ${error.message}`);
  return (data ?? []).map((r) => normRow(r));
}

export async function qRace(id: number): Promise<Row | null> {
  const { data, error } = await sb().from("races").select("*").eq("race_id", id).maybeSingle();
  if (error) throw new Error(`Supabase: ${error.message}`);
  return data ? normRow(data) : null;
}

export async function qRunners(raceId: number): Promise<Row[]> {
  const rows = await pages((from, to) =>
    sb().from("runners").select("*").eq("race_id", raceId).order("cloth").range(from, to),
  );
  return rows.map((r) => normRow(r));
}

export async function qPrevRuns(rideIds: number[]): Promise<Row[]> {
  if (!rideIds.length) return [];
  const out: Row[] = [];
  for (const part of chunks(rideIds)) {
    const rows = await pages((from, to) =>
      sb().from("prev_runs").select("*").in("ride_id", part).order("n").range(from, to),
    );
    out.push(...rows.map((r) => normRow(r)));
  }
  out.sort((a, b) => a.ride_id - b.ride_id || a.n - b.n);
  return out;
}

export async function qFigs(norms: string[], before: string): Promise<Row[]> {
  if (!norms.length) return [];
  const out: Row[] = [];
  for (const part of chunks(norms)) {
    const rows = await pages((from, to) =>
      sb()
        .from("figs")
        .select("horse_norm,race_id,date,foal_year,course,code,surface,dist,dist_f,going,cls,pos,beaten,ran,offr,fig,fig2")
        .in("horse_norm", part)
        .lt("date", before)
        .order("date", { ascending: false })
        .range(from, to),
    );
    out.push(...rows.map((r) => normRow(r)));
  }
  out.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  return out;
}

export async function qRacesFullByDate(date: string): Promise<Row[]> {
  const rows = await pages((from, to) =>
    sb().from("races").select("*").eq("date", date).order("time").range(from, to),
  );
  return rows.map((r) => normRow(r));
}

export async function qRunnersByDate(date: string): Promise<Row[]> {
  const rows = await pages((from, to) =>
    sb().from("runners").select("*").eq("date", date).order("cloth").range(from, to),
  );
  return rows.map((r) => normRow(r));
}


export async function qPredToday(date: string): Promise<Row[]> {
  try {
    const rows = await pages((from, to) =>
      sb().from("pred_today").select("*").eq("date", date).range(from, to),
    );
    return rows.map((r) => normRow(r));
  } catch {
    return [];
  }
}

export async function qPace(dates: string[]): Promise<Row[]> {
  const uniq = [...new Set(dates.filter(Boolean))];
  if (!uniq.length) return [];
  try {
    const out: Row[] = [];
    for (const part of chunks(uniq, 150)) {
      const rows = await pages((from, to) =>
        sb()
          .from("pace")
          .select("date,course_norm,course,off_hhmm,dist_f,code,label,fig_rel,reason,source,fsp,field_def,n_field,horses")
          .in("date", part)
          .range(from, to),
      );
      out.push(...rows.map((r) => normRow(r)));
    }
    return out;
  } catch {
    return [];
  }
}

export async function cacheVersion(): Promise<string> {
  const meta = await qFigMeta();
  const map = Object.fromEntries(meta.map((r) => [r.k, r.v]));
  const { data, error } = await sb().from("scrape_log").select("date, ts").order("ts", { ascending: false }).limit(1);
  if (error) throw new Error(`Supabase: ${error.message}`);
  const log = data?.[0];
  return `sb:${map.built ?? ""}:${map.rows ?? ""}:${log?.ts ?? log?.date ?? ""}`;
}
