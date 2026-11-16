SPEEDS RACING SITE - v1 (Next.js, same set-up as PetLife)
=========================================================
Today's UK & Irish race cards with form, our speed figures and ratings. Runs on this PC only:
http://localhost:3050   (port 3050 so it never clashes with PetLife / NOVA on 3000)

FIRST TIME (from cmd in C:\Users\PC Deals\Desktop\Speeds)
  npm install                 - once; makes the node_modules folder (about a minute)

EVERY DAY
  1. GET_TODAYS_CARDS.bat     - or: npm run cards   (downloads today's cards into data\cards.sqlite)
  2. npm run dev              - or double-click RUN_SITE.bat, then open http://localhost:3050
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
    web\src\app\                 - pages: / (jumps to the next race), /race/<id>, /api/meta, /api/card, /api/race/<id>
    web\src\components\          - RaceTabs, RaceCard (sort, form toggle, colours), ThemeToggle, SiteShell
    web\src\lib\                 - db.ts (reads the SQLite files with Node's built-in node:sqlite), racing.ts, colours.ts
    web\scripts\prepare-figures.mjs - the figure-cache step that runs before npm run dev / build
  tools\sl_cards.py              - Sporting Life card scraper (unchanged)
  site\figcache.py               - builds data\site_cache.sqlite (unchanged; the old Python site still works:
                                   python site\app.py)
  Data is read straight from data\cards.sqlite and data\site_cache.sqlite - nothing is copied into the site.

READING A RACE CARD - same as before
  One tab per race, grouped by meeting; faded tabs have already run. Rank / TOP RATED (gold) = Best 3
  (average of the best 3 figures from the last 12 runs, Flat or jumps to match the race; 2yo scale for 2yo races).
  Last / Avg 3 / Best / 2yo columns; colours ranked within the race: green = best, red = worst.
  Form lines (last 6 runs) from Sporting Life with our beaten lengths and figure. "Sort by rating", "Hide form",
  and the sun/moon button for light/dark.
  Not in v1: odds & trading analysis and sectionals (placeholders on the page). No probabilities yet.

GIT
  If Speeds is a git repo, add these two lines to Speeds\.gitignore:  node_modules/   and   web/.next/
