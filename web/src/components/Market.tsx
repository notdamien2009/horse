import Link from "next/link";
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BarChart3, BookOpen, Calculator, CheckCircle2, Gauge, LineChart,
  ListChecks, PlayCircle, Radar, ShieldCheck, Sparkles, Timer, TrendingDown, TrendingUp, Users,
} from "lucide-react";
import raw from "@/lib/market-stats.json";
import { SITE } from "@/lib/site-config";
import { BetCalc } from "./BetCalc";

/* ---------- data (built by BUILD_MARKET_STATS.bat from FurlongIQ history) ---------- */
type G = { runners: number; wins: number; sr: number | null; ae: number | null; roi: number | null };
type T = { trainer: string; all: G; backed: G; strong: G; drifted: G };
type H = { horse: string; trainer: string; last: string; all: G; backed: G; drifted: G };
type Mover = { time: string; course: string; horse: string; trainer: string; p0: number; p0_col: string; sp: number; move: number; top_pct: number | null; pos: number | null };
type Stats = {
  built: string; counts: Record<string, number> & { first_date: string; last_date: string };
  rules: { back_pp: number; strong_pp: number; drift_pp: number };
  overall: Record<"all" | "backed" | "strong" | "drifted" | "steady", G>;
  examples: { backed: T; drift: T; strong: T }; trainers: T[]; horses: H[];
  movers: { date: string; supporters: Mover[]; drifters: Mover[] };
};
const S = raw as unknown as Stats;

