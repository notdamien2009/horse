"use client";

/**
 * FurlongIQ decision workspace.
 * Presentation only: all figures, probabilities, condition matches and sectionals
 * come from the existing Race payload. No new ratings or probability model.
 */
import { useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowDownWideNarrow, ArrowUpRight, BarChart3, Check, ChevronDown,
  Clock3, GitCompareArrows, Info, Search, ShieldAlert, Target, TrendingUp,
} from "lucide-react";
import type { FormRun, Race, Runner, SectionalRun } from "@/lib/racing";
import styles from "./RaceIntelligence.module.css";

type SortKey = "pred" | "last" | "best3" | "conditions" | "win" | "card";
type StyleKey = "front" | "prom" | "mid" | "rear" | "unknown";
const STYLE: Record<StyleKey, string> = {
  front: "Front", prom: "Prominent", mid: "Midfield", rear: "Held up", unknown: "Unknown",
};
const SORT_LABEL: Record<SortKey, string> = {
  pred: "Predicted speed", last: "Last rated speed", best3: "Best 3 average",
  conditions: "Best at today's conditions", win: "Model win %", card: "Racecard order",
};
const fmt = (x: number | null | undefined, decimals = 0) =>
  x == null || !Number.isFinite(x) ? "—" : x.toFixed(decimals);
