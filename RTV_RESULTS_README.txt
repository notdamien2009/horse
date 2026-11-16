FurlongIQ - Racing TV results backfill
======================================

What it does
------------
Pulls UK and Irish race results from Racing TV (including each horse's
in-running / close-up comment) and adds them to the existing Sporting Life
history database:

  data\racing_history.sqlite

New rows use the same races / runners tables and field names, and are tagged
source=rtv. Existing Sporting Life rows are never changed or deleted. Races
already present (same date, course and off time) are skipped.

Default range: 2023-12-01 to yesterday. Sporting Life already covers most of
that December, so those days are listed and skipped, then the gap from
January 2024 onwards is filled.

How to run
----------
Double-click  RUN_RTV_RESULTS.bat
The window stays open. Leave it running.

How to stop and resume
----------------------
To stop: create an empty file called

  data\rtv_results_backfill\STOP

or close the window (safe after the current race finishes writing).

To resume: delete the STOP file if you created one, then double-click
RUN_RTV_RESULTS.bat again. It picks up where it left off and skips races
already saved.

How to check progress
---------------------
Double-click  CHECK_RTV_RESULTS.bat

It shows races saved, latest date, missing-dates count, and the last log
lines, then waits so the window stays open.

Missing dates
-------------
If a race or a whole day fails, the backfill logs it and carries on. The list
is here:

  data\rtv_results_backfill\MISSING_DATES.csv

Progress log:  data\rtv_results_backfill\collector.log

Backups
-------
Before the first write of each run, a timestamped copy is made next to the
database, e.g.

  data\racing_history.backup-YYYYMMDD-HHMMSS.sqlite

Notes
-----
Official ratings (OR) are not published on the Racing TV results API (only a
Timeform figure, stored as timeform_rating on the runner). Prize money is
stored as prize_raw when it appears in the race title.
