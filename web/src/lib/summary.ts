import "server-only";
import { cacheVersion, card, racesOn, type Meeting, type Race } from "./racing";

// One small summary per race for the race tabs: runner count and the top-rated horse.
// Uses the same race() data as the race card. Cached until the cards or figures change.
export type RaceChip = {
  race_id: number; time: string; name: string; runners: number;
  top: { horse: string; fig: number | null; gap: number | null } | null;
};
export type MeetingTabs = { meeting_id: number; course: string; going: string | null; races: RaceChip[] };

const memo = new Map<string, MeetingTabs[]>();

function chipFrom(full: Race | undefined, fallback: Meeting["races"][number]): RaceChip {
  let out: RaceChip = { race_id: fallback.race_id, time: fallback.time, name: fallback.name, runners: Number(fallback.ride_count) || 0, top: null };
  if (!full) return out;
  const juv = full.rank_basis.startsWith("2yo");
  const val = (h: Race["runners"][number]) => (juv ? h.ratings.best3_2yo : h.ratings.best3 ?? h.ratings.best);
  const ranked = full.runners.filter((h) => h.rank != null).sort((a, b) => a.rank! - b.rank!);
  const a = ranked[0], b = ranked[1];
  return {
    ...out,
    runners: full.active,
    top: a ? { horse: a.horse, fig: val(a), gap: b && val(a) != null && val(b) != null ? Math.round(val(a)! - val(b)!) : null } : null,
  };
}

export async function meetingTabs(date: string): Promise<MeetingTabs[]> {
  const version = `${date}:${await cacheVersion()}`;
  const hit = memo.get(version);
  if (hit) return hit;
  if (memo.size > 20) memo.clear();
  const meetings = await card(date);
  let loaded: Race[] = [];
  try { loaded = await racesOn(date); } catch { /* the tab still works without the summary */ }
  const byId = new Map(loaded.map((r) => [r.race_id, r]));
  const out = meetings.map((m) => ({
    meeting_id: m.meeting_id, course: m.course, going: m.going,
    races: m.races.map((r) => chipFrom(byId.get(r.race_id), r)),
  }));
  memo.set(version, out);
  return out;
}
