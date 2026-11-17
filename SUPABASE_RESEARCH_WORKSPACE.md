# Horse Research on Supabase — verified 17 November 2026

Project: `tkbhjbpiiierhjhjfjdd`
Private database schema: `horse_research`
Registered run: `challenger_v1_initial`

The schema and its 11 tables were created and verified through the connected Supabase project.
The schema is **not** used by the production FurlongIQ website. RLS is enabled on every table, and anonymous/authenticated application roles cannot access it. No public policies have been added (intentional for a private research workspace).

## Tables

- `runs`: immutable run identifiers, version, date cutoffs, status and parameters.
- `source_inventory`: source location and verified coverage; includes local sources that still need importing.
- `raw_races`: source clocks, distance and course metadata (currently empty).
- `raw_runner_results`: original finish/weight and age observations (currently empty).
- `raw_sections`: original per-runner split time and distance (currently empty).
- `standard_times`: challenger standard-time estimates (currently empty).
- `going_allowances`: challenger going estimates (currently empty).
- `result_figures`: challenger performance figures and quality flags (currently empty).
- `sectional_figures`: challenger individual split figures (currently empty).
- `comparison_metrics`: unbiased model comparisons (currently empty).
- `qa_findings`: initial issues logged, including raw input coverage and dangerous production uploader.

## Raw data source notes

GitHub `notdamien2009/horse` has `tools/sectionals.sql`: the **table definition** for compact `public.sectionals`, not raw timing data.
The GitHub `main` branch does not contain `data/` because `.gitignore` excludes it. The live Supabase database has processed `public.figs`, `public.pace`, and compact `public.sectionals`; Storage currently has no buckets.

Source scripts use these LOCAL files:

- `Speeds/data/rbd_core.csv.gz` (raw result adapter source, may vary locally)
- `Speeds/data/racing_history.sqlite` (Racing TV race result times)
- `Speeds/data/sectionals.sqlite` (Racing TV per-runner electronic split times)
- `Speeds/data/speed_v4/speed_figures.csv` and `distance_corrections.csv` (prepared baseline for challenger).

These raw source files have **not** been imported into private Supabase research tables yet. Do not label them uploaded or data-complete.

## Safety warning

`tools/upload_to_supabase.py` calls `wipe_site_data` before uploading local `data/site_cache.sqlite`. Production `public.figs` reaches 2026-11-13, with 433,256 rows at the point of audit. Running that existing uploader on an older or smaller local dataset can replace newer live data. Add a max-date/count preflight, backup and recoverable import before using it. Never use the production uploader to populate `horse_research`.

## Challenger repair

V1.1 corrects the `base_wt` crash: canonical `speed_v4/speed_figures.csv` does not export base weight, although the calculation uses it internally. The research adapter now reconstructs Flat=126 and Jumps=154 from code without modifying input files. Synthetic end-to-end tests pass; real input validation is still pending.

## Useful read-only SQL queries in Supabase SQL Editor

```sql
select * from horse_research.runs order by created_at desc;
select * from horse_research.source_inventory order by source_key;
select severity,area,finding,proposed_action,status from horse_research.qa_findings order by id;
select count(*) from horse_research.raw_sections;
```

The last count will remain zero until the verified raw sections are imported.
