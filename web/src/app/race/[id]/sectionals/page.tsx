import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { race } from "@/lib/racing";
import { SiteShell } from "@/components/SiteShell";
import { RaceSectionals } from "@/components/RaceSectionals";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const r = await race(Number((await params).id));
  return { title: r ? `Sectionals · ${r.time} ${r.course}` : "Race not found" };
}

export default async function RaceSectionalsPage({ params }: Props) {
  const id = Number((await params).id);
  const r = Number.isFinite(id) ? await race(id) : null;
  if (!r) notFound();
  return (
    <SiteShell activeId={id}>
      <RaceSectionals race={r} />
    </SiteShell>
  );
}
