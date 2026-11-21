import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { LiveMarket, PageHead, Workspace } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Live market",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Live market" title="Today's market, read properly." lead="Prices, moves and how unusual each one is, with the FurlongIQ record behind every runner." />
        <LiveMarket />
        <Workspace />
      </div>
    </SiteShell>
  );
}
