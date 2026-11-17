import { redirect } from "next/navigation";
import { cardDate, nextRaceId } from "@/lib/racing";
import { SiteShell } from "@/components/SiteShell";

export const revalidate = 300;

// Home: jump straight to the next race to run today.
export default async function Home() {
  const { date, isToday } = await cardDate();
  const id = await nextRaceId(date, isToday);
  if (id != null) redirect(`/race/${id}`);
  return (
    <SiteShell activeId={null}>
      <div className="empty">
        No cards yet. Double-click <b>GET_TODAYS_CARDS.bat</b> (or run <code>npm run cards</code>), then refresh this page.
      </div>
    </SiteShell>
  );
}
