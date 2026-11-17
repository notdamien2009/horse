"use client";
// Per-race sectional comparison: every runner's profile on one chart, plus a compact table.
import { useMemo, useState } from "react";
import type { PaceInfo, Race, SectionPoint, SectionalRun } from "@/lib/racing";
import { PaceBadge } from "./RaceCard";
import { RaceViewNav } from "./RaceViewNav";
import { f0 } from "@/lib/colours";

const STYLE_LBL: Record<string, string> = {
  front: "Front", prom: "Prominent", mid: "Midfield", rear: "Held up",
};
const COLS = [
  "#5b8def", "#e05d5d", "#3dbf8a", "#e0a14a", "#9b7bed", "#d96bb3",
  "#3db8c5", "#8fbe4d", "#ef7a4a", "#6aa0de", "#c46b8a", "#4caf9a",
  "#d4b14a", "#7a8cff", "#c57b5a", "#5aa8d8",
];

const fmtD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
const shortD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

function lastRun(runs: SectionalRun[] | undefined): SectionalRun | null {
  if (!runs?.length) return null;
  return runs.find((s) => s.n === 1) ?? runs[0];
}

function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

function profile(runs: SectionalRun[] | undefined, mode: "last" | "avg3"): SectionPoint[] {
  const src = (runs ?? []).filter((r) => r.sectors?.length).slice(0, mode === "last" ? 1 : 3);
  if (!src.length) return [];
  if (src.length === 1) return src[0].sectors;
  const byK = new Map<number, number[]>();
  for (const r of src) {
    for (const s of r.sectors) {
      const list = byK.get(s.k) ?? [];
      list.push(s.vs);
      byK.set(s.k, list);
    }
  }
  return [...byK.entries()].sort((a, b) => b[0] - a[0]).map(([k, vs]) => ({ k, vs: Math.round((mean(vs) as number) * 100) / 100 }));
}

function avgFsp(runs: SectionalRun[] | undefined): number | null {
  return mean((runs ?? []).map((r) => r.fin_speed_pct).filter((v): v is number => v != null));
}

type Mode = "last" | "avg3";

