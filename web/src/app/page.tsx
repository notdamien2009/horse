import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { Counters, EdgeCards, Explore, Hero, MovesOverview, Pricing } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: { absolute: "FurlongIQ · Racing market intelligence" },
  description: "Today's UK & Irish racing with FurlongIQ market moves, speed ratings and trainer records.",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <Hero />
        <Counters />
        <MovesOverview />
        <EdgeCards />
        <Explore />
        <Pricing />
      </div>
    </SiteShell>
  );
}
