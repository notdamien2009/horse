"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clock, Crown, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MeetingTabs } from "@/lib/summary";
import { hueStyle } from "@/lib/colours";

const pad = (n: number) => String(n).padStart(2, "0");
const hhmm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

function countdown(time: string, now: Date) {
  const [h, m] = time.split(":").map(Number);
  const off = new Date(now); off.setHours(h, m, 0, 0);
  let s = Math.max(0, Math.round((off.getTime() - now.getTime()) / 1000));
  const hh = Math.floor(s / 3600); s -= hh * 3600;
  const mm = Math.floor(s / 60); s -= mm * 60;
  return hh ? `${hh}h ${pad(mm)}m` : `${mm}m ${pad(s)}s`;
}

export function RaceTabs({ meetings, activeId, isToday, dateLabel, status, stale }: {
  meetings: MeetingTabs[]; activeId: number | null; isToday: boolean; dateLabel: string;
  status: React.ReactNode; stale: boolean;
}) {
  // "now" is worked out in the browser, so races that have already run fade out and the countdown ticks
  const path = usePathname();
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const activeMtg = useMemo(
    () => meetings.find((m) => m.races.some((r) => r.race_id === activeId))?.meeting_id ?? meetings[0]?.meeting_id,
    [meetings, activeId],
  );
  const [shown, setShown] = useState<number | undefined>(activeMtg);
  useEffect(() => setShown(activeMtg), [activeMtg]);
  const mtg = meetings.find((m) => m.meeting_id === shown) ?? meetings[0];

  const nowT = now ? hhmm(now) : null;
  const next = useMemo(() => {
    if (!isToday || !nowT) return null;
    const all = meetings.flatMap((m) => m.races.map((r) => ({ ...r, course: m.course })));
    return all.filter((r) => r.time > nowT).sort((a, b) => a.time.localeCompare(b.time))[0] ?? null;
  }, [meetings, nowT, isToday]);

  // keep the active chip in view
  const rail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    rail.current?.querySelector<HTMLElement>(".rchip.on")?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [shown, activeId]);

  return (
    <header className="topbar">
      <div className="bar1">
        <Link href="/" className="brand" prefetch={false} aria-label="FurlongIQ – next race">
          <img src="/logo.png" alt="" className="logo-img" width={34} height={34} />
          <span className="brand-txt">
            <span className="wordmark">Furlong<span className="brand-iq">IQ</span></span>
            <small>{dateLabel}{stale ? " · latest cards" : ""}</small>
          </span>
        </Link>
        {meetings.length > 0 && (
          <nav className="mpills" aria-label="Meetings">
            {meetings.map((m) => {
              const left = isToday && nowT ? m.races.filter((r) => r.time >= nowT).length : m.races.length;
              return (
                <button key={m.meeting_id} type="button" aria-pressed={m.meeting_id === mtg?.meeting_id}
                  className={`mpill${m.meeting_id === mtg?.meeting_id ? " on" : ""}`} onClick={() => setShown(m.meeting_id)}
                  title={m.going ?? undefined}>
                  <b>{m.course}</b>
                  <span className="mpill-sub">{(m.going ?? "").replace(/\s*\(.*\)/, "")} · {left}/{m.races.length}</span>
                </button>
              );
            })}
          </nav>
        )}
        <div className="bar1-right">
          <Link href="/how-we-rate" prefetch={false}
            className={`how-link${path === "/how-we-rate" ? " on" : ""}`}>
            How we rate
          </Link>
          {next && now && (
            <Link href={`/race/${next.race_id}`} prefetch={false} className="nextoff" title={`Next off: ${next.time} ${next.course} – ${next.name}`}>
              <Clock size={14} aria-hidden />
              <span className="no-lbl">Next off</span>
              <b>{next.time} {next.course.length > 12 ? next.course.slice(0, 11) + "." : next.course}</b>
              <span className="cd" aria-live="off">{countdown(next.time, now)}</span>
            </Link>
          )}
          {status}
        </div>
      </div>
      {mtg && (
        <div className="bar2" ref={rail} role="navigation" aria-label={`${mtg.course} races`}>
          {mtg.races.map((r, i) => {
            const done = isToday && nowT != null && r.time < nowT;
            const isNext = next?.race_id === r.race_id;
            return (
              <Link key={r.race_id} href={`/race/${r.race_id}`} prefetch={false} title={r.name}
                aria-current={r.race_id === activeId ? "page" : undefined}
                className={`rchip${r.race_id === activeId ? " on" : ""}${done ? " done" : ""}${isNext ? " next" : ""}`}>
                <span className="rchip-row">
                  <span className="rchip-time">{r.time}</span>
                  <span className="rchip-n"><Users size={11} aria-hidden />{r.runners}</span>
                  {isNext ? <span className="rchip-tag">NEXT</span> : <span className="rchip-race">R{i + 1}</span>}
                </span>
                {r.top ? (
                  <span className="rchip-top" style={hueStyle(130)}>
                    <Crown size={11} aria-hidden />
                    <span className="rchip-horse">{r.top.horse}</span>
                    {r.top.fig != null && <b>{Math.round(r.top.fig)}</b>}
                  </span>
                ) : (
                  <span className="rchip-top none">no figures</span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </header>
  );
}