export function RaceSectionals({ race: r }: { race: Race }) {
  const [mode, setMode] = useState<Mode>("last");
  const [hov, setHov] = useState<{ i: number; si: number } | null>(null);
  const dateLabel = fmtD(r.date);

  const rows = useMemo(() => {
    return r.runners.map((h, i) => ({
      h,
      color: COLS[i % COLS.length],
      last: lastRun(h.sectionals),
      pts: profile(h.sectionals, mode),
      avgFsp: avgFsp(h.sectionals),
    }));
  }, [r, mode]);

  const withPts = rows.filter((x) => x.pts.length && !x.h.nr);
  const [hidden, setHidden] = useState<Set<number>>(() => new Set());
  const visible = withPts.filter((x) => !hidden.has(x.h.ride_id));
  const toggle = (id: number) => setHidden((s) => {
    const n = new Set(s);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  const W = 1100, H = 360, L = 46, R = 16, T = 18, B = 36;
  const pw = W - L - R, ph = H - T - B, mid = T + ph / 2;
  const ks = visible.flatMap((x) => x.pts.map((s) => s.k));
  const kMin = ks.length ? Math.min(...ks) : 0;
  const kMax = ks.length ? Math.max(...ks) : 5;
  const span = Math.max(1, kMax - kMin);
  const x = (k: number) => L + ((kMax - k) / span) * pw;
  const allVs = visible.flatMap((x) => x.pts.map((s) => s.vs));
  const maxAbs = Math.max(5, Math.min(12, (allVs.length ? Math.max(...allVs.map((v) => Math.abs(v))) : 5) * 1.15));
  const y = (v: number) => mid - (Math.max(-maxAbs, Math.min(maxAbs, v)) / maxAbs) * (ph / 2);
  const ticks = [-Math.round(maxAbs), 0, Math.round(maxAbs)];
  const kTicks = [...new Set(ks.length ? ks : [kMax, kMin])].sort((a, b) => b - a);
  const pathOf = (pts: SectionPoint[]) =>
    pts.map((s, i) => `${i ? "L" : "M"}${x(s.k).toFixed(1)},${y(s.vs).toFixed(1)}`).join(" ");

  const hp = hov && visible[hov.i] ? visible[hov.i].pts[hov.si] : null;
  const hr = hov && visible[hov.i] ? visible[hov.i] : null;
  const hx = hp ? x(hp.k) : 0;

  return (
    <div className="race">
      <section className="hero sec-hero">
        <div className="hero-head">
          <div className="hero-time"><span>{r.time}</span></div>
          <div className="hero-title">
            <div className="hero-course">{r.course} <span>· {dateLabel}</span></div>
            <h1>Sectionals · {r.name}</h1>
          </div>
        </div>
        <div className="facts">
          {r.race_class && <span className="fact"><small>Class</small><b>{r.race_class}</b></span>}
          <span className="fact"><small>Distance</small><b>{r.distance}</b></span>
          <span className="fact going"><small>Going</small><b>{r.going || "–"}</b></span>
          <span className="fact"><small>Type</small><b>{r.family}{r.handicap ? " handicap" : ""}</b></span>
          <span className="fact"><small>Runners</small><b>{r.active}</b></span>
        </div>
      </section>

      <div className="toolbar">
        <RaceViewNav raceId={r.race_id} view="sectionals" />
        <div className="seg" role="group" aria-label="Profile type">
          <button type="button" className={mode === "last" ? "on" : ""} aria-pressed={mode === "last"} onClick={() => setMode("last")}>Last run</button>
          <button type="button" className={mode === "avg3" ? "on" : ""} aria-pressed={mode === "avg3"} onClick={() => setMode("avg3")}>Last 3 average</button>
        </div>
        <span className="muted small hide-sm">% vs section par · finish on the right · click a name to show or hide</span>
      </div>

      {!withPts.length ? (
        <div className="empty">No sectional profiles for this race yet.</div>
      ) : (
        <div className="sec-compare figchart">
          <svg viewBox={`0 0 ${W} ${H}`} className="fc-svg" role="img"
            aria-label={`Sectional profiles for ${visible.length} runners, percent versus par, finish on the right`}>
            {ticks.map((v) => (
              <g key={`t${v}`}>
                <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className={v === 0 ? "sec-par" : "fc-grid"} />
                <text x={L - 6} y={y(v) + 3.5} className="fc-tick" textAnchor="end">{v === 0 ? "Par" : `${v > 0 ? "+" : ""}${v}`}</text>
              </g>
            ))}
            {visible.map((row) => (
              <path key={`l${row.h.ride_id}`} d={pathOf(row.pts)} className="sec-line last" style={{ stroke: row.color }} />
            ))}
            {visible.map((row) => row.pts.map((s, si) => (
              <circle key={`d${row.h.ride_id}-${si}`} cx={x(s.k)} cy={y(s.vs)} r={si === row.pts.length - 1 ? 4.2 : 3.2}
                className="sec-dot last" style={{ fill: row.color }} />
            )))}
            {kTicks.map((k) => (
              <text key={`k${k}`} x={x(k)} y={T + ph + 18} textAnchor="middle" className="fc-date">
                {k === kMin ? "Fin" : `${k}f`}
              </text>
            ))}
            {visible.flatMap((row, i) => row.pts.map((s, si) => (
              <rect key={`h${row.h.ride_id}-${si}`} x={x(s.k) - 10} y={T} width={20} height={ph} className="fc-hit"
                onMouseEnter={() => setHov({ i, si })} onMouseLeave={() => setHov(null)} />
            )))}
            {hp && <line x1={hx} x2={hx} y1={T} y2={T + ph} className="sec-guide" />}
          </svg>
          {hp && hr && (
            <div className={`fc-tip ${hx > W / 2 ? "left" : "right"}`}
              style={{ left: `${((hx + (hx > W / 2 ? -14 : 14)) / W) * 100}%` }}>
              <div className="tip-h"><b style={{ color: hr.color }}>{hr.h.horse}</b></div>
              <div>{hp.k === kMin ? "Final section" : `${hp.k}f out`} · {hp.vs >= 0 ? "+" : ""}{hp.vs.toFixed(1)}% vs par</div>
              {mode === "last" && hr.last && (
                <div className="muted">{shortD(hr.last.date)} · {hr.last.course}</div>
              )}
              {mode === "avg3" && <div className="muted">Average of last {Math.min(3, (hr.h.sectionals ?? []).filter((s) => s.sectors?.length).length)} runs</div>}
            </div>
          )}
        </div>
      )}

      {!!withPts.length && (
        <div className="sec-legend" aria-label="Toggle runners">
          {withPts.map((row) => {
            const off = hidden.has(row.h.ride_id);
            return (
              <button key={row.h.ride_id} type="button" className={`sec-leg${off ? " off" : ""}`}
                aria-pressed={!off} onClick={() => toggle(row.h.ride_id)} title={off ? `Show ${row.h.horse}` : `Hide ${row.h.horse}`}>
                <i style={{ background: off ? "transparent" : row.color, borderColor: row.color }} />
                {row.h.cloth != null && <span className="sec-cloth">{row.h.cloth}</span>}
                {row.h.horse}
              </button>
            );
          })}
        </div>
      )}

      <div className="runs-wrap sec-table-wrap">
        <table className="runs sec-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Runner</th>
              <th title="Pace of the most recent run with sectionals">Last pace</th>
              <th title="Finishing speed % on the last run. Above 100% means the horse finished more strongly than the field.">FSP</th>
              <th title="Pace-adjusted figure on the last run">Adj fig</th>
              <th title="How they ran the last race: front, prominent, midfield or held up">Style</th>
              <th title="Average finishing speed % across recent runs with sectionals">Avg FSP</th>
            </tr>
          </thead>
          <tbody>
            {rows.filter((x) => !x.h.nr).map((row) => (
              <tr key={row.h.ride_id} className={hidden.has(row.h.ride_id) ? "dim" : undefined}>
                <td className="n">{row.h.cloth ?? ""}</td>
                <td className="crs">
                  <button type="button" className="sec-name" onClick={() => row.pts.length && toggle(row.h.ride_id)}>
                    <i style={{ background: hidden.has(row.h.ride_id) || !row.pts.length ? "transparent" : row.color, borderColor: row.color }} />
                    {row.h.horse}
                  </button>
                </td>
                <td>{row.last ? <PaceBadge p={paceOf(row.last)} /> : "–"}</td>
                <td className="n">{row.last?.fin_speed_pct == null ? "–" : `${row.last.fin_speed_pct.toFixed(1)}%`}</td>
                <td className="n">{row.last?.fig_adj == null ? "–" : f0(row.last.fig_adj)}</td>
                <td>{row.last?.run_style ? (STYLE_LBL[row.last.run_style] ?? row.last.run_style) : "–"}</td>
                <td className="n">{row.avgFsp == null ? "–" : `${row.avgFsp.toFixed(1)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function paceOf(s: SectionalRun): PaceInfo {
  const raw = (s.pace_label || "").toLowerCase().replace(/\s+/g, "-");
  const label: PaceInfo["label"] = raw === "true" || raw === "steady" || raw === "slow" || raw === "fast-early" ? raw : "unknown";
  const figRel: PaceInfo["figRel"] = label === "slow" ? "low" : label === "fast-early" ? "suspect" : "ok";
  return { label, figRel, reason: s.pace_label || "No pace label", source: "sectionals", fsp: s.fin_speed_pct, fieldDef: null };
}
