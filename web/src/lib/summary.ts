import "server-only";
import { cache } from "react";
import { unstable_cache } from "next/cache";
import { CARD_REVALIDATE, CARD_TAG } from "./data-cache";
import { card, racesOn, type Meeting, type Race } from "./racing";

// One small summary per race for the race tabs: runner count and the top-rated horse.
// Uses the same cached racesOn() data as the race card. Fresh for 5 minutes (tag: card).
export type RaceChip = {
  race_id: number; time: string; name: string; runners: number;
  top: { horse: string; fig: number | null; gap: number | null } | null;
};
export type MeetingTabs = { meeting_id: number; course: string; going: string | null; races: RaceChip[] };

function chipFrom(full: Race | undefined, fallback: Meeting["races"][number]): RaceChip {
  let out: RaceChip = { race_id: fallback.race_id, time: fallback.time, name: fallback.name, runners: Number(fallback.ride_count) || 0, top: null };
  if (!full) return out;
  const val = (h: Race["runners"][number]) => h.pred;
  const ranked = full.runners.filter((h) => h.rank != null).sort((a, b) => a.rank! - b.rank!);
  const a = ranked[0], b = ranked[1];
  return {
    ...out,
    runners: full.active,
    top: a ? { horse: a.horse, fig: val(a), gap: b && val(a) != null && val(b) != null ? Math.round(val(a)! - val(b)!) : null } : null,
  };
}

async function meetingTabsFresh(date: string): Promise<MeetingTabs[]> {
  const meetings = await card(date);
  let loaded: Race[] = [];
  try { loaded = await racesOn(date); } catch { /* the tab still works without the summary */ }
  const byId = new Map(loaded.map((r) => [r.race_id, r]));
  return meetings.map((m) => ({
    meeting_id: m.meeting_id, course: m.course, going: m.going,
    races: m.races.map((r) => chipFrom(byId.get(r.race_id), r)),
  }));
}

const meetingTabsCached = unstable_cache(meetingTabsFresh, ["meeting-tabs"], { revalidate: CARD_REVALIDATE, tags: [CARD_TAG] });
export const meetingTabs = cache((date: string) => meetingTabsCached(date));
