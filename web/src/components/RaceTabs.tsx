"use client";
import Link from "next/link";
import { useEffect, useState } from "react";

type Tab = { race_id: number; time: string; name: string };
type Mtg = { meeting_id: number; course: string; going: string | null; races: Tab[] };

export function RaceTabs({ meetings, activeId, isToday }: { meetings: Mtg[]; activeId: number | null; isToday: boolean }) {
  // "now" is worked out in the browser, so races that have already run fade out as the day goes on
  const [now, setNow] = useState<string | null>(null);
  useEffect(() => {
    const tick = () => setNow(new Date().toTimeString().slice(0, 5));
    tick();
    const t = setInterval(tick, 60_000);
    return () => clearInterval(t);
  }, []);
  return (
    <nav id="tabs">
      {meetings.map((m) => (
        <div className="mtg" key={m.meeting_id}>
          <div className="mname">{m.course}<small>{m.going ?? ""}</small></div>
          {m.races.map((r) => {
            const done = isToday && now != null && r.time < now;
            return (
              <Link key={r.race_id} href={`/race/${r.race_id}`} title={r.name} prefetch={false}
                className={`tab${r.race_id === activeId ? " on" : ""}${done ? " done" : ""}`}>
                {r.time}<small>{m.course.length > 9 ? m.course.slice(0, 7) + "." : m.course}</small>
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
