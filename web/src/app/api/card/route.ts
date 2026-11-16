import { NextResponse, type NextRequest } from "next/server";
import { card, cardDate } from "@/lib/racing";

export const dynamic = "force-dynamic";

export function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date") ?? cardDate().date;
  return NextResponse.json(card(date));
}
