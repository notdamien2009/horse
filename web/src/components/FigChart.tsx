"use client";
// Speed-figure trend chart for a runner (pure SVG, no chart library).
// Oldest run on the left, newest on the right, always laid out on the same 8 slots so charts line up down the card.
import { useId, useMemo, useState } from "react";
import type { FormRun, Conditions } from "@/lib/racing";
import { f0, hueStyle, type HueFn } from "@/lib/colours";

export const SLOTS = 8;
const JUMPS = ["Hurdle", "Chase", "NHF"];
const isJ = (code: string) => JUMPS.includes(code);

export type Trend = { dir: "up" | "down" | "flat"; slope: number; n: number; idx: number[]; a: number; b: number; scope: string } | null;
export type ChartRun = FormRun & { v: number | null };

/** value plotted for a run: 2yo-scale figure in 2yo races, the normal figure otherwise */
export const runVal = (f: FormRun, juv: boolean) => (juv ? f.fig2 : f.fig);

/** oldest -> newest */
export function chartRuns(runs: FormRun[], juv: boolean): ChartRun[] {
  return [...runs].slice(0, SLOTS).reverse().map((f) => ({ ...f, v: runVal(f, juv) }));
}

/** Least-squares slope (lb per run) over the last 3-6 runs with a figure, same discipline as today's race when possible. */
export function trendOf(pts: ChartRun[], today: Conditions): Trend {
  const figd = pts.map((p, i) => ({ p, i })).filter((o) => o.p.v != null);
  const same = figd.filter((o) => isJ(o.p.code) === isJ(today.code));
  const pick = same.length >= 3 ? same : figd;
  const use = pick.slice(-6);
  if (use.length < 3) return null;
  const xs = use.map((o) => o.i), ys = use.map((o) => o.p.v as number);
  const mx = xs.reduce((a, b) => a + b, 0) / xs.length, my = ys.reduce((a, b) => a + b, 0) / ys.length;
  let num = 0, den = 0;
  xs.forEach((x, k) => { num += (x - mx) * (ys[k] - my); den += (x - mx) ** 2; });
  const b = den ? num / den : 0;
  const dir = b >= 1.5 ? "up" : b <= -1.5 ? "down" : "flat";
  const scope = pick === same ? (isJ(today.code) ? "jumps runs" : "Flat/AW runs") : "runs";
  return { dir, slope: b, n: use.length, idx: xs, a: my - b * mx, b, scope };
}

export function TrendBadge({ t }: { t: Trend }) {
  if (!t) return <span className="trend na" title="Needs at least 3 runs with a figure">Trend –</span>;
  const s = Math.abs(t.slope).toFixed(1);
  const lbl = t.dir === "up" ? `▲ Rising +${s}/run` : t.dir === "down" ? `▼ Falling −${s}/run` : "▶ Steady";
  return (
    <span className={`trend ${t.dir}`}
      title={`Trend line through the last ${t.n} ${t.scope} with a figure: ${t.slope >= 0 ? "+" : "−"}${s} lb per run`}>
      {lbl}
    </span>
  );
}

const fmtD = (d: string, yr = true) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", yr ? { day: "numeric", month: "short", year: "2-digit" } : { day: "numeric", month: "short" });
const posCls = (p: string) => (p === "1" ? "p-win" : p === "2" || p === "3" ? "p-place" : /^[A-Z]/i.test(p) ? "p-bad" : "p-out");
const goingTxt = (g: string | null) => String(g ?? "").replace(/\s*\(.*\)/, "");

const DIMS = {
  sm: { W: 380, H: 112, L: 8, R: 40, T: 14, B: 18, r: 4.4 },
  lg: { W: 960, H: 250, L: 40, R: 64, T: 20, B: 46, r: 6 },
};

