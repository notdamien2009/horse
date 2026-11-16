"use client";
import {
  ArrowDownWideNarrow, ChevronDown, ChevronsDownUp, ChevronsUpDown, Crown, Gauge, ListOrdered, Lock, Timer, TrendingUp,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { Race, Runner, FormRun, Conditions, ClassChange } from "@/lib/racing";
import { ChartLegend, FigChart, FitTags, TrendBadge, chartRuns, runVal, trendOf } from "./FigChart";
import { f0, hueStyle, rankHue, scaleHue, type HueFn } from "@/lib/colours";

const SEC_KEYS = ["last", "avg3", "best", "best2yo"] as const;
const SEC_LABEL: Record<(typeof SEC_KEYS)[number], [string, string]> = {
  last: ["Last", "Most recent figure"],
  avg3: ["Avg 3", "Average of the last 3 figures"],
  best: ["Best", "Best ever figure"],
  best2yo: ["2yo", "Best figure on the 2yo scale"],
};

const fmtDate = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const shortGoing = (g: string | null) =>
  (g ?? "").replace(/\s*\(.*\)/, "").replace("Good to ", "Gd/").replace("Standard", "Std");
const SEX: Record<string, string> = { g: "gelding", m: "mare", f: "filly", c: "colt", h: "horse", r: "rig" };

/** win = green, placed (2nd/3rd) = amber, fall / pulled up etc. = red, others neutral */
function posClass(p: string): string {
  if (p === "1") return "p-win";
  if (p === "2" || p === "3") return "p-place";
  if (/^[A-Z]/i.test(p)) return "p-bad";
  return "p-out";
}

function HeatPill({ v, hue, label, title }: { v: number | null | undefined; hue: number | null; label?: string; title?: string }) {
  return (
    <span className={`pill-h${v == null ? " na" : ""}`} style={hueStyle(hue)} title={title}>
      {label && <small>{label}</small>}
      <b>{v == null ? "–" : f0(v)}</b>
    </span>
  );
}

function Silk({ x }: { x: Runner }) {
  const [bad, setBad] = useState(false);
  const initials = String(x.horse ?? "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w: string) => w[0]).join("").toUpperCase();
  if (x.silk && !bad) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img className="silk" src={`https://www.sportinglife.com/images/silks/${x.silk}`} alt="" loading="lazy"
        onError={() => setBad(true)} />
    );
  }
  return <span className="silk silk-i" aria-hidden>{initials}</span>;
}

function FormChips({ form }: { form: string | null }) {
  const s = String(form ?? "").trim();
  if (!s) return <span className="muted small">no form</span>;
  const chars = s.split("").slice(-8);
  return (
    <span className="fchips" aria-label={`Form ${s}`} title={`Form: ${s} (most recent on the right)`}>
      {chars.map((c, i) => c === "-" || c === "/" ? <span key={i} className="fsep">{c === "/" ? "/" : ""}</span>
        : <span key={i} className={`fchip ${posClass(c === "0" ? "10" : c)}`}>{c}</span>)}
    </span>
  );
}

