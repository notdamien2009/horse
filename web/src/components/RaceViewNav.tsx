"use client";
import Link from "next/link";
import { LayoutList, Timer } from "lucide-react";

export function RaceViewNav({ raceId, view }: { raceId: number; view: "card" | "sectionals" }) {
  return (
    <div className="seg" role="navigation" aria-label="Race views">
      <Link href={`/race/${raceId}`} prefetch={false} className={view === "card" ? "on" : undefined}>
        <LayoutList size={14} aria-hidden /> Race card
      </Link>
      <Link href={`/race/${raceId}/sectionals`} prefetch={false} className={view === "sectionals" ? "on" : undefined}>
        <Timer size={14} aria-hidden /> Sectionals
      </Link>
    </div>
  );
}