const day = (s: string) => {
  const d = new Date(`${String(s).slice(0, 10)}T12:00:00`);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
};
const number = (s: string | null | undefined) => (s || "—").replace(/\s*\(.*$/, "");
const rated = (f: FormRun, juv: boolean) => juv ? f.fig2 : f.fig;
const lastRated = (h: Runner, juv: boolean): number | null => {
  if (!juv) return h.ratings.last;
  return h.form_runs.find(f => f.fig2 != null)?.fig2 ?? null;
};
const best3 = (h: Runner, juv: boolean) => juv ? h.ratings.best3_2yo : h.ratings.best3;
const lastMeasured = (h: Runner): SectionalRun | null =>
  h.sectionals?.find(s => s.run_style != null || s.fin_speed_pct != null) ?? null;
const styleOf = (h: Runner): StyleKey => {
  const style = lastMeasured(h)?.run_style;
  return style === "front" || style === "prom" || style === "mid" || style === "rear" ? style : "unknown";
};
const indicator = (p: string): "win" | "place" | "bad" | "other" =>
  p === "1" ? "win" : p === "2" || p === "3" ? "place" : /^[A-Z]/.test(p) ? "bad" : "other";
function value(h: Runner, juv: boolean, sort: SortKey): number | null {
  switch (sort) {
    case "pred": return h.pred;
    case "last": return lastRated(h, juv);
    case "best3": return best3(h, juv);
    case "conditions": return h.cond_best?.fig ?? null;
    case "win": return h.win_pct;
    case "card": return h.cloth ?? null;
  }
}
function evidence(h: Runner, juv: boolean) {
  // The legacy nfigs field counts standard-scale figures, not juvenile fig2.
  // For juveniles disclose the visible form-window count instead of implying
  // that a zero standard-scale count means no juvenile figures exist.
  const count = juv ? h.form_runs.filter(f => f.fig2 != null).length : h.ratings.nfigs;
  const matched = h.cond_best?.n ?? 0;
  const points: string[] = [];
  if (count === 0) points.push(juv ? "No 2yo figures in visible form" : "No recorded speed figures");
  else if (count < 3) points.push(juv ? "Limited visible 2yo form" : "Limited speed history");
  if (matched === 0) points.push("No verified matching-condition figure");
  if (h.last_ran_days != null && h.last_ran_days >= 150) points.push(`${h.last_ran_days} days since last run`);
  if (h.pred == null) points.push("No speed prediction");
  return { count, matched, points };
}
function bestHorse(horses: Runner[], fn: (h: Runner) => number | null): Runner | null {
  return horses.reduce<Runner | null>((best, h) => {
    const v = fn(h);
    return v != null && (best == null || fn(best) == null || v > fn(best)!) ? h : best;
  }, null);
}

function MiniForm({ h }: { h: Runner }) {
  const form = h.form_runs.slice(0, 5);
  if (!form.length) return <span className={styles.na}>No form</span>;
  return (
    <span className={styles.formRow} aria-label={`Last ${form.length} finishing results, most recent first`}>
      {form.map((f, i) => (
        <span key={`${f.date}-${i}`} title={`${day(f.date)} ${f.course}: ${f.pos || "not recorded"}`}
          className={`${styles.formChip} ${styles[indicator(String(f.pos ?? "").toUpperCase())]}`}>
          {f.pos || "–"}
        </span>
      ))}
    </span>
  );
}

function QuickForm({ h, juv, onClose }: { h: Runner; juv: boolean; onClose: () => void }) {
  return (
    <section className={styles.quickForm} aria-label={`${h.horse} quick form`}>
      <div className={styles.quickHead}>
        <div>
          <p className={styles.eyebrow}>Recorded form · most recent first</p>
          <h3>{h.horse}</h3>
        </div>
        <div className={styles.quickActions}>
          <a href={`#r-${h.ride_id}`}>Full horse card <ArrowUpRight size={13} aria-hidden /></a>
          <button type="button" onClick={onClose}>Close</button>
        </div>
      </div>
      {h.form_runs.length === 0 ? <p className={styles.muted}>No historical form available for this runner.</p> : (
        <div className={styles.tableScroll} role="region" aria-label={`${h.horse} historical results`} tabIndex={0}>
          <table className={styles.quickTable}>
            <thead><tr>
              <th scope="col">Date</th><th scope="col">Course</th><th scope="col">Pos</th>
              <th scope="col">Speed</th><th scope="col">Cls</th><th scope="col">Dist</th>
              <th scope="col">Going</th><th scope="col">Conditions</th><th scope="col">Race comment</th>
            </tr></thead>
            <tbody>
              {h.form_runs.slice(0, 8).map((f, i) => (
                <tr key={`${f.date}-${i}`}>
                  <td>{day(f.date)}</td><td>{f.course}</td>
                  <td><strong>{f.pos || "—"}{f.ran != null ? `/${f.ran}` : ""}</strong></td>
                  <td className={styles.numeric}>{fmt(rated(f, juv))}</td>
                  <td>{f.cls || "—"}</td><td>{f.dist || "—"}</td><td>{number(f.going)}</td>
                  <td><span className={f.fit.all ? styles.match : styles.na}>
                    {f.fit.all ? "Similar*" : "Different / unknown"}
                  </span></td>
                  <td className={styles.comment}>{f.comment || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className={styles.footnote}>
        * Similar uses FurlongIQ's existing code, trip, going and class matching rules; it is not proof of an identical track or race setup.
        Figures are historical performances, not predictions.
      </p>
    </section>
  );
}

export function RaceIntelligence({ race: r }: { race: Race }) {
  const juv = r.rank_basis.startsWith("2yo");
  const [sort, setSort] = useState<SortKey>("pred");
  const [query, setQuery] = useState("");
  const [showNr, setShowNr] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [quickId, setQuickId] = useState<number | null>(null);
  const active = useMemo(() => r.runners.filter(h => !h.nr), [r.runners]);

  const leaders = useMemo(() => ({
    pred: bestHorse(active, h => h.pred),
    last: bestHorse(active, h => lastRated(h, juv)),
    conditions: bestHorse(active, h => h.cond_best?.fig ?? null),
    win: bestHorse(active, h => h.win_pct),
  }), [active, juv]);
  const ratedCount = active.filter(h => h.pred != null).length;
  const modelDisagrees = leaders.pred && leaders.win && leaders.pred.ride_id !== leaders.win.ride_id;
  const rows = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("en-GB");
    const filtered = r.runners.filter(h => (showNr || !h.nr) && (!q || String(h.horse ?? "").toLocaleLowerCase("en-GB").includes(q)));
    return filtered.sort((a, b) => {
      if (a.nr !== b.nr) return Number(a.nr) - Number(b.nr);
      if (sort === "card") return (a.cloth ?? 999) - (b.cloth ?? 999);
      const av = value(a, juv, sort), bv = value(b, juv, sort);
      if (av == null && bv == null) return (a.cloth ?? 999) - (b.cloth ?? 999);
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av || (a.cloth ?? 999) - (b.cloth ?? 999);
    });
  }, [r.runners, juv, query, showNr, sort]);

  const checked = selected.map(id => r.runners.find(h => h.ride_id === id))
    .filter((h): h is Runner => h != null && !h.nr);
  const currentQuick = r.runners.find(h => h.ride_id === quickId) ?? null;
  const toggle = (id: number) => setSelected(prev => prev.includes(id)
    ? prev.filter(x => x !== id) : prev.length < 3 ? [...prev, id] : prev);
  const pace = useMemo(() => {
    const groups: Record<StyleKey, Runner[]> = { front: [], prom: [], mid: [], rear: [], unknown: [] };
    active.forEach(h => groups[styleOf(h)].push(h));
    return groups;
  }, [active]);
  const paceKnown = active.length - pace.unknown.length;

  return (
    <section className={styles.root} aria-labelledby="fi-title">
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}><BarChart3 size={13} aria-hidden /> FURLONGIQ / RACE INTELLIGENCE</p>
          <h2 id="fi-title">{r.time} {r.course} · Compare the field</h2>
          <p>{r.name} · {r.distance} · {r.going || "Going not listed"}{r.race_class ? ` · ${r.race_class}` : ""}</p>
        </div>
        <div className={styles.headerSide}>
          <span className={styles.coverage}><strong>{ratedCount}/{active.length}</strong> runners with speed predictions</span>
          <a href="#full-racecard">Original racecard <ChevronDown size={13} aria-hidden /></a>
        </div>
      </header>

      <div className={styles.insights}>
        <a className={styles.insight} href={leaders.pred ? `#r-${leaders.pred.ride_id}` : "#fi-table"}>
          <span><Target size={15} aria-hidden /> Highest predicted speed</span>
          <strong>{leaders.pred?.horse ?? "No prediction"}</strong>
          <div><b>{fmt(leaders.pred?.pred)}</b><small>{juv ? "2yo figure" : "Today’s predicted figure"}</small></div>
        </a>
        <a className={styles.insight} href={leaders.last ? `#r-${leaders.last.ride_id}` : "#fi-table"}>
          <span><TrendingUp size={15} aria-hidden /> Highest last rated figure</span>
          <strong>{leaders.last?.horse ?? "No recent figure"}</strong>
          <div><b>{fmt(leaders.last ? lastRated(leaders.last, juv) : null)}</b><small>Recorded performance, not forecast</small></div>
        </a>
        <a className={styles.insight} href={leaders.conditions ? `#r-${leaders.conditions.ride_id}` : "#fi-table"}>
          <span><Check size={15} aria-hidden /> Best proven similar conditions</span>
          <strong>{leaders.conditions?.horse ?? "No matching figure"}</strong>
          <div><b>{fmt(leaders.conditions?.cond_best?.fig)}</b>
            <small>{leaders.conditions?.cond_best ? `${leaders.conditions.cond_best.n} matched historical run(s)` : "No documented match"}</small></div>
        </a>
      </div>

      <div className={styles.alerts} role="note">
        {ratedCount < active.length && <span><ShieldAlert size={14} aria-hidden /> {active.length - ratedCount} runner(s) have no speed prediction: rankings are incomplete.</span>}
        {modelDisagrees && <span><Info size={14} aria-hidden /> Speed leader and win-% leader differ. View these as separate model outputs.</span>}
        <span><Info size={14} aria-hidden /> The rating range is a model error band, not a guaranteed outcome or individual-horse confidence interval.</span>
      </div>

      <div className={styles.pacePanel}>
        <div className={styles.paceIntro}>
          <div>
            <h3><Clock3 size={15} aria-hidden /> Historical running styles</h3>
            <p>Most recent measured sectional style; an indication, <strong>not a prediction</strong> of today's pace.</p>
          </div>
          <Link href={`/race/${r.race_id}/sectionals`}>Open sectional analysis <ArrowUpRight size={14} aria-hidden /></Link>
        </div>
        <div className={styles.paceGrid}>
          {(["front", "prom", "mid", "rear"] as const).map(key => (
            <div className={styles.paceBox} key={key}>
              <span>{STYLE[key]} <b>{pace[key].length}</b></span>
              <p title={pace[key].map(h => h.horse).join(", ")}>{pace[key].length ? pace[key].map(h => h.horse).join(" · ") : "No recorded runners"}</p>
            </div>
          ))}
        </div>
        <p className={styles.footnote}>
          {paceKnown}/{active.length} runners have recorded style data.
          {pace.front.length >= 2 ? " Several have previously led; a contested pace is possible, but not established." : ""}
          {paceKnown < Math.ceil(active.length / 2) ? " Pace evidence is incomplete, so no race-shape conclusion is justified." : ""}
        </p>
      </div>

      <div className={styles.tableHead} id="fi-table">
        <div>
          <h3><ArrowDownWideNarrow size={15} aria-hidden /> All runners</h3>
          <p>Form chips show results newest → oldest. Click Quick form for context, or select up to three horses to compare.</p>
        </div>
        <div className={styles.controls}>
          <label className={styles.search}><Search size={14} aria-hidden /><span className={styles.sr}>Search horse</span>
            <input type="search" placeholder="Find horse…" value={query} onChange={e => setQuery(e.target.value)} />
          </label>
          <label className={styles.sort}><span>Sort</span><select value={sort} onChange={e => setSort(e.target.value as SortKey)}>
            {(Object.keys(SORT_LABEL) as SortKey[]).map(key => <option key={key} value={key}>{SORT_LABEL[key]}</option>)}
          </select></label>
          <label className={styles.toggle}><input type="checkbox" checked={showNr} onChange={e => setShowNr(e.target.checked)} /> Show NRs</label>
        </div>
      </div>
      <p className={styles.scrollHint}>On smaller screens, scroll the table sideways for all measures.</p>
      <div className={styles.tableScroll} role="region" aria-label="Sortable race runners comparison" tabIndex={0}>
        <table className={styles.table}>
          <thead><tr>
            <th scope="col">#</th><th scope="col">Runner / recent results</th><th scope="col">Predicted</th>
            <th scope="col">Last speed</th><th scope="col">Best 3</th><th scope="col">Similar conditions</th>
            <th scope="col">Last pace style</th><th scope="col">Win %</th><th scope="col">Evidence</th><th scope="col">Inspect</th>
          </tr></thead>
          <tbody>
            {rows.map(h => {
              const e = evidence(h, juv);
              const st = styleOf(h);
              const checkedH = selected.includes(h.ride_id);
              return <tr key={h.ride_id} className={`${checkedH ? styles.chosen : ""} ${h.nr ? styles.nonrunner : ""}`}>
                <td className={styles.numeric}>{h.cloth ?? "—"}</td>
                <td className={styles.horse}>
                  <a href={`#r-${h.ride_id}`}>{h.horse}</a>
                  {h.nr && <span className={styles.nr}>NR</span>}
                  <MiniForm h={h} />
                </td>
                <td className={`${styles.numeric} ${h.rank === 1 ? styles.topPred : ""}`}>
                  <strong>{fmt(h.pred)}</strong>
                  {h.pred_lo != null && h.pred_hi != null && h.pred_hi > h.pred_lo && h.pred != null && (
                    <small title="Model's published typical error band">{fmt(h.pred_lo)}–{fmt(h.pred_hi)}</small>
                  )}
                </td>
                <td className={styles.numeric}>{fmt(lastRated(h, juv))}</td>
                <td className={styles.numeric}>{fmt(best3(h, juv))}</td>
                <td className={styles.numeric}>
                  <strong>{fmt(h.cond_best?.fig)}</strong>
                  <small>{e.matched > 0 ? `${e.matched} historical match${e.matched === 1 ? "" : "es"}` : "No verified match"}</small>
                </td>
                <td><span className={st === "unknown" ? styles.na : styles.stylePill}>{STYLE[st]}</span></td>
                <td className={styles.numeric}><strong>{h.win_pct == null ? "—" : `${fmt(h.win_pct)}%`}</strong>
                  {h.fair_odds != null && <small>Fair {fmt(h.fair_odds, 2)}</small>}</td>
                <td className={styles.evidence}>
                  <span>{e.count} {juv ? "visible 2yo figures" : "rated runs"}</span>
                  {e.points.length ? <small title={e.points.join("; ")} className={styles.warning}>{e.points[0]}{e.points.length > 1 ? ` +${e.points.length - 1}` : ""}</small> : <small className={styles.good}>Matched data available</small>}
                </td>
                <td className={styles.actions}>
                  <button type="button" onClick={() => setQuickId(quickId === h.ride_id ? null : h.ride_id)}
                    aria-pressed={quickId === h.ride_id} aria-label={`Quick form for ${h.horse}`}>
                    Form
                  </button>
                  <button type="button" disabled={h.nr || (!checkedH && selected.length >= 3)}
                    onClick={() => toggle(h.ride_id)} aria-pressed={checkedH} aria-label={`${checkedH ? "Remove" : "Compare"} ${h.horse}`}>
                    <GitCompareArrows size={13} aria-hidden /> {checkedH ? "Selected" : "Compare"}
                  </button>
                </td>
              </tr>;
            })}
          </tbody>
        </table>
        {rows.length === 0 && <p className={styles.noRows}>No horses match that search.</p>}
      </div>
      <p className={styles.footnote}>
        Predicted, last and best-three figures are separate measures. A matching-condition figure is a historical best using the existing
        FurlongIQ tolerance rules, not a guaranteed repeat. Win % is a separate model estimate and should not be interpreted as a verified probability without calibration results.
      </p>

      {currentQuick && <QuickForm h={currentQuick} juv={juv} onClose={() => setQuickId(null)} />}

      <section className={styles.compare} aria-label="Compare selected runners">
        <div className={styles.compareHead}>
          <div><h3><GitCompareArrows size={16} aria-hidden /> Horse comparison</h3>
            <p>{checked.length ? `${checked.length}/3 selected · ${checked.length < 2 ? "Choose at least one more runner" : "Historical and model data side by side"}` : "Select two or three runners using the comparison table above."}</p>
          </div>
          {checked.length > 0 && <button type="button" onClick={() => setSelected([])}>Clear selection</button>}
        </div>
        {checked.length >= 2 && (
          <div className={styles.tableScroll} role="region" aria-label="Selected horse comparison" tabIndex={0}>
            <table className={styles.duelTable}>
              <thead><tr><th scope="col">Measure</th>{checked.map(h => <th key={h.ride_id} scope="col"><a href={`#r-${h.ride_id}`}>{h.horse}</a></th>)}</tr></thead>
              <tbody>
                {([
                  ["Predicted today", (h: Runner) => fmt(h.pred)],
                  ["Predicted range", (h: Runner) => h.pred_lo == null || h.pred_hi == null || h.pred_hi <= h.pred_lo ? "—" : `${fmt(h.pred_lo)}–${fmt(h.pred_hi)}`],
                  ["Last rated speed", (h: Runner) => fmt(lastRated(h, juv))],
                  ["Average best 3", (h: Runner) => fmt(best3(h, juv))],
                  ["Best similar conditions", (h: Runner) => fmt(h.cond_best?.fig)],
                  ["Similar-condition runs", (h: Runner) => String(h.cond_best?.n ?? 0)],
                  ["Model win estimate", (h: Runner) => h.win_pct == null ? "—" : `${fmt(h.win_pct, 1)}%`],
                  ["Latest recorded running style", (h: Runner) => STYLE[styleOf(h)]],
                  ["Days since run", (h: Runner) => h.last_ran_days == null ? "—" : String(h.last_ran_days)],
                  [juv ? "Visible 2yo figures" : "Speed figures available", (h: Runner) => String(evidence(h, juv).count)],
                  ["Last five results", (h: Runner) => h.form_runs.slice(0, 5).map(f => f.pos || "–").join(" · ") || "—"],
                ] as [string, (h: Runner) => string][]).map(([label, fn]) => (
                  <tr key={label}><th scope="row">{label}</th>{checked.map(h => <td key={h.ride_id}>{fn(h)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
