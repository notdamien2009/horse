import { NextResponse } from "next/server";
import { datesAvailable, figMeta, localDate } from "@/lib/racing";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ today: localDate(), dates: datesAvailable(), figs: figMeta() ?? {} });
}
