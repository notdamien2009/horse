// Shared by server and client components.
export type ColourFn = (v: number | null | undefined) => string | null;

/** green (best) -> red (worst), ranked inside the race */
export function rankColours(values: (number | null | undefined)[]): ColourFn {
  const sorted = [...new Set(values.filter((v): v is number => v != null))].sort((a, b) => b - a);
  return (v) => {
    if (v == null || !sorted.length) return null;
    const i = sorted.indexOf(v), n = sorted.length;
    const t = n === 1 ? 0 : i / (n - 1); // 0 best .. 1 worst
    return `hsl(${Math.round(125 * (1 - t))},${60 + 20 * Math.abs(t - 0.5)}%,${50 + 5 * (1 - Math.abs(t - 0.5) * 2)}%)`;
  };
}

/** colour a single run's figure against the race's spread of ratings */
export function scaleColour(lo: number, hi: number | null): ColourFn {
  return (v) => {
    if (v == null || hi == null || !Number.isFinite(hi)) return null;
    let t = hi === lo ? 1 : (v - lo) / (hi - lo);
    t = Math.max(0, Math.min(1, t));
    return `hsl(${Math.round(125 * t)},65%,52%)`;
  };
}

export const f0 = (v: number | null | undefined) => (v == null ? "" : String(Math.round(v)));
