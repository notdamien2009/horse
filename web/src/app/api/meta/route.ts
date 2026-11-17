import { NextResponse } from "next/server";
import { datesAvailable, figMeta, localDate } from "@/lib/racing";

export const revalidate = 300;

export async function GET() {
  return NextResponse.json({ today: localDate(), dates: await datesAvailable(), figs: (await figMeta()) ?? {} });
}
