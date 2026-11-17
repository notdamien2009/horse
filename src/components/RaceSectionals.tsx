"use client";
/**
 * Existing FurlongIQ sectional calculations, with opt-in historical-condition filters.
 * No synthetic sectional points, figures, pars, or missing-data substitutions.
 */
import { useMemo, useState } from "react";
import { normCourse, type FormRun, type PaceInfo, type Race, type Runner, type SectionPoint, type SectionalRun } from "@/lib/racing";
import { PaceBadge } from "./RaceCard";
import { RaceViewNav } from "./RaceViewNav";
import { f0 } from "@/lib/colours";
import SectionalPaceChart, { type SectionalRunner, type SectionalSeries } from "./SectionalPaceChart";
import styles from "./RaceSectionals.module.css";

type Scope = "all" | "trip" | "conditions";
const STYLE_LBL: Record<string, string> = {
  front: "Front", prom: "Prominent", mid: "Midfield", rear: "Held up",
};
const fmtD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
const shortD = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });

/** Only known form-record context can qualify for a filter. Unknown is NOT a match. */
function formOf(h: Runner, run: SectionalRun): FormRun | null {
  const course = normCourse(run.course);
  return h.form_runs.find(f => f.date === run.date && course && normCourse(f.course) === course) ?? null;
}
function allowed(h: Runner, run: SectionalRun, scope: Scope): boolean {
  if (scope === "all") return true;
  const f = formOf(h, run);
  if (!f) return false;
  if (scope === "trip") return f.fit.code && f.fit.dist;
  return f.fit.all;
}
function withSections(h: Runner, scope: Scope): SectionalRun[] {
  return (h.sectionals ?? [])
    .filter(r => Array.isArray(r.sectors) && r.sectors.length > 0 && allowed(h, r, scope))
    .sort((a, b) => a.n - b.n)
    .slice(0, 3);
}
function mean(xs: number[]): number | null {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}
function finite(v: number | null | undefined): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
/** An averaged point needs two real observations; do not imply one is a 2/3-run average. */
function avgProfile(runs: SectionalRun[]): SectionPoint[] {
  const byK = new Map<number, number[]>();
  for (const r of runs) for (const s of r.sectors) {
    if (!Number.isFinite(s.k) || !Number.isFinite(s.vs)) continue;
    const list = byK.get(s.k) ?? [];
    list.push(s.vs);
    byK.set(s.k, list);
  }
  return [...byK.entries()]
    .filter(([, values]) => values.length >= 2)
    .sort((a, b) => b[0] - a[0])
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
  const [scope, setScope] = useState<Scope>("all");
  const dateLabel = fmtD(r.date);
  const { chartRows, tableRows, labels, measured, observed } = useMemo(() => {
    const rows = r.runners.filter(h => !h.nr).map(h => {
      const runs = withSections(h, scope);
      const recent = runs[0] ?? null;
      const pts = recent?.sectors ?? [];
      const avgPts = runs.length >= 2 ? avgProfile(runs) : [];
      const fsps = runs.map(s => s.fin_speed_pct).filter(finite);
      const figs = runs.map(s => s.fig_adj).filter(finite);
      return { h, recent, runs, pts, avgPts, avgFsp: mean(fsps), avgFig: mean(figs) };
    });
    const keys = [...new Set(rows.flatMap(x => [...x.pts, ...x.avgPts].map(p => p.k)))].sort((a,b) => b-a);
    const sectionLabels = keys.map((k, i) => i === keys.length - 1 ? "Fin" : `${k}f`);
    const chart: SectionalRunner[] = rows.filter(x => x.pts.length).map(x => ({
      id: String(x.h.ride_id), name: x.h.horse, number: x.h.cloth ?? undefined,
      runContext: x.recent ? `${x.recent.date.slice(8, 10)}/${x.recent.date.slice(5, 7)} · ${x.recent.course}` : undefined,
      averageCount: x.avgPts.length > 0 ? x.runs.length : undefined,
      lastRun: seriesAt(x.pts, keys),
      lastThreeAverage: x.avgPts.length ? seriesAt(x.avgPts, keys) : null,
      adjustedFigure: x.recent?.fig_adj ?? null,
      averageAdjustedFigure: x.runs.length >= 2 ? x.avgFig : null,
      lastFsp: x.recent?.fin_speed_pct ?? null,
      averageFsp: x.runs.length >= 2 ? x.avgFsp : null,
    }));
    return {
      chartRows: chart, tableRows: rows, labels: sectionLabels,
      measured: rows.filter(x => x.recent != null).length,
      observed: rows.reduce((n, x) => n + x.runs.length, 0),
    };
  }, [r, scope]);

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
        <span className="muted small">Measured historical sectional performance · finish on the right</span>
      </div>

      <section className={styles.filterPanel} aria-label="Historical sectional comparison filters">
        <div className={styles.filterHeader}>
          <div>
            <h2>Compare like with like</h2>
            <p>Select which previous runs are eligible. The underlying recorded figures and sectional points are unchanged.</p>
          </div>
          <div className={styles.coverage}>
            <strong>{measured}/{r.active}</strong><span>runners with matched profiles</span>
            <strong>{observed}</strong><span>historical measured runs used</span>
          </div>
        </div>
        <div className={styles.tabs} role="group" aria-label="Historical run filters">
          <button type="button" aria-pressed={scope === "all"} onClick={() => setScope("all")}>All recorded runs</button>
          <button type="button" aria-pressed={scope === "trip"} onClick={() => setScope("trip")}>Same race type + similar trip</button>
          <button type="button" aria-pressed={scope === "conditions"} onClick={() => setScope("conditions")}>Similar today's conditions</button>
        </div>
        <p className={styles.explain}>
          {scope === "all"
            ? "Showing the three most recent measured sectional runs per horse, even when distance, surface or going differ. Compare these pace shapes cautiously."
            : scope === "trip"
              ? "Only historical runs with matching Flat/AW/Hurdle/Chase/NHF type and distance within the existing FurlongIQ trip tolerance qualify."
              : "Only historical runs passing the existing discipline, distance, going and class suitability test qualify. Unknown class is permitted by the existing matching rule."}
        </p>
        {scope !== "all" && <p className={styles.caveat}>
          The filters require matching historical form records in the currently loaded form history (up to eight runs). Older sectionals with no linked form context are excluded, not treated as unsuitable.
        </p>}
      </section>

      {chartRows.length ? (
        <SectionalPaceChart key={scope} runners={chartRows} sectionLabels={labels} />
      ) : (
        <div className={styles.empty}>
          <strong>No comparable sectional profiles in this view</strong>
          <p>That means the available data could not establish a match, not that these horses lack ability.</p>
          {scope !== "all" && <button type="button" onClick={() => setScope("all")}>Show all recorded runs</button>}
        </div>
      )}

      <div className="runs-wrap sec-table-wrap" style={{ marginTop: 20 }}>
        <table className="runs sec-table">
          <thead><tr>
            <th>#</th><th>Runner</th><th>Last measured</th><th>Course</th>
            <th title="Number of historical runs qualifying under the selected filter">Runs</th>
            <th title="Pace of the most recent matching run">Last pace</th>
            <th title="FSP is relative to this horse's own average race speed, not a field ranking">FSP</th>
            <th title="Existing pace-adjusted figure for the most recent matching run">Adj fig</th>
            <th title="Observed running style from last matching run">Style</th>
            <th title="Average FSP across up to three selected historical runs">Avg FSP</th>
          </tr></thead>
          <tbody>
            {tableRows.map(row => (
              <tr key={row.h.ride_id}>
                <td className="n">{row.h.cloth ?? ""}</td>
                <td className="crs">{row.h.horse}</td>
                <td>{row.recent ? shortD(row.recent.date) : "–"}</td>
                <td>{row.recent?.course || "–"}</td>
                <td className="n">{row.runs.length}</td>
                <td>{row.recent ? <PaceBadge p={paceOf(row.recent)} /> : "–"}</td>
                <td className="n">{row.recent?.fin_speed_pct == null ? "–" : `${row.recent.fin_speed_pct.toFixed(1)}%`}</td>
                <td className="n">{row.recent?.fig_adj == null ? "–" : f0(row.recent.fig_adj)}</td>
                <td>{row.recent?.run_style ? (STYLE_LBL[row.recent.run_style] ?? row.recent.run_style) : "–"}</td>
                <td className="n">{row.avgFsp == null || row.runs.length < 2 ? "–" : `${row.avgFsp.toFixed(1)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={styles.disclaimer}>
        Historical sectional profiles are not direct forecasts or race finishing-order rankings.
        Final sectional percentages describe pace relative to that runner's own race speed, not an absolute measure of speed.
        A plotted checkpoint average requires at least two real readings. Missing values remain missing.
      </p>
    </div>
  );
}
