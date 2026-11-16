SPEEDS RACING SITE - v1
=======================
Today's UK & Irish race cards with form, our speed figures and ratings. Runs on this PC only (http://localhost:8050).

FILES (all inside C:\Users\PC Deals\Desktop\Speeds)
  GET_TODAYS_CARDS.bat   - downloads today's cards from Sporting Life into data\cards.sqlite (about 1 minute,
                           3 seconds between pages). Run it each morning; run it again later for non-runners/odds.
                           For another day: GET_TODAYS_CARDS.bat --date 2026-11-17 (only works once SL has published it).
  RUN_SITE.bat           - starts the site and opens it in your browser. Close the black window to stop it.
  tools\sl_cards.py      - the card scraper.
  site\app.py            - the web server (standard Python only, nothing to install).
  site\figcache.py       - builds data\site_cache.sqlite from the speed figures.
  site\static\           - the page itself (index.html, app.js, style.css).

DAILY USE
  1. Double-click GET_TODAYS_CARDS.bat and wait for "Saved ... runners".
  2. Double-click RUN_SITE.bat. The page opens on the next race to run.

WHERE THE FIGURES COME FROM
  The site uses data\speed_v3\speed_figures.csv if it exists, otherwise data\speed_v2\speed_figures.csv.
  The first start (or the first start after the CSV changes) builds data\site_cache.sqlite, which takes about a minute.
  After that it starts instantly. To force a rebuild, delete data\site_cache.sqlite.

READING A RACE CARD
  - One tab per race, grouped by meeting (time + course). Faded tabs have already run.
  - Rank / TOP RATED: runners ranked on "Best 3" = average of the best 3 figures from the last 12 runs
    (Flat figures for Flat races, jumps figures for jumps races, all runs if the horse has none of that type).
  - Last = most recent figure, Avg 3 = average of the last 3 figures, Best = best figure ever, 2yo = best figure on
    the 2-year-old scale (shows once v3 figures are in place).
  - Colours are ranked within the race: green = best in this race, red = worst. Figures in the form lines are
    coloured against this race's ratings, so a green run is a run good enough to win this race.
  - Form lines (last 6 runs) come from Sporting Life; the beaten lengths and figure come from our figures.
    A "-" figure means no figure (pulled up, fell, beaten too far, bad time, or a run not in our data, e.g. abroad).
  - Headgear in orange; a "1" after it means first time.
  - "Sort by rating" re-orders the card by rank; "Hide form" gives a compact view; the half-moon button switches light/dark.

NOT IN v1 (placeholders on the page)
  Odds and trading analysis, and sectionals - coming later.
