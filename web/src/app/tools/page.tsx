import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";
import { PageHead, Tools } from "@/components/Market";

export const revalidate = 300;
export const metadata: Metadata = {
  title: "Tools",
};

export default function Page() {
  return (
    <SiteShell activeId={null}>
      <div className="mk">
        <PageHead eyebrow="Tools & value" title="Price it yourself." lead="Work out returns after commission and compare our fair odds with the market." />
        <Tools />
      </div>
    </SiteShell>
  );
}
