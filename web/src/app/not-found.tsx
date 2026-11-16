import Link from "next/link";
import { SiteShell } from "@/components/SiteShell";

export default function NotFound() {
  return (
    <SiteShell activeId={null}>
      <div className="empty">
        That race isn&apos;t on today&apos;s cards. <Link href="/">Go to the next race</Link>.
      </div>
    </SiteShell>
  );
}
