// Shared by server and client components.
// Colours are ranked inside each race: green = best, amber = middle, red = worst.
// Components get a *hue* (0 red .. 130 green) and the CSS turns it into the right shade for dark / light mode
// via the --h custom property (see .heat / .pill-h / .bar-h in globals.css).
import type { CSSProperties } from "react";

export type ColourFn = (v: number | null | undefined) => string | null;
export type HueFn = (v: number | null | undefined) => number | null;

const BEST = 130; // green

/** hue ranked within the race: best value = green, worst = red */
export function rankHue(values: (number | null | undefined)[]): HueFn {
  const sorted = [...new Set(values.filter((v): v is number => v != null))].sort((a, b) => b - a);
  return (v) => {
    if (v == null || !sorted.length) return null;
    const i = sorted.indexOf(v), n = sorted.length;
    if (i < 0) return null;
    const t = n === 1 ? 0 : i / (n - 1); // 0 best .. 1 worst
    return Math.round(BEST * (1 - t));
  };
}

/** hue for a single run's figure against the race's spread of ratings (lo = red, hi = green) */
export function scaleHue(lo: number, hi: number | null): HueFn {
  return (v) => {
    if (v == null || hi == null || !Number.isFinite(hi)) return null;
    let t = hi === lo ? 1 : (v - lo) / (hi - lo);
    t = Math.max(0, Math.min(1, t));
    return Math.round(BEST * t);
  };
}

/** inline style carrying the hue for the heat classes */
export const hueStyle = (h: number | null | undefined): CSSProperties | undefined =>
  h == null ? undefined : ({ ["--h" as string]: h } as CSSProperties);

// v1 helpers kept for compatibility
export function rankColours(values: (number | null | undefined)[]): ColourFn {
  const h = rankHue(values);
  return (v) => { const x = h(v); return x == null ? null : `hsl(${x},65%,50%)`; };
}
export function scaleColour(lo: number, hi: number | null): ColourFn {
  const h = scaleHue(lo, hi);
  return (v) => { const x = h(v); return x == null ? null : `hsl(${x},65%,52%)`; };
}

export const f0 = (v: number | null | undefined) => (v == null ? "" : String(Math.round(v)));
