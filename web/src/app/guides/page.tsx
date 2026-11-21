import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { Faq, HowTo, PageHead, Tutorials } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Guides",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Guides" title="Get more from FurlongIQ." lead="How to use the site, what every number means, and short video guides." />
        <HowTo />
        <Faq />
        <Tutorials />
      </div>
    </SiteShell>
  );
}
