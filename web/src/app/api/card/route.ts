import { NextResponse, type NextRequest } from "next/server";
import { card, cardDate } from "@/lib/racing";

export const revalidate = 300;

export async function GET(req: NextRequest) {
  const date = req.nextUrl.searchParams.get("date") ?? (await cardDate()).date;
  return NextResponse.json(await card(date));
}
