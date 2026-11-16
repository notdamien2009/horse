/** Convert a fractional (or already-decimal) odds string to a 2dp decimal, e.g. 5/2 → 3.50, evens → 2.00. */
export function toDecimalOdds(raw: string | null | undefined): string {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s || s === "-" || s === "–") return s;
  const head = s.toLowerCase().replace(/[,]/g, "").trim();
  if (/^(evens?|evs|even money)\b/.test(head)) return "2.00";
  const dec = head.match(/^(\d+(?:\.\d+)?)\s*(?:d(?:ec)?)?$/i);
  if (dec) {
    const n = Number(dec[1]);
    return Number.isFinite(n) ? n.toFixed(2) : s;
  }
  const frac = s.match(/(\d+)\s*\/\s*(\d+)/);
  if (frac) {
    const a = Number(frac[1]), b = Number(frac[2]);
    if (b > 0 && Number.isFinite(a)) return (1 + a / b).toFixed(2);
  }
  return s;
}
