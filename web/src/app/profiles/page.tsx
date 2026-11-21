import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { EdgeCards, HorseTable, PageHead, TrainerTable } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Horse & trainer profiles",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Profiles" title="Horse & trainer profiles." lead="See how each yard and horse performs when the money arrives — and when it leaves." />
        <EdgeCards />
        <TrainerTable />
        <HorseTable />
      </div>
    </SiteShell>
  );
}
