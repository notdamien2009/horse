"use client";
import { ArrowDownWideNarrow, ListOrdered, Rows3, Rows4 } from "lucide-react";
import { useMemo, useState } from "react";
import type { Race, Runner, FormRun } from "@/lib/racing";
import { f0, rankColours, scaleColour, type ColourFn } from "@/lib/colours";

const FIG_KEYS = ["last", "best", "best3", "avg3", "best2yo", "best3_2yo"] as const;

function Fig({ v, col }: { v: number | null | undefined; col: ColourFn }) {
  if (v == null) return <span className="fig na">–</span>;
  return <span className="fig" style={{ background: col(v) ?? undefined }}>{f0(v)}</span>;
}

const fmtDate = (d: string) =>
  new Date(d + "T12:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "2-digit" });
const shortGoing = (g: string | null) =>
  (g ?? "").replace(/\s*\(.*\)/, "").replace("Good to ", "Gd/").replace("Standard", "Std");

export function RaceCard({ race: r }: { race: Race }) {
  const [sort, setSort] = useState<"card" | "rank">("card");
  const [showForm, setShowForm] = useState(true);

  const { cols, rankCol, runCol, show2, ranked } = useMemo(() => {
    const act = r.runners.filter((h) => !h.nr);
    const cols = Object.fromEntries(FIG_KEYS.map((k) => [k, rankColours(act.map((h) => h.ratings[k]))])) as Record<(typeof FIG_KEYS)[number], ColourFn>;
    const rankCol = rankColours(act.map((h) => (h.rank == null ? null : -h.rank)));
    const b3 = act.map((h) => h.ratings.best3).filter((v): v is number => v != null);
    const runCol = b3.length ? scaleColour(Math.min(...b3) - 15, Math.max(...b3)) : scaleColour(0, null);
    const show2 = act.some((h) => h.ratings.best2yo != null);
    const ranked = act.filter((h) => h.rank).sort((a, b) => a.rank! - b.rank!);
    return { cols, rankCol, runCol, show2, ranked };
  }, [r]);

  const list = sort === "rank"
    ? [...r.runners].sort((a, b) => Number(a.nr) - Number(b.nr) || (a.rank ?? 99) - (b.rank ?? 99))
    : r.runners;
  const juv = r.rank_basis.startsWith("2yo");
  const ncols = show2 ? 15 : 13;

  return (
    <>
      <div className="rhead">
        <h1>{r.time} {r.course} — {r.name}</h1>
        <div className="facts">
          <span>Class <b>{r.race_class || "-"}</b></span>
          <span>Distance <b>{r.distance}</b></span>
          <span>Going <b>{r.going}</b></span>
          <span>Type <b>{r.family}{r.handicap ? " handicap" : ""}</b></span>
          <span>Age <b>{r.age_band || ""}</b></span>
          <span>Runners <b>{r.active}</b></span>
          <span>With figures <b>{r.rated}/{r.active}</b></span>
        </div>
        {ranked.length > 0 && (
          <div className="ranking">
            <span className="muted" style={{ alignSelf: "center" }}>Figure ranking ({r.rank_basis}):</span>
            {ranked.map((x) => (
              <span key={x.ride_id} className="chip" style={{ background: rankCol(-x.rank!) ?? undefined }}>
                {x.rank}. {x.horse} {f0(juv ? x.ratings.best3_2yo : x.ratings.best3)}
              </span>
            ))}
          </div>
        )}
        {r.verdict && <div className="verdict"><b>SL verdict:</b> {r.verdict}</div>}
      </div>

      <div className="tools">
        <span className="legend">worst <i /> best</span>
        <button onClick={() => setSort(sort === "card" ? "rank" : "card")}>
          {sort === "card" ? <><ArrowDownWideNarrow size={14} /> Sort by rating</> : <><ListOrdered size={14} /> Sort by card no.</>}
        </button>
        <button onClick={() => setShowForm(!showForm)}>
          {showForm ? <><Rows3 size={14} /> Hide form</> : <><Rows4 size={14} /> Show form</>}
        </button>
      </div>

      <div className="wrap">
        <table className="card">
          <thead>
            <tr>
              <th>Rank</th><th>No (Dr)</th><th>Horse</th><th>Form</th><th>Age</th><th>Wgt</th><th>OR</th>
              <th>Jockey / Trainer</th><th>Odds</th>
              <th className="num" title="Most recent figure">Last</th>
              <th className="num" title="Best-3 of last 12 runs (ranking basis)">Best 3</th>
              <th className="num" title="Average of last 3 figures">Avg 3</th>
              <th className="num" title="Best ever figure">Best</th>
              {show2 && <><th className="num" title="2yo scale: best-3 average">2yo B3</th><th className="num" title="2yo scale: best">2yo Best</th></>}
            </tr>
          </thead>
          <tbody>
            {list.map((x) => (
              <RunnerRows key={x.ride_id} x={x} cols={cols} rankCol={rankCol} runCol={runCol}
                show2={show2} showForm={showForm} ncols={ncols} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="soon">
        <div><b>Odds &amp; trading analysis</b>Coming later – needs backtesting first.</div>
        <div><b>Sectionals</b>Coming later – once the sectional data is scraped.</div>
      </div>
    </>
  );
}

function RunnerRows({ x, cols, rankCol, runCol, show2, showForm, ncols }: {
  x: Runner; cols: Record<string, ColourFn>; rankCol: ColourFn; runCol: ColourFn; show2: boolean; showForm: boolean; ncols: number;
}) {
  const top = x.rank === 1, rt = x.ratings;
  return (
    <>
      <tr className={`runner${top ? " top" : ""}${x.nr ? " nr" : ""}`}>
        <td className="num">{x.rank ? <span className="rank" style={{ background: rankCol(-x.rank) ?? undefined }}>{x.rank}</span> : <span className="muted">–</span>}</td>
        <td className="num"><span className="cloth">{x.cloth ?? ""}</span>{x.draw ? <div className="draw">({x.draw})</div> : null}</td>
        <td>
          <span className="hname">{x.horse}</span>
          {top && <span className="badge">TOP RATED</span>}{" "}
          {x.headgear && <span className="hg" title="headgear (1 = first time)">{x.headgear}</span>}
          <div className="hsub">
            {x.last_ran_days != null ? `${x.last_ran_days} days since last run · ` : ""}
            {x.runs ?? 0} runs, {x.wins ?? 0} wins, {x.places ?? 0} places{x.nr ? " · NON-RUNNER" : ""}
          </div>
        </td>
        <td className="form">{x.form || ""}</td>
        <td className="num">{x.age ?? ""}{x.sex || ""}</td>
        <td className="num">{x.weight || ""}</td>
        <td className="num">{x.official_rating ?? "–"}</td>
        <td>{x.jockey || ""}{x.jockey_claim ? <span className="muted"> ({x.jockey_claim})</span> : null}<div className="hsub">{x.trainer || ""}</div></td>
        <td className="num">{x.odds || x.forecast_odds || ""}</td>
        <td className="num"><Fig v={rt.last} col={cols.last} /></td>
        <td className="num"><Fig v={rt.best3} col={cols.best3} /></td>
        <td className="num"><Fig v={rt.avg3} col={cols.avg3} /></td>
        <td className="num"><Fig v={rt.best} col={cols.best} /></td>
        {show2 && <><td className="num"><Fig v={rt.best3_2yo} col={cols.best3_2yo} /></td><td className="num"><Fig v={rt.best2yo} col={cols.best2yo} /></td></>}
      </tr>
      {showForm && (
        <tr className="formrow"><td colSpan={ncols}><FormTable runs={x.form_runs} col={runCol} /></td></tr>
      )}
    </>
  );
}

function FormTable({ runs, col }: { runs: FormRun[]; col: ColourFn }) {
  if (!runs?.length) return <span className="muted">No previous runs.</span>;
  return (
    <table className="runs">
      <thead>
        <tr><th>Date</th><th>Course</th><th>Dist</th><th>Going</th><th>Type</th><th>Cl</th><th>Pos</th><th>Btn</th><th>SP</th><th>OR</th><th>Fig</th><th>Comment</th></tr>
      </thead>
      <tbody>
        {runs.map((r, i) => (
          <tr key={i}>
            <td>{fmtDate(r.date)}</td><td>{r.course}</td><td>{r.dist}</td><td>{shortGoing(r.going)}</td>
            <td>{r.type}</td><td>{r.cls}</td>
            <td className={`pos${r.pos === "1" ? " won" : ""}`}>{r.pos}{r.ran ? `/${r.ran}` : ""}</td>
            <td>{r.btn == null ? "" : r.pos === "1" ? "–" : r.btn}</td>
            <td>{r.sp || ""}</td><td>{r.or ?? ""}</td>
            <td><Fig v={r.fig} col={col} /></td>
            <td className="cmt" title={r.comment || ""}><div>{r.comment || ""}</div></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
