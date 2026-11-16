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
            A plain-English guide to the figures, the predicted-today rating, form-only win %, pace labels, and the flags on the race card — and what we&apos;re building next.
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
            <b>Best 3</b> is the average of the horse&apos;s best three figures from its last 12 runs,
            in the same discipline as today (Flat/AW or jumps). In 2yo races we use the 2yo scale instead.
            It is shown under the predicted figure, as a second opinion — it rewards past peaks, which the
            predicted figure is trying not to over-trust.
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
          <h2>Predicted today</h2>
          <p>
            The big number on each runner is now a <b>predicted figure for today</b> — what we think the horse
            will actually run in this race, not its best old figure. Recent runs count most, the trend is given
            credit, and we take into account class change, days since the last run, trip, going, and how the
            horse has performed at today&apos;s conditions.
          </p>
          <p>
            The mix is learned from hundreds of thousands of past runs (using only information known before
            each race), then tested on a later year it has not seen. On that test, the predicted figure is
            closer to what the horse actually ran than Best 3 or the last figure alone, and the top-predicted
            horse wins a little more often than the top Best 3 horse. It is still an interim model: it does
            not yet check whether a past figure was inflated by a soft race standard, and a typical miss is
            around a stone. The range under the number (for example 100–121) is that typical error band.
          </p>
          <p>
            Runners are sorted by this predicted figure, strongest at the top. <b>Best 3</b> is still shown
            underneath, so you can see where a horse sits on its peaks as well as on what we think it will
            run today. Colours are still ranked within this race only: green is the highest predicted figure
            in the field, red is the lowest.
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

        <section>
          <h2>Race pace and true-run figures</h2>
          <p>
            A speed figure can look poor — or brilliant — because of <em>how</em> the race was run, not how good the
            horse is. Some races are truly run: they go an honest gallop and the time means what it says. Others crawl
            early and turn into a sprint at the end. A horse can win easily like that and still only record a modest
            figure, because the overall time was slow.
          </p>
          <p>
            Every past run on the form now has a <b>Pace</b> badge, and a flag on whether we trust that figure:
          </p>
          <ul>
            <li><span className="pace true">True run</span> — an honest or even pace. The figure is usually a fair measure of what the horse ran to.</li>
            <li><span className="pace steady">Steady</span> — a shade slow early, with a quicker finish. Treat the figure with a little more caution.</li>
            <li><span className="pace slow">Slow-run</span> — a slow early pace and a sprint finish. The figure is often lower than the horse&apos;s ability, and is marked as unreliable.</li>
          </ul>
          <p>We build that label from three checks, in this order:</p>
          <ul>
            <li>
              <b>Sectionals</b> — where we have Racing TV data, the finishing-speed percentage (how much faster the
              last two furlongs were than the race average). A high percentage means they finished much faster than
              they travelled, which is the signature of a slow-run race. The bands are set from the data itself, by
              code and distance, because a 2m hurdle doesn&apos;t finish the same way a 5f sprint does.
            </li>
            <li>
              <b>The whole field</b> — we compare each runner&apos;s figure with the median of its other runs. If the
              field as a group ran around 10 lb or more below their usual level, we mark it as a slow-run race and
              the figure as <b>Low (pace-affected)</b>. If the field ran well <em>above</em> its usual level, we flag
              the figure as <b>Suspect high</b> — the race standard may have been too soft.
            </li>
            <li>
              <b>The comment</b> — a weaker fallback when we don&apos;t have those two. Phrases such as &quot;slowly run&quot;,
              &quot;false pace&quot;, &quot;dictated&quot; or &quot;pulled hard&quot; can hint at a steady or slow race.
            </li>
          </ul>
          <p>
            Hover the badge for a one-line reason, for example &quot;Field ran 14 below their usual; finish 108% (sprint)&quot;.
            Unreliable figures are drawn with a dashed, faded style on the form and as a dashed point on the trend chart.
            This first version does not yet change the Predicted today weights — it shows you which past runs to trust.
          </p>
        </section>


        <section>
          <h2>Win % and fair odds</h2>
          <p>
            Each runner also has a <b>win percentage</b> — our estimate of how likely it is to win this race,
            from form only. The figures in a race are turned into probabilities that <b>add up to 100%</b>.
            We use the predicted-today figure, how far it sits behind the top of the race, Best of the last 3,
            the last figure, class and official-rating moves, days since the last run, field size, and a
            reliability adjustment when a recent figure came from a slow or suspicious pace. Starting prices
            and Betfair prices are not used to make the number.
          </p>
          <p>
            Next to the win % is a <b>fair odds</b> in decimal form (for example 5.50, which is the same as 9/2).
            Compare it with the live price: <b>if the price is bigger than our fair odds, it may be value</b>.
            That is a guide, not a ready-made bet — prices were held back and only used afterwards to check
            whether the rule would have paid on a later year of results.
          </p>
          <p>
            You can sort the card <b>By win %</b>. All odds on the site (the card, the form table, and the
            headline price) are shown as decimals: 5/2 becomes 3.50, evens becomes 2.00.
          </p>
        </section>

        <section className="guide-soon">
          <h2>Coming soon</h2>
          <p>
            The predicted figure above is a first pass. Once the Racing TV results and the rest of the sectionals are in, we will:
          </p>
          <ul>
            <li>
              <b>Give pace-affected runs less weight</b> in Predicted today, once we have tested that it improves the
              forecast on past races.
            </li>
            <li>
              <b>Checking each figure against official ratings and class</b> — on top of the field-wide check above,
              so a big figure in a weak race can be marked down on more than pace alone.
            </li>
            <li>
              <b>OR on the same scale</b> — so you can see whether a horse&apos;s speed backs up its handicap mark.
            </li>
            <li>
              <b>Running style</b> — how a horse actually runs its races (travels strongly, leads, or finishes fast),
              once the sectional scrape is complete.
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
