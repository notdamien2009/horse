import "server-only";

/** Server-side Supabase config. NEXT_PUBLIC_ variants are accepted so the same values can be set in Vercel. */
export function supabaseConfig(): { url: string; key: string } | null {
  const url = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || "").trim();
  const key = (process.env.SUPABASE_ANON_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
  if (!url || !key) return null;
  return { url, key };
}

/**
 * The live Vercel site reads Supabase. On this PC we always read the local SQLite
 * files, even if .env has SUPABASE_URL set for UPLOAD_TO_SUPABASE.bat.
 * Set FURLONGIQ_USE_SUPABASE=1 only if you really want the local site to use Supabase.
 */
export function usingSupabase(): boolean {
  if (!supabaseConfig()) return false;
  if (process.env.VERCEL) return true;
  return process.env.FURLONGIQ_USE_SUPABASE === "1";
}