export function FigChart({ runs, juv, lo, hi, hue, refV, refLabel, today, size = "sm", trend }: {
  runs: FormRun[]; juv: boolean; lo: number; hi: number; hue: HueFn; refV: number | null; refLabel: string;
  today: Conditions; size?: "sm" | "lg"; trend?: Trend;
}) {
  const uid = useId().replace(/:/g, "");
  const [hov, setHov] = useState<number | null>(null);
  const pts = useMemo(() => chartRuns(runs, juv), [runs, juv]);
  const t = trend === undefined ? trendOf(pts, today) : trend;
  const D = DIMS[size];
  const { W, H, L, R, T, B } = D;
  const pw = W - L - R, ph = H - T - B, base = T + ph;
  const off = SLOTS - pts.length; // newest run always in the right-hand slot
  const x = (i: number) => L + ((off + i) * pw) / (SLOTS - 1);
  const y = (v: number) => T + ph - ((Math.max(lo, Math.min(hi, v)) - lo) / Math.max(1, hi - lo)) * ph;
  const vals = pts.filter((p) => p.v != null);

  if (!pts.length) return <div className={`figchart-empty ${size}`}>No previous runs</div>;

  // line: solid between consecutive runs, dashed where it skips over runs with no figure
  const segs: { d: string; dash: boolean }[] = [];
  let prev = -1;
  pts.forEach((p, i) => {
    if (p.v == null) return;
    if (prev >= 0) segs.push({ d: `M${x(prev).toFixed(1)},${y(pts[prev].v!).toFixed(1)}L${x(i).toFixed(1)},${y(p.v).toFixed(1)}`, dash: i - prev > 1 });
    prev = i;
  });
  const figI = pts.map((p, i) => (p.v == null ? -1 : i)).filter((i) => i >= 0);
  const lastI = figI.length ? figI[figI.length - 1] : -1;
  const area = figI.length > 1
    ? `M${x(figI[0])},${base} ` + figI.map((i) => `L${x(i).toFixed(1)},${y(pts[i].v!).toFixed(1)}`).join(" ") + ` L${x(lastI)},${base}Z`
    : "";
  const ticks: number[] = [];
  if (size === "lg") { const st = hi - lo > 60 ? 20 : 10; for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) ticks.push(v); }
  const tCol = t?.dir === "up" ? "var(--win)" : t?.dir === "down" ? "var(--bad)" : "var(--muted)";
  const slotW = pw / (SLOTS - 1);
  const h = hov == null ? null : pts[hov];
  const hx = hov == null ? 0 : x(hov);

  return (
    <div className={`figchart ${size}`} onMouseLeave={() => setHov(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="fc-svg" role="img"
        aria-label={`Speed figures, oldest to newest: ${pts.map((p) => (p.v == null ? `${p.pos || "–"} no figure` : Math.round(p.v))).join(", ")}`}>
        <defs>
          <linearGradient id={`ar${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--acc)" stopOpacity=".22" />
            <stop offset="1" stopColor="var(--acc)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* today's-conditions columns */}
        {pts.map((p, i) => p.fit.all ? (
          <rect key={`b${i}`} x={x(i) - Math.min(14, slotW * 0.3)} y={T - 4} width={Math.min(28, slotW * 0.6)} height={ph + 4} rx={5} className="fc-band" />
        ) : null)}
        {ticks.map((v) => (
          <g key={`t${v}`}>
            <line x1={L} x2={W - R + 8} y1={y(v)} y2={y(v)} className="fc-grid" />
            <text x={L - 8} y={y(v) + 4} className="fc-tick" textAnchor="end">{v}</text>
          </g>
        ))}
        <line x1={L} x2={W - R + 8} y1={base} y2={base} className="fc-axis" />
        {refV != null && refV >= lo && refV <= hi && (
          <g>
            <line x1={L} x2={W - R + 4} y1={y(refV)} y2={y(refV)} className="fc-ref" />
            <text x={W - R + 8} y={y(refV) - 2} className="fc-ref-t">{f0(refV)}</text>
            <text x={W - R + 8} y={y(refV) + (size === "lg" ? 12 : 9)} className="fc-ref-s">{refLabel}</text>
          </g>
        )}
        {area && <path d={area} fill={`url(#ar${uid})`} />}
        {segs.map((s, i) => <path key={`s${i}`} d={s.d} className={`fc-line${s.dash ? " gap" : ""}`} />)}
        {t && (
          <line x1={x(t.idx[0])} x2={x(t.idx[t.idx.length - 1])} y1={y(t.a + t.b * t.idx[0])} y2={y(t.a + t.b * t.idx[t.idx.length - 1])}
            className="fc-trend" style={{ stroke: tCol }} />
        )}
        {pts.map((p, i) => {
          const cx = x(i);
          if (p.v == null) {
            return <circle key={`p${i}`} cx={cx} cy={base} r={D.r - 0.6} className={`fc-nofig ${posCls(p.pos)}`} />;
          }
          const cy = y(p.v), r = i === lastI ? D.r + 1.6 : D.r;
          const st = hueStyle(hue(p.v));
          return (
            <g key={`p${i}`} className={hov === i ? "fc-hov" : undefined}>
              {p.fit.all && <circle cx={cx} cy={cy} r={r + 3.6} className="fc-ring" />}
              {p.fit.code
                ? <circle cx={cx} cy={cy} r={r} className="fc-dot" style={st} />
                : <rect x={cx - r} y={cy - r} width={r * 2} height={r * 2} transform={`rotate(45 ${cx} ${cy})`} className="fc-dot other" style={st} />}
              {i === lastI && (
                <text x={cx - r - (p.fit.all ? 8 : 5)} y={cy - r - 1} textAnchor="end" className="fc-last heat" style={st}>{f0(p.v)}</text>
              )}
            </g>
          );
        })}
        {pts.map((p, i) => (
          <g key={`l${i}`}>
            <text x={x(i)} y={base + (size === "lg" ? 16 : 13)} textAnchor="middle" className={`fc-pos ${posCls(p.pos)}`}>{p.pos || "–"}</text>
            {size === "lg" && (
              <>
                <text x={x(i)} y={base + 29} textAnchor="middle" className="fc-date">{fmtD(p.date)}</text>
                <text x={x(i)} y={base + 41} textAnchor="middle" className="fc-crs">{String(p.course ?? "").slice(0, 14)}</text>
              </>
            )}
          </g>
        ))}
        {pts.map((p, i) => (
          <rect key={`h${i}`} x={x(i) - slotW / 2} y={0} width={slotW} height={H} className="fc-hit"
            onMouseEnter={() => setHov(i)} onClick={(e) => { e.stopPropagation(); setHov(i); }} />
        ))}
      </svg>
      {h && (
        <div className={`fc-tip ${hx > W / 2 ? "left" : "right"}`}
          style={{ left: `${((hx + (hx > W / 2 ? -14 : 14)) / W) * 100}%` }}>
          <div className="tip-h"><b>{fmtD(h.date)}</b> · {h.course}</div>
          <div>{h.dist} · {h.code === "AW" ? "AW Flat" : h.code}{h.cls ? ` · Class ${h.cls}` : ""}</div>
          <div className="muted">{goingTxt(h.going) || "going –"}</div>
          <div className="tip-n">
            <span className={`tpos ${posCls(h.pos)}`}>{h.pos || "–"}{h.ran ? `/${h.ran}` : ""}</span>
            {h.v == null ? <span className="muted">no figure</span>
              : <span className="pill-h" style={hueStyle(hue(h.v))}><small>Fig</small><b>{f0(h.v)}</b></span>}
          </div>
          <FitTags f={h} />
        </div>
      )}
    </div>
  );
}

/** C / D / G / Cl tags: does this run match today's code, trip, going and class? */
export function FitTags({ f, compact }: { f: FormRun; compact?: boolean }) {
  const tags: [string, string, boolean | null][] = [
    ["Code", "Same code (Flat / AW / Hurdle / Chase / NHF)", f.fit.code],
    ["Trip", "Distance within 1f or 10% of today", f.fit.dist],
    ["Going", "Similar going (within one step; AW with AW)", f.fit.going],
    ["Class", "Same class or one either side", f.fit.cls],
  ];
  return (
    <span className={`fit${compact ? " compact" : ""}${f.fit.all ? " all" : ""}`}>
      {f.fit.all && !compact && <span className="fit-all">◎ Today&apos;s conditions</span>}
      {tags.map(([k, tt, ok]) => (
        <span key={k} className={`ft ${ok == null ? "unk" : ok ? "ok" : "no"}`} title={`${tt}: ${ok == null ? "unknown" : ok ? "yes" : "no"}`}>
          {ok == null ? "?" : ok ? "✓" : "✗"} {compact ? k[0] + (k === "Class" ? "l" : "") : k}
        </span>
      ))}
    </span>
  );
}

export function ChartLegend({ refLabel }: { refLabel: string }) {
  return (
    <span className="fc-legend">
      <span><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><circle cx="8" cy="8" r="6.3" className="fc-ring" /><circle cx="8" cy="8" r="3.6" className="fc-dot" style={hueStyle(110)} /></svg>today&apos;s conditions</span>
      <span><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><circle cx="6" cy="6" r="4" className="fc-dot" style={hueStyle(110)} /></svg>other run</span>
      <span><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><rect x="2.6" y="2.6" width="6.8" height="6.8" transform="rotate(45 6 6)" className="fc-dot other" style={hueStyle(110)} /></svg>different code</span>
      <span><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><circle cx="6" cy="6" r="3.6" className="fc-nofig" /></svg>no figure</span>
      <span><svg width="20" height="10" viewBox="0 0 20 10" aria-hidden><line x1="1" x2="19" y1="5" y2="5" className="fc-ref" /></svg>{refLabel}</span>
    </span>
  );
}
