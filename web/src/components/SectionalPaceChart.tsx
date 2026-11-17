"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import styles from "./SectionalPaceChart.module.css";

/** Values MUST already be the existing signed % difference from each section's par.
 * Missing data is null. This component never recalculates par, FSP, or speed figures. */
export type SectionalSeries = readonly (number | null)[];
export type SectionalRunner = {
  id: string;
  name: string;
  number?: number | string;
  /** Date/course of the latest observed historical race, to avoid confusing runs with todays race. */
  runContext?: string;
  /** Number of actual runs underpinning the historical average (2 or 3). */
  averageCount?: number;
  lastRun: SectionalSeries;
  lastThreeAverage?: SectionalSeries | null;
  /** Existing comparable adjusted figure from the source system, NOT derived from the lines. */
  adjustedFigure?: number | null;
  averageAdjustedFigure?: number | null;
  /** Information only. FSP is relative to the horse's own race speed, not a field ranking. */
  lastFsp?: number | null;
  averageFsp?: number | null;
};
export type SectionalPaceChartProps = {
  runners: SectionalRunner[];
  sectionLabels: string[];
  className?: string;
};

type SourceMode = "last" | "avg";
type Metric = "close" | "lift" | "rating";
const COLOURS = ["#55d9f8", "#f6be63", "#bc9bff"] as const;
const VW = 940, VH = 340, LEFT = 57, RIGHT = 28, TOP = 29, BOTTOM = 49, MAX_SELECTED = 3;
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const signed = (value: number | null | undefined, unit = "%") =>
  isNumber(value) ? `${value > 0 ? "+" : ""}${value.toFixed(1)}${unit}` : "—";
const fig = (value: number | null | undefined) => isNumber(value) ? `${Number(value.toFixed(1))}` : "—";
const avgTwo = (a: number | null | undefined, b: number | null | undefined): number | null =>
  isNumber(a) && isNumber(b) ? (a + b) / 2 : null;
function activeSeries(r: SectionalRunner, mode: SourceMode): SectionalSeries {
  return (mode === "avg" ? r.lastThreeAverage : r.lastRun) ?? [];
}
function metrics(r: SectionalRunner, mode: SourceMode, n: number) {
  const p = activeSeries(r, mode);
  const close = n >= 2 ? avgTwo(p[n - 2], p[n - 1]) : null;
  const open = n >= 4 ? avgTwo(p[0], p[1]) : null;
  return {
    close,
    lift: isNumber(close) && isNumber(open) ? close - open : null,
    rating: mode === "avg" ? (r.averageAdjustedFigure ?? null) : (r.adjustedFigure ?? null),
    fsp: mode === "avg" ? (r.averageFsp ?? null) : (r.lastFsp ?? null),
  };
}
function sortByMetric(runners: SectionalRunner[], mode: SourceMode, metric: Metric, n: number) {
  return [...runners].filter(r => isNumber(metrics(r, mode, n)[metric]))
    .sort((a, b) => (metrics(b, mode, n)[metric] ?? -Infinity) - (metrics(a, mode, n)[metric] ?? -Infinity));
}
function initialFocus(runners: SectionalRunner[], mode: SourceMode, metric: Metric, n: number) {
  return sortByMetric(runners, mode, metric, n).slice(0, MAX_SELECTED).map(r => r.id);
}

/** Shape-preserving cubic interpolation. Only renders *between* adjacent measured points.
 * Never bridges nulls or overshoots between values. No inferred point is ranked. */
function smoothPath(values: SectionalSeries, first: number, last: number, x: (i: number) => number, y: (v: number) => number) {
  const runs: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [];
  for (let i = first; i <= last; i++) {
    const v = values[i];
    if (!isNumber(v)) { if (current.length) runs.push(current); current = []; continue; }
    current.push({ x: x(i), y: y(v) });
  }
  if (current.length) runs.push(current);
  return runs.map(points => {
    if (points.length === 1) return `M${points[0].x},${points[0].y}`;
    const n = points.length;
    const d = Array.from({ length: n - 1 }, (_, i) =>
      (points[i + 1].y - points[i].y) / (points[i + 1].x - points[i].x));
    const m: number[] = Array(n).fill(0);
    m[0] = d[0]; m[n - 1] = d[n - 2];
    for (let i = 1; i < n - 1; i++) {
      m[i] = d[i - 1] * d[i] <= 0 ? 0 : 2 * d[i - 1] * d[i] / (d[i - 1] + d[i]);
    }
    for (let i = 0; i < n - 1; i++) {
      if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      const a = m[i] / d[i], b = m[i + 1] / d[i];
      const sum = a * a + b * b;
      if (sum > 9) { const factor = 3 / Math.sqrt(sum); m[i] *= factor; m[i + 1] *= factor; }
    }
    return points.slice(1).reduce((path, p, i) => {
      const a = points[i], step = p.x - a.x;
      return `${path} C${(a.x + step / 3).toFixed(2)},${(a.y + m[i] * step / 3).toFixed(2)} ${(p.x - step / 3).toFixed(2)},${(p.y - m[i + 1] * step / 3).toFixed(2)} ${p.x.toFixed(2)},${p.y.toFixed(2)}`;
    }, `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)}`);
  }).join(" ");
}

