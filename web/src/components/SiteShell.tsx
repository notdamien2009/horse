import Link from "next/link";
import { Database, TriangleAlert } from "lucide-react";
import { cardDate, figMeta } from "@/lib/racing";
import { meetingTabs } from "@/lib/summary";
import { RaceTabs } from "./RaceTabs";
import { ThemeToggle } from "./ThemeToggle";

/** Sticky header (brand, date, figures, next-off countdown, meetings and race chips) + footer. Server component. */
export async function SiteShell({ activeId, children }: { activeId: number | null; children: React.ReactNode }) {
  const { date, isToday } = await cardDate();
  const meetings = await meetingTabs(date);
  const meta = await figMeta();
  const label = new Date(date + "T12:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  const status = (
    <>
      {meta?.version ? (
        <span className="figmeta" title={`Figure cache built ${meta.built ?? ""} · ${Number(meta.rows ?? 0).toLocaleString("en-GB")} runs · races to ${meta.max_date}`}>
          <Database size={13} aria-hidden /> <b>{meta.version}</b>
          <span className="hide-sm"> · {Number(meta.rows ?? 0).toLocaleString("en-GB")} runs · to {meta.max_date}</span>
        </span>
      ) : (
        <span className="nofigs"><TriangleAlert size={14} aria-hidden /> NO FIGURES LOADED – stop the site and run npm run dev again</span>
      )}
      <ThemeToggle />
    </>
  );
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <RaceTabs isToday={isToday} activeId={activeId} meetings={meetings} dateLabel={label} status={status}
        stale={!isToday && meetings.length > 0} />
      <main id="main">{children}</main>
      <footer>
        <span>FurlongIQ racecards · updated daily</span>
        <span>FIQ speed ratings · 9st Flat / 11st jumps base</span>
        <span className="legend">Ranked within each race <i aria-hidden /> <em>worst → best</em></span>
        <Link href="/how-we-rate" prefetch={false}>How we rate the horses</Link>
      </footer>
    </>
  );
}
