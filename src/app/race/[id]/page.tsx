import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { race } from "@/lib/racing";
import { SiteShell } from "@/components/SiteShell";
import { RaceCard } from "@/components/RaceCard";
import { RaceIntelligence } from "@/components/RaceIntelligence";

export const revalidate = 300;

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const r = await race(Number((await params).id));
  return { title: r ? `${r.time} ${r.course}` : "Race not found" };
}

export default async function RacePage({ params }: Props) {
  const id = Number((await params).id);
  const r = Number.isFinite(id) ? await race(id) : null;
  if (!r) notFound();
  return (
    <SiteShell activeId={id}>
      <RaceIntelligence race={r} />
      <div id="full-racecard">
        <RaceCard race={r} />
      </div>
    </SiteShell>
  );
}