export function RaceCard({ race: r }: { race: Race }) {
  const [sort, setSort] = useState<"rank" | "card">("rank");
  const [open, setOpen] = useState<Set<number>>(() => new Set());
  const juv = r.rank_basis.startsWith("2yo");
  const head = (h: Runner) => h.pred;
  const b3of = (h: Runner) => (juv ? h.ratings.best3_2yo : h.ratings.best3 ?? h.ratings.best);

  const m = useMemo(() => {
    const act = r.runners.filter((h) => !h.nr);
    const headHue = rankHue(act.map(head));
    const b3Hue = rankHue(act.map(b3of));
    const hues = Object.fromEntries(SEC_KEYS.map((k) => [k, rankHue(act.map((h) => h.ratings[k]))])) as Record<(typeof SEC_KEYS)[number], HueFn>;
    const hv = act.map(head).filter((v): v is number => v != null);
    const top = hv.length ? Math.max(...hv) : null;
    const low = hv.length ? Math.min(...hv) : 0;
    const barLo = top == null ? 0 : Math.min(low, top - 10) - 8; // bar baseline so the weakest still shows
    const b3 = act.map((h) => h.ratings.best3).filter((v): v is number => v != null);
    const runHue = b3.length ? scaleHue(Math.min(...b3) - 15, Math.max(...b3)) : scaleHue(0, null);
    // sparkline scale shared by the race: from ~25 below the weakest rating up to the best single run
    const allRuns = act.flatMap((h) => h.form_runs.map((f) => f.fig)).filter((v): v is number => v != null);
    const sHi = allRuns.length ? Math.max(...allRuns) : 1;
    const sLo = Math.max(allRuns.length ? Math.min(...allRuns) : 0, (hv.length ? Math.min(...hv) : sHi) - 25);
    const ranked = act.filter((h) => h.rank).sort((a, b) => a.rank! - b.rank!);
    const gap = ranked.length > 1 && head(ranked[0]) != null && head(ranked[1]) != null ? Math.round(head(ranked[0])! - head(ranked[1])!) : null;
    const unrated = act.filter((h) => !h.rank);
    const show2 = act.some((h) => h.ratings.best2yo != null);
    // trend-chart scale shared by the whole race (so charts compare horse to horse): ~25 below the weakest rating up to the best run
    const cv = act.flatMap((h) => h.form_runs.slice(0, 8).map((f) => runVal(f, juv))).filter((v): v is number => v != null);
    const cMax = Math.max(cv.length ? Math.max(...cv) : 0, top ?? 0);
    const cLo = Math.floor(Math.max(cv.length ? Math.min(...cv) : cMax - 40, (hv.length ? low : cMax) - 25) - 4);
    const cHi = Math.ceil(cMax + 5);
    const chartHue = hv.length ? scaleHue(low - 15, top) : runHue;
    return { headHue, b3Hue, hues, top, barLo, runHue, sLo, sHi, ranked, gap, unrated, show2, cLo, cHi, chartHue };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [r]);

  const list = sort === "rank"
    ? [...r.runners].sort((a, b) => Number(a.nr) - Number(b.nr) || (a.rank ?? 99) - (b.rank ?? 99) || (a.cloth ?? 0) - (b.cloth ?? 0))
    : r.runners;
  const allOpen = open.size > 0 && open.size >= r.runners.filter((h) => !h.nr).length;
  const toggle = (id: number) => setOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const setAll = () => setOpen(allOpen ? new Set() : new Set(r.runners.filter((h) => !h.nr).map((h) => h.ride_id)));
  const pct = (v: number | null) => (v == null || m.top == null ? 0 : Math.max(4, Math.min(100, ((v - m.barLo) / Math.max(1, m.top - m.barLo)) * 100)));
  const leader = m.ranked[0];
  const dateLabel = new Date(r.date + "T12:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="race">
      <section className="hero">
        <div className="hero-head">
          <div className="hero-time"><span>{r.time}</span></div>
          <div className="hero-title">
            <div className="hero-course">{r.course} <span>· {dateLabel}</span></div>
            <h1>{r.name}</h1>
          </div>
        </div>
        <div className="facts">
          {r.race_class && <span className="fact"><small>Class</small><b>{r.race_class}</b></span>}
          <span className="fact"><small>Distance</small><b>{r.distance}</b></span>
          <span className="fact going"><small>Going</small><b>{r.going || "–"}</b></span>
          <span className="fact"><small>Type</small><b>{r.family}{r.handicap ? " handicap" : ""}</b></span>
          {r.age_band && <span className="fact"><small>Age</small><b>{r.age_band}</b></span>}
          <span className="fact"><small>Runners</small><b>{r.active}</b></span>
          <span className={`fact${r.rated < r.active ? " warn" : ""}`}><small>With figures</small><b>{r.rated}/{r.active}</b></span>
        </div>

        <div className="hero-grid">
          <div className="glance">
            <div className="sec-title"><Gauge size={15} aria-hidden /> Ratings at a glance <span>{juv ? "2yo scale · predicted figure for today" : "Predicted today · the figure we think each horse will run"}</span></div>
            {m.ranked.length ? (
              <ol className="gbars">
                {m.ranked.map((h, i) => {
                  const v = head(h);
                  return (
                    <li key={h.ride_id} style={{ ...hueStyle(m.headHue(v)), animationDelay: `${i * 35}ms` }}>
                      <a href={`#r-${h.ride_id}`} className="gbar-row">
                        <span className="gbar-rank">{h.rank}</span>
                        <span className="gbar-name">{h.horse}</span>
                        <span className="gbar-track"><span className="gbar-fill" style={{ width: `${pct(v)}%` }} /></span>
                        <span className="gbar-val heat">{f0(v)}</span>
                      </a>
                    </li>
                  );
                })}
              </ol>
            ) : <div className="muted small">No runner has a figure yet.</div>}
            {m.unrated.length > 0 && (
              <div className="unrated">No figures: {m.unrated.map((h) => h.horse).join(", ")}</div>
            )}
          </div>

          <div className="hero-side">
            {leader ? (
              <a className="leader" href={`#r-${leader.ride_id}`}>
                <span className="leader-tag"><Crown size={13} aria-hidden /> TOP RATED</span>
                <span className="leader-name">{leader.horse}</span>
                <span className="leader-sub">{leader.jockey || ""}{leader.trainer ? ` · ${leader.trainer}` : ""}</span>
                <span className="leader-nums">
                  <span className="leader-fig">{f0(head(leader))}</span>
                  {m.gap != null && <span className={`clear${m.gap >= 5 ? " wide" : ""}`}>{m.gap > 0 ? `+${m.gap} clear` : "joint top"}</span>}
                  {(leader.odds || leader.forecast_odds) && <span className="leader-odds">{leader.odds || leader.forecast_odds}</span>}
                </span>
              </a>
            ) : <div className="leader none">No ratings for this race yet.</div>}
            {r.verdict && <div className="verdict"><b>Sporting Life verdict</b><p>{r.verdict}</p></div>}
          </div>
        </div>
      </section>

      <div className="toolbar">
        <div className="seg" role="group" aria-label="Sort runners">
          <button type="button" className={sort === "rank" ? "on" : ""} aria-pressed={sort === "rank"} onClick={() => setSort("rank")}>
            <ArrowDownWideNarrow size={14} aria-hidden /> By rating
          </button>
          <button type="button" className={sort === "card" ? "on" : ""} aria-pressed={sort === "card"} onClick={() => setSort("card")}>
            <ListOrdered size={14} aria-hidden /> Card order
          </button>
        </div>
        <span className="legend hide-sm">worst <i aria-hidden /> best</span>
        <div className="chart-key">
          <span className="today-cond" title="A past run counts as 'today's conditions' when all of these match">
            <b>◎ Today&apos;s conditions:</b> {condText(r.cond, r.distance, r.going)}
          </span>
          <ChartLegend refLabel={juv ? "top 2yo predicted" : "top predicted"} />
        </div>
        <button type="button" className="ghost" onClick={setAll}>
          {allOpen ? <><ChevronsDownUp size={14} aria-hidden /> Collapse all form</> : <><ChevronsUpDown size={14} aria-hidden /> Expand all form</>}
        </button>
      </div>

      <div className="runners">
        {list.map((x, i) => (
          <RunnerCard key={x.ride_id} x={x} i={i} head={head(x)} b3={b3of(x)} juv={juv} m={m} pct={pct}
            isOpen={open.has(x.ride_id)} onToggle={() => toggle(x.ride_id)} cond={r.cond} />
        ))}
      </div>

      <div className="soon">
        <div className="soon-card">
          <TrendingUp size={18} aria-hidden />
          <div><b>Odds &amp; trading analysis</b><span>Needs backtesting first.</span></div>
          <span className="soon-tag"><Lock size={11} aria-hidden /> Coming soon</span>
        </div>
        <div className="soon-card">
          <Timer size={18} aria-hidden />
          <div><b>Sectionals</b><span>Once the sectional data is scraped.</span></div>
          <span className="soon-tag"><Lock size={11} aria-hidden /> Coming soon</span>
        </div>
      </div>
    </div>
  );
}

type M = {
  headHue: HueFn; b3Hue: HueFn; hues: Record<(typeof SEC_KEYS)[number], HueFn>; top: number | null; runHue: HueFn;
  sLo: number; sHi: number; gap: number | null; show2: boolean; cLo: number; cHi: number; chartHue: HueFn;
};


function ClassBadge({ c }: { c: ClassChange | null }) {
  if (!c) return null;
  const lastTxt = c.last != null ? `Last run: Class ${c.last}.` : "Last run class unknown.";
  const avgTxt = c.avg != null ? ` Average of last ${c.n} run${c.n === 1 ? "" : "s"} with a class: Class ${c.avg}.` : "";
  const why = c.dir === "drop"
    ? " Dropping in class — today's race is easier than recent runs."
    : " Stepping up in class — today's race is tougher than recent runs.";
  return (
    <span className={`cls-flag ${c.dir}`}
      title={`Today Class ${c.today}. ${lastTxt}${avgTxt}${why} Class 1 is the highest grade; Class 6/7 is the lowest.`}>
      {c.dir === "drop" ? "Class drop ▼" : "Class rise ▲"}
    </span>
  );
}

/** "Hurdle · 2m 4f 116y ±1f · Good to Soft ±1 step · Class 4 ±1" */
function condText(c: Conditions, dist: string, going: string | null): string {
  const tol = c.dist_f == null ? "" : ` ±${Math.max(1, c.dist_f * 0.1).toFixed(c.dist_f * 0.1 > 1 ? 1 : 0)}f`;
  return [
    c.code === "AW" ? "AW Flat" : c.code,
    `${dist}${tol}`,
    c.aw ? "all-weather" : `${String(going ?? "").replace(/\s*\(.*\)/, "") || "going ?"} ±1 step`,
    c.cls_n ? `Class ${c.cls_n} ±1` : "any class",
  ].join(" · ");
}

function RunnerCard({ x, i, head, b3, juv, m, pct, isOpen, onToggle, cond }: {
  x: Runner; i: number; head: number | null; b3: number | null; juv: boolean; m: M; pct: (v: number | null) => number; isOpen: boolean; onToggle: () => void;
  cond: Conditions;
}) {
  const trend = useMemo(() => trendOf(chartRuns(x.form_runs, juv), cond), [x.form_runs, juv, cond]);
  const refLabel = juv ? "top 2yo pred" : "top predicted";
  const cb = x.cond_best;
  const top = x.rank === 1, rt = x.ratings;
  const hue = m.headHue(head);
  const behind = head != null && m.top != null ? Math.round(m.top - head) : null;
  const odds = x.odds || x.forecast_odds || "";
  const keys = SEC_KEYS.filter((k) => k !== "best2yo" || (m.show2 && (juv || rt.best2yo != null)));
  const panelId = `form-${x.ride_id}`;
  return (
    <article id={`r-${x.ride_id}`} className={`runner${top ? " top" : ""}${x.nr ? " nr" : ""}${isOpen ? " open" : ""}`}
      style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
      <div className="rmain" onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button")) onToggle(); }}>
        <div className="c-rank">
          {x.rank ? <span className="rank-badge" style={hueStyle(m.headHue(head))}>{x.rank}</span> : <span className="rank-badge na">–</span>}
        </div>
        <div className="c-cloth">
          <span className="cloth">{x.cloth ?? ""}</span>
          {x.draw ? <span className="draw" title="Stall / draw">({x.draw})</span> : null}
        </div>
        <div className="c-silk"><Silk x={x} /></div>
        <div className="c-id">
          <div className="hname-row">
            <span className="hname">{x.horse}</span>
            {top && <span className="badge-top"><Crown size={11} aria-hidden /> TOP RATED</span>}
            {x.headgear && <span className="hg" title="Headgear (1 = first time)">{x.headgear}</span>}
            {x.nr && <span className="badge-nr">NON-RUNNER</span>}
          </div>
          <div className="hmeta">
            <span>{x.age ?? ""}yo {SEX[String(x.sex ?? "").toLowerCase()] ?? x.sex ?? ""}</span>
            {x.weight && <span>{x.weight}</span>}
            <span>OR <b>{x.official_rating ?? "–"}</b>{x.or_delta != null && (
              <em className={`or-delta ${x.or_delta < 0 ? "down" : "up"}`}
                title={`Official rating ${x.or_delta < 0 ? "down" : "up"} ${Math.abs(x.or_delta)} lb since last run in this discipline`}>
                {x.or_delta > 0 ? `+${x.or_delta}` : x.or_delta}
              </em>
            )}</span>
            {x.last_ran_days != null && <span title="Days since last run">{x.last_ran_days}d</span>}
          </div>
          <div className="hpeople">
            <span title="Jockey"><i>J</i>{x.jockey || "–"}{x.jockey_claim ? <em> ({x.jockey_claim})</em> : null}</span>
            <span title="Trainer"><i>T</i>{x.trainer || "–"}</span>
          </div>
        </div>
        <div className="c-form">
          <div className="form-top">
            <FormChips form={x.form} />
            <span className="rec">{x.runs ?? 0} runs · <b>{x.wins ?? 0}</b>W {x.places ?? 0}P</span>
          </div>
          <div className="form-tags">
            <TrendBadge t={trend} />
            <ClassBadge c={x.class_change} />
            {cb && (
              <span className="pill-h cond-best" style={hueStyle(m.chartHue(cb.fig))}
                title={`Best figure at today's conditions: ${f0(cb.fig)} at ${cb.course} on ${fmtDate(cb.date)} (${cb.n} run${cb.n === 1 ? "" : "s"} at these conditions)`}>
                <small>◎ Today&apos;s cond.</small><b>{f0(cb.fig)}</b><small className="cb-n">{cb.n}×</small>
              </span>
            )}
          </div>
          <FigChart runs={x.form_runs} juv={juv} lo={m.cLo} hi={m.cHi} hue={m.chartHue} refV={m.top} refLabel={refLabel}
            today={cond} trend={trend} />
        </div>
        <div className="c-rating" style={hueStyle(hue)}>
          <div className="headline">
            <div className="hl-num">
              <small>{juv ? "2yo predicted" : "Predicted today"}</small>
              <span className={`big heat${head == null ? " na" : ""}`}>{head == null ? "–" : f0(head)}</span>
              {head != null && x.pred_lo != null && x.pred_hi != null && (
                <span className="pred-band" title={`Typical error band on unseen races: ${f0(x.pred_lo)} to ${f0(x.pred_hi)}`}>
                  {f0(x.pred_lo)}–{f0(x.pred_hi)}
                </span>
              )}
            </div>
            <div className="hl-bar">
              <span className="track"><span className="fill" style={{ width: `${pct(head)}%` }} /></span>
              <span className="gapnote">
                {head == null ? "no figures yet" : top && m.gap != null ? (
                  <span className={`clear${m.gap >= 5 ? " wide" : ""}`}>{m.gap > 0 ? `+${m.gap} clear` : "joint top"}</span>
                ) : behind != null ? (behind === 0 ? "joint top" : `−${behind} off top`) : ""}
              </span>
            </div>
          </div>
          <div className="secs">
            <HeatPill v={b3} hue={m.b3Hue(b3)} label={juv ? "2yo B3" : "Best 3"}
              title={juv ? "Average of the best 3 figures on the 2yo scale from the last 12 runs" : "Average of the best 3 figures from the last 12 runs (same discipline)"} />
            {keys.map((k) => (
              <HeatPill key={k} v={rt[k]} hue={m.hues[k](rt[k])} label={SEC_LABEL[k][0]} title={SEC_LABEL[k][1]} />
            ))}
          </div>
        </div>
        <div className="c-odds">
          <span className="odds">{odds || "–"}</span>
          <small>{x.odds ? "odds" : x.forecast_odds ? "forecast" : ""}</small>
        </div>
        <div className="c-exp">
          <button type="button" className="exp-btn" aria-expanded={isOpen} aria-controls={panelId} onClick={onToggle}
            title={isOpen ? "Hide form" : "Show form"}>
            <ChevronDown size={18} aria-hidden />
            <span className="sr">{isOpen ? "Hide" : "Show"} form for {x.horse}</span>
          </button>
        </div>
      </div>
      {isOpen && (
        <div className="rform" id={panelId}>
          {x.commentary && <p className="spotlight"><b>Spotlight</b> {x.commentary}</p>}
          <div className="bigchart">
            <div className="bigchart-head">
              <span className="sec-title"><TrendingUp size={14} aria-hidden /> Speed figures, last {Math.min(8, x.form_runs.length)} runs</span>
              <TrendBadge t={trend} />
              <ClassBadge c={x.class_change} />
              {cb ? (
                <span className="pill-h cond-best" style={hueStyle(m.chartHue(cb.fig))}>
                  <small>◎ Best at today&apos;s conditions</small><b>{f0(cb.fig)}</b>
                  <small className="cb-n">{cb.course} {fmtDate(cb.date)} · {cb.n} run{cb.n === 1 ? "" : "s"}</small>
                </span>
              ) : <span className="muted small">No figure yet at today&apos;s conditions</span>}
              <ChartLegend refLabel={juv ? "top 2yo predicted in this race" : "top predicted in this race"} />
            </div>
            <FigChart runs={x.form_runs} juv={juv} lo={m.cLo} hi={m.cHi} hue={m.chartHue} refV={m.top}
              refLabel={refLabel} today={cond} trend={trend} size="lg" />
          </div>
          <FormTable runs={x.form_runs} hue={m.chartHue} juv={juv} />
        </div>
      )}
    </article>
  );
}

function FormTable({ runs, hue, juv }: { runs: FormRun[]; hue: HueFn; juv: boolean }) {
  if (!runs?.length) return <div className="muted small">No previous runs.</div>;
  return (
    <div className="runs-wrap">
      <table className="runs">
        <thead>
          <tr>
            <th>Date</th><th>Course</th><th>Dist</th><th>Going</th><th>Type</th><th className="n">Cl</th>
            <th className="n">Pos</th><th className="n">Btn</th><th className="n">SP</th><th className="n">OR</th>
            <th className="n" title={juv ? "Figure on the 2yo scale (as in the chart)" : undefined}>{juv ? "2yo Fig" : "Fig"}</th><th>vs today</th><th>Comment</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((f, i) => (
            <tr key={i} className={f.fit.all ? "cond" : undefined}>
              <td className="d">{fmtDate(f.date)}</td>
              <td className="crs">{f.course}</td>
              <td>{f.dist}</td>
              <td>{shortGoing(f.going)}</td>
              <td>{f.type}</td>
              <td className="n">{f.cls}</td>
              <td className="n"><span className={`pos ${posClass(f.pos)}`}>{f.pos || "–"}{f.ran ? <small>/{f.ran}</small> : null}</span></td>
              <td className="n">{f.btn == null ? "" : f.pos === "1" ? "–" : f.btn}</td>
              <td className="n">{f.sp || ""}</td>
              <td className="n">{f.or ?? ""}</td>
              <td className="n"><HeatPill v={runVal(f, juv)} hue={hue(runVal(f, juv))}
                title={juv && f.fig != null ? `All-age figure ${f0(f.fig)}` : undefined} /></td>
              <td><FitTags f={f} compact /></td>
              <td className="cmt" title={f.comment || ""}><div>{f.comment || ""}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
