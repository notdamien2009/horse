import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";
import { CARD_TAG } from "@/lib/data-cache";

export const dynamic = "force-dynamic";

function authorized(req: NextRequest): boolean {
  const secret = (process.env.REVALIDATE_SECRET || process.env.FURLONGIQ_REVALIDATE_SECRET || "").trim();
  if (!secret) return false;
  const header = (req.headers.get("x-revalidate-secret") || req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  const query = req.nextUrl.searchParams.get("secret") || "";
  return header === secret || query === secret;
}

/** Optional: POST or GET with the REVALIDATE_SECRET so a daily upload can drop the 5-minute page cache early. */
export async function POST(req: NextRequest) {
  const secret = (process.env.REVALIDATE_SECRET || process.env.FURLONGIQ_REVALIDATE_SECRET || "").trim();
  if (!secret) return NextResponse.json({ ok: false, error: "REVALIDATE_SECRET is not set" }, { status: 501 });
  if (!authorized(req)) return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  revalidateTag(CARD_TAG, { expire: 0 });
  revalidatePath("/", "layout");
  return NextResponse.json({ ok: true, revalidated: CARD_TAG });
}

export async function GET(req: NextRequest) {
  return POST(req);
}
