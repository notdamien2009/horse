import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { MoversGrid, MovesOverview, PageHead } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Movers grid",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Movers grid" title="Who's been backed. Who's drifting." lead="The biggest moves of the day, measured in points of win chance, with history to say how rare they are." />
        <MoversGrid />
        <MovesOverview />
      </div>
    </SiteShell>
  );
}
