import "server-only";

/** Server-side Supabase config. NEXT_PUBLIC_ variants are accepted so the same values can be set in Vercel. */
export function supabaseConfig(): { url: string; key: string } | null {
  const url = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const key = (process.env.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
  if (!url || !key) return null;
  return { url, key };
}

export function usingSupabase(): boolean {
  return supabaseConfig() != null;
}
