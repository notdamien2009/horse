import type { Metadata } from "next";
import { SiteShell } from "@/components/SiteShell";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "How we rate" };

export default function HowWeRatePage() {
  return (
    <SiteShell activeId={null}>
      <article className="guide">
        <header className="guide-hero">
          <p className="guide-kicker">FurlongIQ</p>
          <h1>How we rate the horses</h1>
          <p className="guide-lead">
            A plain-English guide to the figures and flags on the race card — and what we&apos;re building next.
          </p>
        </header>

        <section>
          <h2>Speed figures</h2>
          <p>
            Each figure is our measure of how well a horse ran, on a scale with <b>100 as the base</b>. A higher number is better.
          </p>
          <p>We start from the race time, then adjust for:</p>
          <ul>
            <li><b>Going allowance</b> — how much the ground was quicker or slower than standard that day.</li>
            <li><b>Weight for age</b> — younger horses get a fair allowance, using the official BHA scale.</li>
            <li><b>Weight carried</b> — figures are compared at a base weight of 9st on the Flat and 11st over jumps.</li>
          </ul>
          <p>
            Two-year-olds have their own scale, which we use in 2yo races. Figures have a floor of 45, so a very slow run
            doesn&apos;t drag a horse&apos;s record into the weeds.
          </p>
          <p>
            These are <em>our</em> figures, not official ratings. They tell you how fast the horse ran, not what the handicapper thinks it should be.
          </p>
        </section>

        <section>
          <h2>Best 3, Last and Avg 3</h2>
          <p>
            The big number on each runner is <b>Best 3</b>: the average of the horse&apos;s best three figures from its last 12 runs,
            in the same discipline as today (Flat/AW or jumps). In 2yo races we use the 2yo scale instead.
          </p>
          <p>The smaller chips underneath are:</p>
          <ul>
            <li><b>Last</b> — the most recent figure.</li>
            <li><b>Avg 3</b> — the average of the last three figures, good or bad.</li>
            <li><b>Best</b> — the best figure we have, of any age.</li>
            <li><b>2yo</b> — the best figure on the 2yo scale, when we have one.</li>
          </ul>
          <p>
            Colours are ranked <b>within this race only</b>: green is the best of these runners, red is the weakest.
            A 110 can be green in one race and amber in another. That&apos;s deliberate — it shows who&apos;s ahead
            today, not a lifetime grade.
          </p>
        </section>

        <section>
          <h2>Trend</h2>
          <p>
            The Rising / Falling badge is a trend line through the last 3 to 6 runs with a figure, preferably in the same
            discipline as today.
          </p>
          <ul>
            <li><span className="trend up">▲ Rising</span> — improving by about 1½ lb a run or more.</li>
            <li><span className="trend down">▼ Falling</span> — declining by the same amount.</li>
            <li><span className="trend flat">▶ Steady</span> — in between.</li>
          </ul>
          <p>
            This is why a lightly raced, improving horse can be more interesting than one sitting on an old peak.
            Best 3 rewards past highs; the trend tells you which way the horse is travelling.
          </p>
        </section>

        <section>
          <h2>Today&apos;s conditions</h2>
          <p>
            A past run is marked as &quot;today&apos;s conditions&quot; (a gold ring on the chart, and a gold row in the form)
            when it matches this race on:
          </p>
          <ul>
            <li>the same code (Flat, AW, Hurdle, Chase or bumper)</li>
            <li>a similar trip (within 1 furlong, or 10%)</li>
            <li>similar going (within one step, for example Good to Soft vs Good or Soft; or all-weather with all-weather)</li>
            <li>class within one grade (if we don&apos;t know the class, we don&apos;t hold it against the horse)</li>
          </ul>
          <p>
            The <b>Today&apos;s cond.</b> chip is the best figure the horse has run at those conditions, and how many times it has run them.
          </p>
        </section>

        <section>
          <h2>Class change</h2>
          <p>
            Class 1 is the highest grade; Class 6 or 7 is the lowest. We compare today&apos;s class with the horse&apos;s last run
            and the average of its last three runs, using the same discipline where we can.
          </p>
          <ul>
            <li><span className="cls-flag drop">Class drop ▼</span> — today is a lower class, so an easier race than it has been contesting.</li>
            <li><span className="cls-flag rise">Class rise ▲</span> — today is a step up.</li>
          </ul>
          <p>
            If the official rating has moved since its last run in this discipline, you&apos;ll also see that next to the OR
            (for example OR 113 <em className="or-delta down">−2</em>). A horse dropping in class isn&apos;t automatically the pick —
            but it is the kind of thing that Best 3 alone can miss.
          </p>
        </section>

        <section className="guide-soon">
          <h2>Coming soon</h2>
          <p>
            We&apos;re building a fuller rating, to sit next to Best 3 as a <b>predicted figure for today</b>. The plan is:
          </p>
          <ul>
            <li>
              <b>A predicted figure for today</b> — recent runs count most, the trend is given credit, and we take into
              account how well the horse fits today&apos;s conditions. The mix will be learned from thousands of past results,
              then tested on races the model hasn&apos;t seen.
            </li>
            <li>
              <b>Checking each figure</b> — compare it with the horse&apos;s official rating and the class of that race.
              If the horses it beat ran to their usual level elsewhere, the figure holds up. If a whole field suddenly ran
              15 lb above their norm, the race standard may have been wrong, and we&apos;ll flag that figure as suspect.
            </li>
            <li>
              <b>OR on the same scale</b> — so you can see whether a horse&apos;s speed backs up its handicap mark.
            </li>
            <li>
              <b>Sectionals and running style</b> — once that scrape is in, how a horse actually runs its races
              (travels strongly, leads, or finishes fast).
            </li>
            <li>
              <b>Trade predictions</b> — the chance a horse trades below 2.0 in running, halves its price (DOB),
              or hits the 1.8, 1.5 and 1.2 lay levels.
            </li>
          </ul>
          <p>
            A first pass at those trade predictions, using price, form and speed figures, was accurate — but it only
            matched the market. It didn&apos;t beat it. The edge, if there is one, is more likely to come from sectionals
            and the fuller rating above. We&apos;ll show the profit-or-loss test when that work is done.
          </p>
        </section>
      </article>
    </SiteShell>
  );
}
