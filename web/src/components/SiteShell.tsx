import { cardDate, card, figMeta } from "@/lib/racing";
import { RaceTabs } from "./RaceTabs";
import { ThemeToggle } from "./ThemeToggle";

/** Header + one tab per race today (grouped by meeting) + footer. Server component: reads the SQLite files. */
export function SiteShell({ activeId, children }: { activeId: number | null; children: React.ReactNode }) {
  const { date, isToday } = cardDate();
  const meetings = card(date);
  const meta = figMeta();
  const label = new Date(date + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return (
    <>
      <header className="top">
        <div className="brand">Speeds <span>Today&apos;s Racing</span></div>
        <div className="hdr-right">
          <span>{label}{!isToday && meetings.length ? " (latest cards - run GET_TODAYS_CARDS.bat for today)" : ""}</span>
          {meta?.version ? (
            <span className="muted" title={`Figure cache built ${meta.built ?? ""}`}>
              Figures: <b>{meta.version}</b> · {Number(meta.rows ?? 0).toLocaleString("en-GB")} runs · to {meta.max_date}
            </span>
          ) : (
            <span className="nofigs">NO FIGURES LOADED - stop the site and run npm run dev again to build them</span>
          )}
          <ThemeToggle />
        </div>
      </header>
      {meetings.length > 0 && (
        <RaceTabs
          isToday={isToday}
          activeId={activeId}
          meetings={meetings.map((m) => ({
            meeting_id: m.meeting_id, course: m.course, going: m.going,
            races: m.races.map((r) => ({ race_id: r.race_id, time: r.time, name: r.name })),
          }))}
        />
      )}
      <main id="main">{children}</main>
      <footer className="muted">
        Cards: Sporting Life (run GET_TODAYS_CARDS.bat to refresh). Figures: our speed figures, 9st Flat / 11st jumps base.
        Colours are ranked within each race: green = best, red = worst.
      </footer>
    </>
  );
}
