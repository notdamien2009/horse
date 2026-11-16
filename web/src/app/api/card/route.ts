import { NextResponse, type NextRequest } from "next/server";
import { card, cardDate } from "@/lib/racing";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date") ?? (await cardDate()).date;
  return NextResponse.json(await card(date));
}
