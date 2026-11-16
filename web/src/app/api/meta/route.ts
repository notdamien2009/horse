import { NextResponse } from "next/server";
import { datesAvailable, figMeta, localDate } from "@/lib/racing";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ today: localDate(), dates: await datesAvailable(), figs: (await figMeta()) ?? {} });
}
