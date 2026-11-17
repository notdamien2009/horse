"use client";
// Sectional profile: furlong-by-furlong % vs par, aligned on the finish.
// Last run is a solid line; up to two earlier runs are drawn faint. Hidden when there is no data.
import { useId, useMemo, useState } from "react";
import type { SectionalRun } from "@/lib/racing";
import { f0 } from "@/lib/colours";

const DIMS = {
  sm: { W: 380, H: 110, L: 28, R: 10, T: 14, B: 22, r: 3.2 },
  lg: { W: 960, H: 240, L: 40, R: 16, T: 20, B: 36, r: 4.6 },
};

const STYLE_LBL: Record<string, string> = {
  front: "Front", prom: "Prominent", mid: "Midfield", rear: "Held up",
};
const PACE_LBL: Record<string, string> = {
  True: "True run", Steady: "Steady", Slow: "Slow-run", "Fast-early": "Fast-early",
};

const fmtD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "2-digit" });

function vsTxt(v: number): string {
  const s = `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
  return v >= 0 ? `${s} faster than par` : `${s} slower than par`;
}

export function hasSectionals(runs: SectionalRun[] | null | undefined): boolean {
  return !!runs?.some((r) => r.sectors?.length);
}

export function SectionalChart({ runs, size = "sm" }: { runs: SectionalRun[] | null | undefined; size?: "sm" | "lg" }) {
  const uid = useId().replace(/:/g, "");
  const [hov, setHov] = useState<{ ri: number; si: number } | null>(null);
  const series = useMemo(() => (runs ?? []).filter((r) => r.sectors?.length).slice(0, 3), [runs]);
  if (!series.length) return null;

  const D = DIMS[size];
  const { W, H, L, R, T, B } = D;
  const pw = W - L - R, ph = H - T - B, mid = T + ph / 2;
  const ks = series.flatMap((r) => r.sectors.map((s) => s.k));
  const kMin = Math.min(...ks), kMax = Math.max(...ks);
  const span = Math.max(1, kMax - kMin);
  // k is furlongs from the finish; finish (low k) sits on the right.
  const x = (k: number) => L + ((kMax - k) / span) * pw;
  const allVs = series.flatMap((r) => r.sectors.map((s) => s.vs));
  const maxAbs = Math.max(5, Math.min(12, Math.max(...allVs.map((v) => Math.abs(v))) * 1.15));
  const y = (v: number) => mid - (Math.max(-maxAbs, Math.min(maxAbs, v)) / maxAbs) * (ph / 2);
  const ticks = size === "lg" ? [-Math.round(maxAbs), 0, Math.round(maxAbs)] : [0];
  const kTicks = Array.from(new Set(ks)).sort((a, b) => b - a);
  const last = series[0];
  const earlier = series.slice(1);
  const hx = hov ? x(series[hov.ri].sectors[hov.si].k) : 0;
  const hp = hov ? series[hov.ri].sectors[hov.si] : null;
  const hr = hov ? series[hov.ri] : null;

  const pathOf = (r: SectionalRun) =>
    r.sectors.map((s, i) => `${i ? "L" : "M"}${x(s.k).toFixed(1)},${y(s.vs).toFixed(1)}`).join(" ");

  return (
    <div className={`secchart figchart ${size}`} onMouseLeave={() => setHov(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="fc-svg" role="img"
        aria-label={`Sectional profile, last ${series.length} run${series.length === 1 ? "" : "s"} as percent versus par, finish on the right`}>
        <defs>
          <linearGradient id={`up${uid}`} x1="0" y1="1" x2="0" y2="0">
            <stop offset="0" stopColor="var(--win)" stopOpacity="0" />
            <stop offset="1" stopColor="var(--win)" stopOpacity=".22" />
          </linearGradient>
          <linearGradient id={`dn${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--bad)" stopOpacity="0" />
            <stop offset="1" stopColor="var(--bad)" stopOpacity=".18" />
          </linearGradient>
          <clipPath id={`upC${uid}`}><rect x={L} y={T} width={pw} height={ph / 2} /></clipPath>
          <clipPath id={`dnC${uid}`}><rect x={L} y={mid} width={pw} height={ph / 2} /></clipPath>
        </defs>
        {ticks.map((v) => (
          <g key={`t${v}`}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === 0 ? "sec-par" : "fc-grid"} />
            <text x={L - 6} y={y(v) + 3.5} className="fc-tick" textAnchor="end">{v === 0 ? "Par" : `${v > 0 ? "+" : ""}${v}`}</text>
          </g>
        ))}
        {last.sectors.length > 1 && (
          <>
            <path d={`${pathOf(last)} L${x(last.sectors[last.sectors.length - 1].k)},${mid} L${x(last.sectors[0].k)},${mid} Z`} fill={`url(#up${uid})`} clipPath={`url(#upC${uid})`} />
            <path d={`${pathOf(last)} L${x(last.sectors[last.sectors.length - 1].k)},${mid} L${x(last.sectors[0].k)},${mid} Z`} fill={`url(#dn${uid})`} clipPath={`url(#dnC${uid})`} />
          </>
        )}
        {earlier.map((r, i) => (
          <path key={`p${i}`} d={pathOf(r)} className="sec-line prev" />
        ))}
        <path d={pathOf(last)} className="sec-line last" />
        {earlier.map((r, ri) => r.sectors.map((s, si) => (
          <circle key={`e${ri}-${si}`} cx={x(s.k)} cy={y(s.vs)} r={D.r - 1} className="sec-dot prev" />
        )))}
        {last.sectors.map((s, si) => (
          <circle key={`l${si}`} cx={x(s.k)} cy={y(s.vs)} r={si === last.sectors.length - 1 ? D.r + 0.8 : D.r}
            className={`sec-dot last${s.vs >= 0 ? " fast" : " slow"}`} />
        ))}
        {kTicks.map((k) => (
          <text key={`k${k}`} x={x(k)} y={T + ph + (size === "lg" ? 16 : 14)} textAnchor="middle" className="fc-date">
            {k === kMin ? "Fin" : `${k}f`}
          </text>
        ))}
        {series.flatMap((r, ri) => r.sectors.map((s, si) => (
          <rect key={`h${ri}-${si}`} x={x(s.k) - 8} y={T} width={16} height={ph} className="fc-hit"
            onMouseEnter={() => setHov({ ri, si })} onClick={(e) => { e.stopPropagation(); setHov({ ri, si }); }} />
        )))}
        {hp && <line x1={hx} x2={hx} y1={T} y2={T + ph} className="sec-guide" />}
      </svg>
      {hp && hr && (
        <div className={`fc-tip ${hx > W / 2 ? "left" : "right"}`}
          style={{ left: `${((hx + (hx > W / 2 ? -14 : 14)) / W) * 100}%` }}>
          <div className="tip-h"><b>{fmtD(hr.date)}</b> · {hr.course}{hov?.ri === 0 ? " · last run" : ""}</div>
          <div>{hp.k === kMin ? "Final section" : `${hp.k}f out`}</div>
          <div className={hp.vs >= 0 ? "sec-fast" : "sec-slow"}>{vsTxt(hp.vs)}</div>
          <div className="tip-n">
            {hr.fin_speed_pct != null && <span className="muted">FSP {hr.fin_speed_pct.toFixed(1)}%</span>}
            {hr.fig_adj != null && <span className="muted">Adj {f0(hr.fig_adj)}</span>}
            {hr.run_style && <span className="muted">{STYLE_LBL[hr.run_style] ?? hr.run_style}</span>}
          </div>
          {hr.pace_label && <div className="muted">{PACE_LBL[hr.pace_label] ?? hr.pace_label}</div>}
        </div>
      )}
    </div>
  );
}
