import { NextResponse } from "next/server";
import { race } from "@/lib/racing";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const r = race(Number((await params).id));
  return NextResponse.json(r, { status: r ? 200 : 404 });
}
