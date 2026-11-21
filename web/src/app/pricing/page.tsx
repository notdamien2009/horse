import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { Faq, PageHead, Pricing } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Pricing",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Pricing" title="Full access. One simple price." lead="Everything FurlongIQ does, at one fair monthly price." />
        <Pricing />
        <Faq />
      </div>
    </SiteShell>
  );
}
