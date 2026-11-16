FURLONGIQ RACING SITE - v7 (Next.js, same set-up as PetLife)
=========================================================
Today's UK & Irish race cards with form, our speed figures and ratings.
http://localhost:3050   (port 3050 so it never clashes with PetLife / NOVA on 3000)
To put the same site on Vercel (reading from the horse Supabase), see HOSTING.txt.

FIRST TIME (from cmd in C:\Users\PC Deals\Desktop\Speeds)
  npm install                 - once; makes the node_modules folder (about a minute)

EVERY DAY
  1. GET_TODAYS_CARDS.bat     - or: npm run cards   (downloads today's cards into data\cards.sqlite)
  2. PREDICT_TODAY.bat        - first time trains the 'predicted today' model (~2 minutes) and
                                scores today's cards. Later days you can just run RUN_SITE.bat;
                                it will re-score today's cards if the model is already there.
  3. npm run dev              - or double-click RUN_SITE.bat, then open http://localhost:3050
     Before the site starts it builds/checks the figure cache (data\site_cache.sqlite) from
     data\speed_v3\speed_figures.csv (v2 if there is no v3). First time ~1 minute, then about a second.
     You should see a line like:
       [figures] READY: speed_v3 - 433,256 runs (360,522 with a figure), races up to 2026-11-13 ...
     If the figures can't be built it stops with a "FIGURES NOT READY" box saying why
     (e.g. Python not found, or "pip install pandas" needed). The header of the site shows
     "Figures: speed_v3 . 433,256 runs . to <date>" when they are loaded.
  Press Ctrl+C in the cmd window to stop the site.

OTHER COMMANDS
  npm run figures    - rebuild/check the figure cache only (delete data\site_cache.sqlite to force a full rebuild)
  npm run build      - production build;  npm start  - run the production build on port 3050
  npm run typecheck  - TypeScript check

WHERE THINGS ARE
  package.json, RUN_SITE.bat     - in the Speeds folder (run npm from here)
  web\                           - the website (Next.js 16 App Router, React 19, TypeScript)
    web\src\app\                 - pages: / (jumps to the next race), /race/<id>, /how-we-rate, /api/meta, /api/card, /api/race/<id>
    web\src\components\          - RaceTabs (top bar), RaceCard (hero + runner cards), ThemeToggle, SiteShell
    web\src\lib\                 - db.ts (reads the SQLite files with Node's built-in node:sqlite), racing.ts, summary.ts (race-tab summaries), colours.ts
    web\scripts\prepare-figures.mjs - the figure-cache step that runs before npm run dev / build
  tools\sl_cards.py              - Sporting Life card scraper (unchanged)
  site\figcache.py               - builds data\site_cache.sqlite (unchanged; the old Python site still works:
                                   python site\app.py)
  Data is read straight from data\cards.sqlite and data\site_cache.sqlite - nothing is copied into the site.

READING A RACE CARD (v2 design)
  Top bar (stays on screen): meetings as pills, then one chip per race with the time, runner count and the
  top-rated horse + figure. "Next off" counts down to the next race; races already run fade out.
  Race header: time, course and race name, key facts, "Ratings at a glance" bar chart (Best 3, ranked and
  coloured), the TOP RATED horse with how many pounds clear it is, and the Sporting Life verdict.
  Runner cards: rank badge, cloth (draw), silk, horse, age/sex/weight/OR, jockey / trainer, odds on the right.
  Big coloured number = Predicted today (the figure we think the horse will run in this race: recent form,
  trend, class change, trip, going and conditions-fit, learned from past results and tested on a later year).
  A typical-error range sits under the number. Best 3 is kept as a chip underneath, then Last / Avg 3 / Best / 2yo.
  "By rating" sorts by the predicted figure, strongest at the top (2yo scale in 2yo races). Form chips as before.
  SPEED-FIGURE TREND CHART (v3) on every runner, last 8 runs, oldest left -> newest right (newest always in the
  right-hand slot so the charts line up down the card; all charts in a race share one scale):
    - points coloured on the race heat scale; the last figure is labelled
    - runs with no figure (PU, F, UR, unplaced without a figure) = small hollow circle on the axis, the line
      carries on past them as a dashed segment; finishing position under every point
    - gold dashed line = today's top Best 3 in the race (2yo Best 3 in 2yo races, where the chart uses 2yo figures)
    - trend line + badge: least-squares slope over the last 3-6 runs with a figure (same discipline as today -
      jumps runs for a jumps race, Flat/AW runs for a Flat race - when there are 3+ of them):
      "Rising +X/run" (green, +1.5 lb a run or more), "Falling -X/run" (red), "Steady" (grey)
    - RIGHT RACE / WRONG RACE: a run is "today's conditions" (gold ring + gold column) when it was the same code
      (Flat / AW / Hurdle / Chase / NHF), trip within 1f or 10%, similar going (within one step, e.g. Good to
      Soft vs Good or Soft; AW with AW) and class within one (unknown class doesn't count against it).
      Diamond = different code (e.g. a Flat run for a hurdler). The line above the cards spells out today's conditions.
    - "Today's cond." chip = best figure the horse has run at today's conditions (whole history) and how many runs
    - hover a point for date, course, trip, going, class, position, figure and which conditions matched
  Click a card (or the arrow) to open its form: a big version of the chart, then the last 8 runs with a
  "vs today" column (C = code, T = trip, G = going, Cl = class; gold rows = today's conditions).
  Colours are ranked within the race: green = best, red = worst. Sun/moon button = light/dark.
  CLASS CHANGE (v6): a "Class drop ▼" (green) or "Class rise ▲" (amber) badge when today's class is easier or
  tougher than the last run, or the average of the last 3 runs (same discipline where we can). Class 1 is the
  highest grade. If the official rating has moved since the last run in this discipline, the change is shown
  next to the OR (e.g. OR 113 −2).
  PREDICTED TODAY (v7): default sort and the big number on each runner. Interim model — does not yet check
  whether a past figure was inflated by a soft race standard. HOW WE RATE: a plain-English guide at
  /how-we-rate (link in the header), now including Predicted today, plus Best 3, trend, conditions, class
  change, and what's coming next (figure checks, OR on the speed scale, sectionals, trade predictions).
  Honest note: a first pass at trade predictions matched the market but didn't beat it.
  Not yet: odds & trading analysis and sectionals (greyed "coming soon" panels). No probabilities.

GIT
  If Speeds is a git repo, add these two lines to Speeds\.gitignore:  node_modules/   and   web/.next/

HOSTING
  See HOSTING.txt. Double-click UPLOAD_TO_SUPABASE.bat after today's cards and
  figures are ready, to refresh the live site. Local npm run dev is unchanged.
