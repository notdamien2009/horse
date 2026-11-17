"use client";
// Sectional performance comparison. Existing calculations are passed through unchanged.
// Data source: Race.sectionals from @/lib/racing. No extra requests or database changes.
import { useMemo } from "react";
import type { PaceInfo, Race, SectionPoint, SectionalRun } from "@/lib/racing";
import { PaceBadge } from "./RaceCard";
import { RaceViewNav } from "./RaceViewNav";
import { f0 } from "@/lib/colours";
import SectionalPaceChart, { type SectionalRunner, type SectionalSeries } from "./SectionalPaceChart";

const STYLE_LBL: Record<string, string> = {
  front: "Front", prom: "Prominent", mid: "Midfield", rear: "Held up",
};
const fmtD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

function withSections(runs: SectionalRun[] | undefined): SectionalRun[] {
  return (runs ?? []).filter(r => Array.isArray(r.sectors) && r.sectors.length > 0)
    .sort((a, b) => a.n - b.n).slice(0, 3);
}
function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
function finite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
function avgProfile(runs: SectionalRun[]): SectionPoint[] {
  const byK = new Map<number, number[]>();
  for (const r of runs) for (const s of r.sectors) {
    if (!Number.isFinite(s.k) || !Number.isFinite(s.vs)) continue;
    const list = byK.get(s.k) ?? [];
    list.push(s.vs); byK.set(s.k, list);
  }
  return [...byK.entries()].sort((a, b) => b[0] - a[0])
    .map(([k, values]) => ({ k, vs: mean(values)! }));
}
function seriesAt(points: SectionPoint[], keys: number[]): SectionalSeries {
  const byK = new Map(points.filter(s => Number.isFinite(s.k) && Number.isFinite(s.vs)).map(s => [s.k, s.vs]));
  return keys.map(k => byK.get(k) ?? null);
}
function paceOf(s: SectionalRun): PaceInfo {
  const raw = (s.pace_label || "").toLowerCase().replace(/\s+/g, "-");
  const label: PaceInfo["label"] = raw === "true" || raw === "steady" || raw === "slow" || raw === "fast-early" ? raw : "unknown";
  const figRel: PaceInfo["figRel"] = label === "slow" ? "low" : label === "fast-early" ? "suspect" : "ok";
  return { label, figRel, reason: s.pace_label || "No pace label", source: "sectionals", fsp: s.fin_speed_pct, fieldDef: null };
}

export function RaceSectionals({ race: r }: { race: Race }) {
  const dateLabel = fmtD(r.date);
  const { chartRows, tableRows, labels } = useMemo(() => {
    const rows = r.runners.filter(h => !h.nr).map(h => {
      const runs = withSections(h.sectionals);
      const recent = runs[0] ?? null;
      const pts = recent?.sectors ?? [];
      // An average requires at least two measured runs. A single run is not an 'average of three'.
      const avgPts = runs.length >= 2 ? avgProfile(runs) : [];
      const fsps = runs.map(s => s.fin_speed_pct).filter(finite);
      const figs = runs.map(s => s.fig_adj).filter(finite);
      return { h, recent, runs, pts, avgPts, avgFsp: mean(fsps), avgFig: mean(figs) };
    });
    // Use a common aligned furlong grid. Missing checkpoints remain null, not zero.
    const keys = [...new Set(rows.flatMap(x => [...x.pts, ...x.avgPts].map(p => p.k)))].sort((a,b) => b-a);
    const sectionLabels = keys.map((k, i) => i === keys.length - 1 ? "Fin" : `${k}f`);
    const chart: SectionalRunner[] = rows.filter(x => x.pts.length).map(x => ({
      id: String(x.h.ride_id), name: x.h.horse,
      number: x.h.cloth ?? undefined,
      runContext: x.recent ? `${x.recent.date.slice(8, 10)}/${x.recent.date.slice(5, 7)} · ${x.recent.course}` : undefined,
      averageCount: x.runs.length >= 2 ? x.runs.length : undefined,
      lastRun: seriesAt(x.pts, keys),
      lastThreeAverage: x.avgPts.length ? seriesAt(x.avgPts, keys) : null,
      adjustedFigure: x.recent?.fig_adj ?? null,
      averageAdjustedFigure: x.runs.length >= 2 ? x.avgFig : null,
      lastFsp: x.recent?.fin_speed_pct ?? null,
      averageFsp: x.runs.length >= 2 ? x.avgFsp : null,
    }));
    return { chartRows: chart, tableRows: rows, labels: sectionLabels };
  }, [r]);

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
        <span className="muted small">Compare historical sectional performances · finish on the right</span>
      </div>

      {chartRows.length ? (
        <SectionalPaceChart runners={chartRows} sectionLabels={labels} />
      ) : (
        <div className="empty">No sectional profiles for the active runners in this race yet.</div>
      )}

      <div className="runs-wrap sec-table-wrap" style={{ marginTop: 20 }}>
        <table className="runs sec-table">
          <thead>
            <tr>
              <th>#</th><th>Runner</th>
              <th title="Pace of the most recent recorded run with sectionals">Last pace</th>
              <th title="Finishing speed percentage relative to this horse's own average race speed, NOT its position in the field">FSP</th>
              <th title="Existing pace-adjusted figure for the last measured historical run">Adj fig</th>
              <th title="How this horse ran in its last measured race">Style</th>
              <th title="Average FSP across up to the last three measured runs">Avg FSP</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map(row => (
              <tr key={row.h.ride_id}>
                <td className="n">{row.h.cloth ?? ""}</td>
                <td className="crs">{row.h.horse}</td>
                <td>{row.recent ? <PaceBadge p={paceOf(row.recent)} /> : "–"}</td>
                <td className="n">{row.recent?.fin_speed_pct == null ? "–" : `${row.recent.fin_speed_pct.toFixed(1)}%`}</td>
                <td className="n">{row.recent?.fig_adj == null ? "–" : f0(row.recent.fig_adj)}</td>
                <td>{row.recent?.run_style ? (STYLE_LBL[row.recent.run_style] ?? row.recent.run_style) : "–"}</td>
                <td className="n">{row.avgFsp == null ? "–" : `${row.avgFsp.toFixed(1)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