const n0 = (n: number) => n.toLocaleString("en-GB");
const big = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n0(n));
const pct = (v: number | null) => (v == null ? "–" : `${v.toFixed(1)}%`);
const signed = (v: number | null, unit = "%") => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)}${unit}`);
const fmtDay = (d: string) => new Date(d + "T12:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const posTxt = (p: number | null) => (p == null ? "–" : p === 1 ? "Won" : `${p}${p === 2 ? "nd" : p === 3 ? "rd" : "th"}`);
const earlyLbl = (c: string) => c.replace(/\s*mins?/i, " min").toLowerCase();
const yearsSpan = () => `${new Date(S.counts.first_date).getFullYear()}–${new Date(S.counts.last_date).getFullYear()}`;

/* ---------- shared bits ---------- */
export function PageHead({ eyebrow, title, lead }: { eyebrow: string; title: string; lead?: string }) {
  return (
    <header className="mk-page-head">
      <p className="mk-eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      {lead && <p>{lead}</p>}
    </header>
  );
}

function SecHead({ eyebrow, title, lead }: { eyebrow: React.ReactNode; title: string; lead?: React.ReactNode }) {
  return (
    <header className="mk-sec-head">
      <p className="mk-eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {lead && <p>{lead}</p>}
    </header>
  );
}

function Bar({ label, g, tone }: { label: string; g: G; tone: "base" | "up" | "down" }) {
  const w = Math.min(100, ((g.sr ?? 0) / 60) * 100);
  return (
    <div className={`mk-bar ${tone}`}>
      <div className="mk-bar-top"><span>{label}</span><b>{pct(g.sr)}</b></div>
      <div className="mk-bar-track"><i style={{ width: `${w}%` }} /></div>
      <small>{n0(g.wins)} wins / {n0(g.runners)} runners · A/E {g.ae?.toFixed(2) ?? "–"}</small>
    </div>
  );
}

/* ---------- home ---------- */
export function Hero() {
  const c = S.counts;
  return (
    <section className="mk-hero">
      <div className="mk-hero-copy">
        <p className="mk-kicker"><Sparkles size={14} aria-hidden /> FurlongIQ · racing market intelligence</p>
        <h1>See the money <span>before</span> you stake yours.</h1>
        <p className="mk-lead">
          Every price move in today&apos;s racing, set against {yearsSpan()} of FurlongIQ market history, speed ratings and
          trainer records. Know when a gamble has history behind it — and when a drift is just noise.
        </p>
        <ul className="mk-ticks">
          <li><CheckCircle2 size={18} aria-hidden /> Skip the bets the market has already found out.</li>
          <li><CheckCircle2 size={18} aria-hidden /> Act fast when support is genuinely rare.</li>
          <li><CheckCircle2 size={18} aria-hidden /> One screen for prices, ratings, pace and form.</li>
        </ul>
        <div className="mk-cta">
          <Link href="/pricing" prefetch={false} className="mk-btn primary">Join for £{SITE.priceMonthlyGBP}/month</Link>
          <Link href="/cards" prefetch={false} className="mk-btn ghost">Today&apos;s racecards</Link>
        </div>
        <p className="mk-fine">History to {fmtDay(c.last_date)} · stats rebuilt {S.built}</p>
      </div>
      <Terminal rows={4} />
    </section>
  );
}

function Terminal({ rows }: { rows: number }) {
  return (
    <div className="mk-hero-panel" aria-label="Market snapshot">
      <div className="mk-term-head"><Activity size={15} aria-hidden /> Market snapshot <span className="mk-dot" /> {fmtDay(S.movers.date)}</div>
      {S.movers.supporters.slice(0, rows).map((m, i) => (
        <div key={`u${i}`} className="mk-term-row up"><span>{m.time} {m.course}</span><b>{m.horse}</b><em>{m.p0.toFixed(2)} → {m.sp.toFixed(2)}</em><i>{signed(m.move, "pp")}</i></div>
      ))}
      {S.movers.drifters.slice(0, Math.max(1, rows - 1)).map((m, i) => (
        <div key={`d${i}`} className="mk-term-row down"><span>{m.time} {m.course}</span><b>{m.horse}</b><em>{m.p0.toFixed(2)} → {m.sp.toFixed(2)}</em><i>{signed(m.move, "pp")}</i></div>
      ))}
      <p className="mk-fine">Latest day in the FurlongIQ history. Live feed coming soon.</p>
    </div>
  );
}

export function Counters() {
  const c = S.counts;
  return (
    <section className="mk-stats" aria-label="FurlongIQ data">
      <h2 className="mk-eyebrow">Built on {big(c.price_points)} FurlongIQ price points</h2>
      <div className="mk-counters">
        <div><b>{n0(c.runners)}</b><span>Runners tracked</span><small>Every price, rating and result</small></div>
        <div><b>{n0(c.races)}</b><span>Races</span><small>{n0(c.courses)} UK &amp; Irish courses</small></div>
        <div><b>{n0(c.horses)}</b><span>Horse profiles</span><small>How each one handles support</small></div>
        <div><b>{n0(c.trainers)}</b><span>Trainer profiles</span><small>Strike rates when backed or drifting</small></div>
        <div><b>{n0(c.jockeys)}</b><span>Jockeys</span><small>Every ride on record</small></div>
        <div><b>{n0(c.fig_runs)}</b><span>FIQ speed ratings</span><small>Our own figure for every run</small></div>
      </div>
    </section>
  );
}

export function MovesOverview() {
  const o = S.overall, r = S.rules;
  return (
    <section className="mk-sec">
      <SecHead eyebrow="What the market tells you" title="Moves change the odds of winning. Not always the value."
        lead={<>All {n0(o.all.runners)} runners with an early price, split by how far their chance moved from the early price to the FIQ SP.</>} />
      <div className="mk-moves">
        {([
          ["Backed +" + r.strong_pp + "pp or more", o.strong, "up"],
          ["Backed +" + r.back_pp + "pp or more", o.backed, "up"],
          ["Steady", o.steady, "base"],
          ["Drifted " + r.drift_pp + "pp or more", o.drifted, "down"],
        ] as const).map(([label, g, tone]) => (
          <div key={label} className={`mk-move ${tone}`}>
            <span>{label}</span><b>{pct(g.sr)}</b><small>win rate · {n0(g.runners)} runners</small>
            <em>A/E {g.ae?.toFixed(2)} · {signed(g.roi)} at FIQ SP</em>
          </div>
        ))}
      </div>
      <p className="mk-note">
        Backed horses win far more often, but the final price already reflects it. The edge comes from knowing
        <b> which</b> trainers and horses beat their final price when the money arrives.
      </p>
    </section>
  );
}

function EdgeCard({ step, title, lead, t, k, kLabel, rule, note }: {
  step: string; title: string; lead: string; t: T; k: "backed" | "strong" | "drifted"; kLabel: string; rule: string; note: string;
}) {
  const g = t[k];
  return (
    <article className="mk-edge">
      <p className="mk-step">{step}</p>
      <h3>{t.trainer}</h3>
      <p className="mk-edge-lead">{title}</p>
      <div className="mk-bars">
        <Bar label="All runners" g={t.all} tone="base" />
        <Bar label={kLabel} g={g} tone={k === "drifted" ? "down" : "up"} />
      </div>
      <p className="mk-edge-say">{lead}</p>
      <p className="mk-rule"><Timer size={13} aria-hidden /> {rule}</p>
      <p className="mk-fine">{note} Profit at FIQ SP after {SITE.commissionPct}% commission: <b className={(g.roi ?? 0) >= 0 ? "pos" : "neg"}>{signed(g.roi)}</b> on {n0(g.runners)} runs.</p>
    </article>
  );
}

export function EdgeCards() {
  const ex = S.examples, r = S.rules, o = S.overall;
  const rareShare = ((o.strong.runners / o.all.runners) * 100).toFixed(1);
  return (
    <section className="mk-sec">
      <SecHead eyebrow="The FurlongIQ edge" title="Same move. Different trainer. Different story." />
      <div className="mk-edges">
        <EdgeCard step="01 · Support that matters" t={ex.backed} k="backed" kLabel={`Backed +${r.back_pp}pp`}
          title="When this yard's runners are backed late, take notice."
          lead={`${pct(ex.backed.backed.sr)} when backed, against ${pct(ex.backed.all.sr)} overall.`}
          rule={`Early price → FIQ SP · support of ${r.back_pp}+ points.`}
          note="Picked from every trainer with 150+ runs, so the top of the list flatters." />
        <EdgeCard step="02 · Rare, strong support" t={ex.strong} k="strong" kLabel={`Backed +${r.strong_pp}pp`}
          title="Big moves are rare here — and they land."
          lead={`Only ${ex.strong.strong.runners} of ${n0(ex.strong.all.runners)} runners were backed this hard; ${ex.strong.strong.wins} won.`}
          rule={`Early price → FIQ SP · support of ${r.strong_pp}+ points (${rareShare}% of all runners).`}
          note="Small sample — treat as a lead to watch, not a system." />
        <EdgeCard step="03 · Ignore the drift" t={ex.drift} k="drifted" kLabel={`Drifted ${r.drift_pp}pp`}
          title="A drift hasn't cost this yard winners."
          lead={`${pct(ex.drift.drifted.sr)} after a drift, against ${pct(ex.drift.all.sr)} overall — almost identical.`}
          rule={`Early price → FIQ SP · drifts of ${Math.abs(r.drift_pp)}+ points.`}
          note="Don't panic out of a selection on a drift alone." />
      </div>
    </section>
  );
}

export function Explore() {
  const items: [string, string, string, React.ReactNode][] = [
    ["/live", "Live market", "Today's moves as they happen, with how unusual each one is.", <Radar key="i" size={20} aria-hidden />],
    ["/movers", "Movers grid", "The biggest supporters and drifters, with results.", <TrendingUp key="i" size={20} aria-hidden />],
    ["/profiles", "Horse & trainer profiles", "Who wins when backed — and who beats their price.", <Users key="i" size={20} aria-hidden />],
    ["/tools", "Tools", "Back & lay calculator, value finder and more.", <Calculator key="i" size={20} aria-hidden />],
    ["/guides", "Guides", "Step-by-step how-to, glossary and tutorials.", <BookOpen key="i" size={20} aria-hidden />],
    ["/cards", "Racecards", "FIQ speed ratings, win % and fair odds for every runner.", <Gauge key="i" size={20} aria-hidden />],
  ];
  return (
    <section className="mk-sec">
      <SecHead eyebrow="Inside FurlongIQ" title="Everything you need on raceday." />
      <div className="mk-explore">
        {items.map(([href, t, d, icon]) => (
          <Link key={href} href={href} prefetch={false} className="mk-tile">
            <span className="mk-tile-ic">{icon}</span><b>{t}</b><small>{d}</small><ArrowRight size={16} aria-hidden className="mk-tile-go" />
          </Link>
        ))}
      </div>
    </section>
  );
}

/* ---------- movers ---------- */
function MoverTable({ rows, kind }: { rows: Mover[]; kind: "up" | "down" }) {
  return (
    <div className="mk-grid-wrap">
      <h3 className={kind}>{kind === "up" ? <TrendingUp size={17} aria-hidden /> : <TrendingDown size={17} aria-hidden />} {kind === "up" ? "Biggest supporters" : "Biggest drifters"}</h3>
      <table className="mk-grid">
        <thead>
          <tr><th>Off</th><th>Horse</th><th className="n">Early</th><th className="n">FIQ SP</th><th className="n">Move</th><th>How unusual</th><th className="n">Result</th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="t"><b>{r.time}</b><small>{r.course}</small></td>
              <td><b>{r.horse}</b><small>{r.trainer}</small></td>
              <td className="n">{r.p0.toFixed(2)}<small>{earlyLbl(r.p0_col)}</small></td>
              <td className="n">{r.sp.toFixed(2)}</td>
              <td className={`n mv ${kind}`}>{kind === "up" ? <ArrowUpRight size={13} aria-hidden /> : <ArrowDownRight size={13} aria-hidden />}{signed(r.move, "pp")}</td>
              <td><span className="mk-rare">{r.top_pct == null ? "–" : `Top ${r.top_pct < 1 ? r.top_pct.toFixed(1) : Math.round(r.top_pct)}%`}</span><small>of moves at this price</small></td>
              <td className={`n res${r.pos === 1 ? " won" : ""}`}>{posTxt(r.pos)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MoversGrid() {
  return (
    <section className="mk-sec" id="movers">
      <SecHead eyebrow="FurlongIQ movers grid" title={`${fmtDay(S.movers.date)}: the biggest moves, with context.`}
        lead={<>Move = change in win chance, in percentage points, from the early price to the FIQ SP. &ldquo;How unusual&rdquo; compares each move with every runner at a similar price since {new Date(S.counts.first_date).getFullYear()}.</>} />
      <div className="mk-grids">
        <MoverTable rows={S.movers.supporters} kind="up" />
        <MoverTable rows={S.movers.drifters} kind="down" />
      </div>
    </section>
  );
}

/* ---------- live ---------- */
export function LiveMarket() {
  return (
    <section className="mk-sec mk-split">
      <div>
        <Terminal rows={6} />
      </div>
      <div className="mk-panel">
        <p className="mk-eyebrow"><Radar size={14} aria-hidden /> Live market terminal</p>
        <h3>Live feed coming soon</h3>
        <p>On raceday this panel will stream today&apos;s prices and flag any runner whose move is in the top 5% for its price — with the trainer and horse record alongside. Until then it shows the latest day in the FurlongIQ history.</p>
        <ul className="mk-list">
          <li>Early price, latest price and move in points</li>
          <li>How unusual the move is, from FurlongIQ history</li>
          <li>Alerts for the trainers and horses you follow</li>
        </ul>
      </div>
    </section>
  );
}

export function Workspace() {
  return (
    <section className="mk-sec">
      <SecHead eyebrow={<><LineChart size={14} aria-hidden /> Raceday workspace</>} title="Everything for the race in one view." />
      <div className="mk-links cols">
        <Link href="/cards" prefetch={false}><Gauge size={16} aria-hidden /> Racecards with FIQ speed ratings &amp; win %</Link>
        <Link href="/cards" prefetch={false}><BarChart3 size={16} aria-hidden /> Sectionals &amp; pace maps for every race</Link>
        <Link href="/movers" prefetch={false}><TrendingUp size={16} aria-hidden /> Movers grid</Link>
        <Link href="/how-we-rate" prefetch={false}><BookOpen size={16} aria-hidden /> How the FurlongIQ ratings work</Link>
      </div>
    </section>
  );
}

/* ---------- profiles ---------- */
export function TrainerTable() {
  return (
    <section className="mk-sec" id="trainers">
      <SecHead eyebrow={<><Users size={14} aria-hidden /> Trainer profiles</>} title={`The busiest ${S.trainers.length} yards, backed vs drifting.`}
        lead="A/E = actual winners ÷ winners expected from the FIQ SP. Above 1.00 means the yard beat its prices. Small numbers under each win % are runs." />
      <div className="mk-table-wrap">
        <table className="mk-grid mk-trainers">
          <thead>
            <tr><th>Trainer</th><th className="n">Runs</th><th className="n">Win %</th><th className="n">A/E</th>
              <th className="n">Backed win %</th><th className="n">Backed A/E</th><th className="n">Drifted win %</th><th className="n">Drifted A/E</th></tr>
          </thead>
          <tbody>
            {S.trainers.map((t) => (
              <tr key={t.trainer}>
                <td><b>{t.trainer}</b></td>
                <td className="n">{n0(t.all.runners)}</td>
                <td className="n">{pct(t.all.sr)}</td>
                <td className="n">{t.all.ae?.toFixed(2)}</td>
                <td className="n up">{pct(t.backed.sr)}<small>{t.backed.runners}</small></td>
                <td className={`n ${(t.backed.ae ?? 0) >= 1 ? "pos" : "neg"}`}>{t.backed.ae?.toFixed(2) ?? "–"}</td>
                <td className="n down">{pct(t.drifted.sr)}<small>{t.drifted.runners}</small></td>
                <td className={`n ${(t.drifted.ae ?? 0) >= 1 ? "pos" : "neg"}`}>{t.drifted.ae?.toFixed(2) ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function HorseTable() {
  return (
    <section className="mk-sec" id="horses">
      <SecHead eyebrow="Horse profiles" title="The horses the market backs most often."
        lead={`Horses with 10+ runs, ranked by how many times they were backed by ${S.rules.back_pp}+ points. Does the money land?`} />
      <div className="mk-table-wrap">
        <table className="mk-grid">
          <thead>
            <tr><th>Horse</th><th>Latest trainer</th><th className="n">Runs</th><th className="n">Win %</th>
              <th className="n">Times backed</th><th className="n">Backed win %</th><th className="n">Backed A/E</th><th className="n">Last run</th></tr>
          </thead>
          <tbody>
            {S.horses.map((h) => (
              <tr key={h.horse}>
                <td><b>{h.horse}</b></td>
                <td>{h.trainer}</td>
                <td className="n">{h.all.runners}</td>
                <td className="n">{pct(h.all.sr)}</td>
                <td className="n">{h.backed.runners}</td>
                <td className="n up">{pct(h.backed.sr)}</td>
                <td className={`n ${(h.backed.ae ?? 0) >= 1 ? "pos" : "neg"}`}>{h.backed.ae?.toFixed(2) ?? "–"}</td>
                <td className="n">{fmtDay(h.last)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ---------- tools ---------- */
export function Tools() {
  return (
    <section className="mk-sec" id="tools">
      <div className="mk-tools">
        <BetCalc />
        <div className="mk-panel">
          <h3><Calculator size={17} aria-hidden /> Value finder</h3>
          <p>Every runner on the racecard has a FurlongIQ win % and fair odds. When the price on offer is bigger than our fair odds, it may be value.</p>
          <Link href="/cards" prefetch={false} className="mk-btn ghost sm">Open the racecards</Link>
        </div>
        <div className="mk-panel muted">
          <h3><ListChecks size={17} aria-hidden /> Tissue builder</h3>
          <p>Set your own chances for each runner and compare them with ours and the market. <b>Coming soon.</b></p>
        </div>
      </div>
    </section>
  );
}

/* ---------- guides ---------- */
export function HowTo() {
  return (
    <section className="mk-sec">
      <SecHead eyebrow="How to use FurlongIQ" title="Four steps to a clearer bet." />
      <ol className="mk-steps">
        <li><b>Start with the card.</b> Open the race and see who the FIQ speed ratings put on top, and by how much.</li>
        <li><b>Check the move.</b> Has the horse been backed or drifted since the early price? How rare is a move that size?</li>
        <li><b>Read the record.</b> What happens when this trainer&apos;s runners move like this — do they win, and do they beat their price?</li>
        <li><b>Price it.</b> Compare our fair odds with what&apos;s on offer, and work out returns after commission.</li>
      </ol>
    </section>
  );
}

export function Faq() {
  return (
    <section className="mk-sec" id="faq">
      <SecHead eyebrow="Glossary & FAQ" title="Plain English, no jargon." />
      <div className="mk-faq">
        <details><summary>What is the early price?</summary><p>The first FurlongIQ market price we hold for the runner before the off — normally 15 minutes before the race.</p></details>
        <details><summary>What is the FIQ SP?</summary><p>The FurlongIQ starting price: the final market price when the race starts. Profit figures are worked out at the FIQ SP with {SITE.commissionPct}% commission taken off winnings.</p></details>
        <details><summary>What does &ldquo;pp&rdquo; mean?</summary><p>Percentage points of win chance. A move from 5.0 (20%) to 4.0 (25%) is +5pp. It is not the percentage change in the price.</p></details>
        <details><summary>What is A/E?</summary><p>Actual winners divided by the winners the prices expected. 1.00 means the runners won exactly as often as their prices said; above 1.00 they beat the market.</p></details>
        <details><summary>Is a high win rate a reason to bet?</summary><p>No. Backed horses win more often, but they are also shorter. Look at A/E and profit at the FIQ SP, and at how many runs the figure is based on.</p></details>
        <details><summary>How often is this updated?</summary><p>The racecards update daily. The market history and profiles are rebuilt whenever new results are added.</p></details>
      </div>
    </section>
  );
}

export function Tutorials() {
  return (
    <section className="mk-sec">
      <SecHead eyebrow="Tutorial gallery" title="Short guides to every tool." />
      <div className="mk-tuts">
        {["Reading the racecard", "Spotting a rare move", "Trainer profiles explained", "Fair odds & value"].map((t) => (
          <div key={t} className="mk-tut"><PlayCircle size={30} aria-hidden /><b>{t}</b><small>Video coming soon</small></div>
        ))}
      </div>
    </section>
  );
}

/* ---------- pricing ---------- */
export function Pricing() {
  return (
    <section className="mk-sec" id="pricing">
      <div className="mk-price">
        <div>
          <p className="mk-ex">FurlongIQ membership · cancel anytime</p>
          <b className="mk-amt">£{SITE.priceMonthlyGBP}<small>/month</small></b>
          <ul className="mk-list">
            <li>Daily racecards with FIQ speed ratings, win % and fair odds</li>
            <li>Market movers grid and live market terminal</li>
            <li>Horse and trainer profiles, backed vs drifting</li>
            <li>Sectionals, pace maps and calculators</li>
          </ul>
          <Link href="/cards" prefetch={false} className="mk-btn primary">Start with today&apos;s racing</Link>
        </div>
        <div className="mk-guard"><ShieldCheck size={22} aria-hidden /><p>FurlongIQ shows what happened in the past. It is not a guarantee of future results. Please gamble responsibly — 18+.</p></div>
      </div>
    </section>
  );
}