const definitions: Record<Metric, { label: string; short: string; unit: string; detail: string }> = {
  close: { label: "Strongest close", short: "Closing pace", unit: "%", detail: "Average of the last 2 reported checkpoints against their section pars; not necessarily the fastest raw final time." },
  lift: { label: "Biggest late lift", short: "Late vs early", unit: "pp", detail: "Closing 2-checkpoint average minus opening 2-checkpoint average, in percentage points. Relative change, not absolute race speed." },
  rating: { label: "Best rated run", short: "Adjusted figure", unit: "", detail: "Highest existing comparable adjusted figure. No figure is invented from the pace curves." },
};

export default function SectionalPaceChart({ runners, sectionLabels, className = "" }: SectionalPaceChartProps) {
  const [mode, setMode] = useState<SourceMode>("last");
  const [metric, setMetric] = useState<Metric>("close");
  const [zoomFinish, setZoomFinish] = useState(false);
  const [selected, setSelected] = useState<string[]>(() => initialFocus(runners, "last", "close", sectionLabels.length));
  const [section, setSection] = useState(Math.max(0, sectionLabels.length - 1));
  const [query, setQuery] = useState("");
  const chartViewport = useRef<HTMLDivElement | null>(null);
  const identity = runners.map(r => r.id).join("\u001f") + `|${sectionLabels.join("\u001f")}`;
  useEffect(() => {
    setMode("last"); setMetric("close"); setSelected(initialFocus(runners, "last", "close", sectionLabels.length));
    setSection(Math.max(0, sectionLabels.length - 1)); setZoomFinish(false); setQuery("");
    // Reset only when field or checkpoints change; not when asynchronous metrics refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [identity]);

  // On narrow screens show the *finish* immediately instead of hiding it to the right.
  useEffect(() => {
    const viewport = chartViewport.current;
    if (viewport && typeof window !== "undefined" && window.matchMedia("(max-width: 670px)").matches) {
      viewport.scrollLeft = viewport.scrollWidth - viewport.clientWidth;
    }
  }, [zoomFinish, mode, identity]);

  const n = sectionLabels.length;
  const avgAvailable = runners.some(r => r.lastThreeAverage?.some(isNumber));
  const rankings = useMemo(() => ({
    close: sortByMetric(runners, mode, "close", n),
    lift: sortByMetric(runners, mode, "lift", n),
    rating: sortByMetric(runners, mode, "rating", n),
  }), [runners, mode, n]);
  const leaderboard = rankings[metric];
  const selectedRunners = selected.map(id => runners.find(r => r.id === id)).filter((r): r is SectionalRunner => Boolean(r));
  const colourOf = (r: SectionalRunner) => COLOURS[selected.findIndex(id => id === r.id)] ?? COLOURS[0];
  const visibleStart = zoomFinish && n > 4 ? n - 4 : 0;
  const visibleEnd = n - 1;
  const inRange = runners.flatMap(r => activeSeries(r, mode).slice(visibleStart, n).filter(isNumber));
  const maxAbsolute = Math.max(4, Math.ceil((Math.max(0, ...inRange.map(Math.abs)) + 0.8) / 2) * 2);
  const xx = (index: number) => LEFT + ((index - visibleStart) / Math.max(1, visibleEnd - visibleStart)) * (VW - LEFT - RIGHT);
  const yy = (value: number) => TOP + ((maxAbsolute - value) / (2 * maxAbsolute)) * (VH - TOP - BOTTOM);
  const ticks = [maxAbsolute, maxAbsolute / 2, 0, -maxAbsolute / 2, -maxAbsolute];
  const currentSection = Math.min(Math.max(section, visibleStart), Math.max(visibleEnd, 0));
  const inspect = selectedRunners.filter(r => isNumber(activeSeries(r, mode)[currentSection]));

  function chooseMetric(next: Metric) {
    setMetric(next); setSelected(initialFocus(runners, mode, next, n));
  }
  function chooseMode(next: SourceMode) {
    setMode(next); setSelected(initialFocus(runners, next, metric, n));
  }
  function toggleRunner(id: string) {
    setSelected(prev => prev.includes(id) ? prev.filter(i => i !== id) : [...prev.slice(-(MAX_SELECTED - 1)), id]);
  }
  if (!n) return <section className={`${styles.root} ${className}`}>No sectional checkpoints available.</section>;
  return (
    <section className={`${styles.root} ${className}`} aria-label="Sectional strength analysis">
      <header className={styles.header}>
        <div><div className={styles.eyebrow}>SECTIONAL PERFORMANCE / ANALYSIS</div><h2>Who ran strongest?</h2>
          <p>Compare the complete effort, the closing pace and the late improvement. Historical races may differ in date, going and course. One ranking cannot answer all three.</p></div>
        <div className={styles.switcher} role="group" aria-label="Historical runs">
          <button type="button" aria-pressed={mode === "last"} onClick={() => chooseMode("last")}>Last run</button>
          <button type="button" aria-pressed={mode === "avg"} disabled={!avgAvailable} onClick={() => chooseMode("avg")}>Last 3 average</button>
        </div>
      </header>
      <div className={styles.insightGrid}>
        {(["rating", "close", "lift"] as const).map(key => {
          const leader = rankings[key][0];
          const stat = leader ? metrics(leader, mode, n)[key] : null;
          return <button type="button" key={key} className={styles.insight} aria-pressed={metric === key} onClick={() => chooseMetric(key)}>
            <span className={styles.insightTitle}>{definitions[key].label} <span aria-hidden="true">↗</span></span>
            <strong>{leader ? leader.name : "No qualifying data"}</strong>
            <span className={styles.insightBottom}>{isNumber(stat) ? (key === "rating" ? fig(stat) : signed(stat, definitions[key].unit)) : "—"}<small>{definitions[key].short}</small></span>
          </button>;
        })}
      </div>
      <div className={styles.explainer} role="status"><strong>{definitions[metric].label}:</strong> {definitions[metric].detail}</div>
      <div className={styles.workspace}>
        <div className={styles.left}>
          <div className={styles.chartHeader}>
            <div><h3>Section-by-section pace</h3><span>Signed difference versus each section's par (%)</span></div>
            <div className={styles.chartTools} role="group" aria-label="Chart range">
              <button type="button" aria-pressed={!zoomFinish} onClick={() => setZoomFinish(false)}>Full race</button>
              <button type="button" aria-pressed={zoomFinish} onClick={() => { setZoomFinish(true); setSection(Math.max(0,n - 1)); }}>Final stages</button>
            </div>
          </div>
          <div className={styles.svgScroll} ref={chartViewport}>
            <svg className={styles.chart} viewBox={`0 0 ${VW} ${VH}`} role="img" aria-label="Smoothly connected measured sectional percentages, with selected runners highlighted and all other runners faded">
              {n >= 2 && <rect x={Math.max(LEFT, xx(n - 2) - 14)} y={TOP - 9} width={Math.max(0, xx(n - 1) - xx(n - 2) + 28)} height={VH - TOP - BOTTOM + 18} rx="10" className={styles.finishZone}/>}
              {ticks.map((t, i) => <g key={i}>
                <line x1={LEFT} x2={VW - RIGHT} y1={yy(t)} y2={yy(t)} className={t === 0 ? styles.par : styles.gridLine}/>
                <text x={LEFT - 13} y={yy(t) + 4} className={styles.axis} textAnchor="end">{t > 0 ? "+" : ""}{Number(t.toFixed(1))}</text>
              </g>)}
              <line x1={xx(currentSection)} x2={xx(currentSection)} y1={TOP - 8} y2={VH - BOTTOM + 8} className={styles.inspectionLine}/>
              {sectionLabels.slice(visibleStart).map((label, i) => <text key={`${i}:${label}`} x={xx(visibleStart + i)} y={VH - 19} textAnchor="middle" className={styles.axis}>{label}</text>)}
              {runners.filter(r => !selected.includes(r.id)).map(r => <path key={r.id} d={smoothPath(activeSeries(r, mode), visibleStart, visibleEnd, xx, yy)} fill="none" className={styles.backgroundTrace}/>)}
              {selectedRunners.map(r => <g key={r.id}>
                <path d={smoothPath(activeSeries(r, mode), visibleStart, visibleEnd, xx, yy)} fill="none" stroke={colourOf(r)} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round"/>
                {activeSeries(r, mode).slice(visibleStart, n).map((v, i) => {
                  if (!isNumber(v)) return null;
                  const j = i + visibleStart;
                  return <g key={j}>
                    <circle cx={xx(j)} cy={yy(v)} r={j === currentSection ? 7 : 5} fill={colourOf(r)} stroke="#08121d" strokeWidth="2"/>
                    <circle cx={xx(j)} cy={yy(v)} r="15" fill="transparent" className={styles.hitTarget} role="button" tabIndex={0} aria-label={`${r.name} at ${sectionLabels[j]}: ${signed(v)}`} onClick={() => setSection(j)} onFocus={() => setSection(j)} onKeyDown={(e: { key: string; preventDefault(): void }) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSection(j); } }}/>
                  </g>;
                })}
              </g>)}
            </svg>
          </div>
          <p className={styles.scrollNote}>On a small screen, swipe the chart sideways. Curves join measured points only; they do not add readings.</p>
          <div className={styles.sectionButtons} role="group" aria-label="Inspect a section">
            {sectionLabels.slice(visibleStart).map((label, i) => <button key={i} type="button" aria-pressed={currentSection === visibleStart + i} onClick={() => setSection(visibleStart + i)}>{label}</button>)}
          </div>
          <div className={styles.inspector} aria-live="polite">
            <div className={styles.inspectTitle}><span>AT {sectionLabels[currentSection]}</span><strong>{currentSection === n - 1 ? "Final checkpoint" : "Section inspection"}</strong></div>
            <div className={styles.inspectItems}>{inspect.length ? inspect.map(r => <div className={styles.inspectItem} key={r.id} style={{ borderLeftColor: colourOf(r) }}>
              <span>{r.name}</span><strong>{signed(activeSeries(r, mode)[currentSection])}</strong>
            </div>) : <span className={styles.dim}>Select a runner to inspect.</span>}</div>
          </div>
        </div>
        <aside className={styles.right}>
          <div className={styles.leaderHeader}><div><h3>{definitions[metric].label} — ranked</h3><p>Only runners with sufficient data appear.</p></div><span>{leaderboard.length} ranked</span></div>
          <div className={styles.leaderRows}>{leaderboard.length ? leaderboard.map((r, i) => <button key={r.id} type="button" className={styles.leaderRow} aria-pressed={selected.includes(r.id)} onClick={() => toggleRunner(r.id)} aria-label={`${r.name}, rank ${i+1}, ${definitions[metric].short} ${metric === "rating" ? fig(metrics(r, mode, n).rating) : signed(metrics(r, mode, n)[metric], definitions[metric].unit)}. Click to ${selected.includes(r.id) ? "remove from" : "add to"} chart comparison`}>
            <span className={styles.rank}>{i + 1}</span><span className={styles.leaderName}>{r.name}<small>{r.number != null ? `#${r.number} · ` : ""}{mode === "avg" ? (r.averageCount ? `Avg ${r.averageCount} runs` : "No average") : (r.runContext || "Historical run")}{selected.includes(r.id) ? " · Highlighted" : ""}</small></span>
            <strong>{metric === "rating" ? fig(metrics(r, mode, n).rating) : signed(metrics(r, mode, n)[metric], definitions[metric].unit)}</strong>
            <span className={styles.dot} style={{ background: selected.includes(r.id) ? colourOf(r) : "#516477" }}/>
          </button>) : <p className={styles.noData}>This ranking is unavailable because its required figures are missing. Choose another measure.</p>}</div>
          <div className={styles.rightFoot}>Click any horse to compare, up to three at once. Unselected runners remain visible as faint traces.</div>
        </aside>
      </div>
      <div className={styles.runnerPanel}>
        <div className={styles.runnerTitle}><h3>Custom comparison</h3><span>{selected.length} of {MAX_SELECTED} focused</span></div>
        <div className={styles.searchArea}><input type="search" aria-label="Find a runner" placeholder="Find a horse…" value={query} onChange={(e: { target: { value: string } }) => setQuery(e.target.value)}/><button type="button" onClick={() => setSelected(initialFocus(runners, mode, metric, n))}>Restore top 3</button><button type="button" onClick={() => setSelected([])}>Clear</button></div>
        <div className={styles.runnerChips}>{runners.filter(r => r.name.toLowerCase().includes(query.toLowerCase().trim())).map(r => <button key={r.id} type="button" aria-pressed={selected.includes(r.id)} onClick={() => toggleRunner(r.id)}>
          <span className={styles.chipIndicator} style={{ background: selected.includes(r.id) ? colourOf(r) : "#506073" }}/><span>{r.number != null ? `${r.number} · ` : ""}{r.name}</span>
        </button>)}</div>
      </div>
      <footer className={styles.disclaimer}>Par = 0%. The highlighted closing zone covers the last two supplied checkpoints. These are different historical runs, not runners measured in the same race. A pace profile is <strong>not</strong> a finishing-position ranking or a prediction. Adjusted figures must be supplied by your existing model. Missing data remains missing.</footer>
    </section>
  );
}
