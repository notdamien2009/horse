import { redirect } from "next/navigation";
import { cardDate, nextRaceId } from "@/lib/racing";
import { SiteShell } from "@/components/SiteShell";

export const dynamic = "force-dynamic";

// Home: jump straight to the next race to run today.
export default function Home() {
  const { date, isToday } = cardDate();
  const id = nextRaceId(date, isToday);
  if (id != null) redirect(`/race/${id}`);
  return (
    <SiteShell activeId={null}>
      <div className="empty">
        No cards yet. Double-click <b>GET_TODAYS_CARDS.bat</b> (or run <code>npm run cards</code>), then refresh this page.
      </div>
    </SiteShell>
  );
}
