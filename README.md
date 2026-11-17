# FurlongIQ Challenger V1 — result and sectional speed figures

**Status: research prototype, input adapter patch v1.1. NOT approved to replace the live FurlongIQ ratings.**

**V1.1 correction:** Real `speed_v4/speed_figures.csv` files do not contain `base_wt`. It is now derived from the V3/V4 method constants: Flat 126 lb; Hurdle, Chase and NHF 154 lb. No existing V4 file is rewritten. The regression test intentionally omits this column to mirror production.

This package is deliberately isolated from `tools/speedfig_v3.py`, `tools/speedfig_v4.py`, `tools/sectionals_v12.py`, `BUILD_MASTER.bat`, `data/site_cache.sqlite`, the live website, and Supabase. It **never uploads, writes to SQLite or calls a website**. The existing AI can continue running V4/V12 without conflict.

## Installation

Copy the following files into the existing horse repository (`notdamien2009/horse`), preserving their paths:

- `tools/challenger_figures.py`
- `tests/test_challenger.py`
- `RUN_CHALLENGER_PILOT.bat`
- `RUN_CHALLENGER_FULL.bat`

**Do not replace or rename any existing speed figure scripts.** The new files have unique names.

Install Python requirements (normally already installed for FurlongIQ):

```bat
py -3 -m pip install numpy pandas
```

Verify the required source files are available **locally**:

```text
data/speed_v4/speed_figures.csv

data/speed_v4/distance_corrections.csv

data/sectionals.sqlite                  optional for results; required for sectional figures
```

Create those sources with the **existing** `BUILD_MASTER.bat` only if they are missing. That existing build should be allowed to finish before starting the challenger; don't run both against changing input files simultaneously. The `data/` directory is Git-ignored: a Git push does not upload these databases.

## Trial run

Double-click `RUN_CHALLENGER_PILOT.bat`, or run:

```bat
py -3 tools\challenger_figures.py --root . --train-end 2025-12-31 --max-rtv-races 10000
```

This trains standards and pars on result history **before 1 Jan 2026**, then labels 2026 as the held-out period. The sectional pilot uses at most 10,000 matched Racing TV races, selecting historical training and later holdout races. It leaves `data/speed_v4`, `data/sectionals_v12`, the database and website untouched.

When QA passes on your real data, you can remove the cap:

```bat
py -3 tools\challenger_figures.py --root . --train-end 2025-12-31
```

The full sectional mode can use significant RAM on a large `sectionals.sqlite`; try the bounded pilot first. The script does not modify the other AI's ratings.

## What the figures mean

### 1. Result speed figure (absolute)

The challenger fits its **own** time standards (35th percentile, shrinkage for sparse course/trip combinations). The race winner's clock is independently selected from the candidates already recorded in V4's distance audit. If two clocks disagree without a corroborating pair, the race is quarantined rather than choosing whichever matches a class rating. Exact Racing TV yards are used where available.

For each finisher, the adjusted figure uses this form:

`100 + (new standard time at actual yards + new going allowance × exact furlongs - verified winner clock) × pounds_per_second - effective beaten lengths × pounds_per_length + (effective weight - base weight)`

Class affects fitting the standard and going prior, **not** a discretionary horse rating boost. The new standard and going estimates are fitted on the training period only; a meeting's own race is excluded from its meeting adjustment. Any missing or contested clock stays flagged.

**What is independent:** the race-clock reconciliation policy, standard times, going estimates and final result rating are newly calculated. **What is shared:** course/distance/horse joins, weight-for-age conversion, approximate lengths-per-second and raw source candidates come from the V4 prepared source tables. This is a *methodology challenger*, not a fully separate source-data pipeline.

### 2. Sectional clock figure (absolute)

When every sectional is complete, the winner's summed sectional clock is consistent with the result clock, and the horse's identity joins correctly, the challenger independently times each runner from the electronic **sum of its sectionals**. It then gives that runner an absolute figure against the newly fitted race standard. This avoids deriving every runner time from an approximate beaten-length conversion.

`sectional_clock_fig` can be directly compared with `challenger_fig` and `weighted_fig`; the `sectional_clock_delta` shows the change from using actual individual time rather than estimated beaten lengths. Without a verified winner sectional clock, this figure is **not published**.

### 3. Sectional split index (pace distribution)

`section_index` uses a different, intentionally pace-normalised measure. Each section is compared with historical *winner pace shapes* for course + code/surface + distance, using training dates only. Sparse course/trip histories shrink towards broader par shapes. Expected section times are renormalised to each runner's total sectional clock so **split differences across the race sum to zero**.

- 100 = typical pace distribution for that part of the race.
- 103 = about 3% quicker relative to the runner's own race time and that section's par.
- 97 = about 3% slower relative to the same reference.

A 103 **is not** equivalent to a 103 overall speed figure. It measures how the horse distributed its performance. `late_index` is the last two furlongs on Flat/AW, last three over jumps; `early_index` covers the remainder. `sectional_style` describes the pattern, not a guaranteed tactical advantage.

**No automatic 'deserved performance upgrade' is added in V1.** An upgrade should only be introduced after historical out-of-time tests prove it improves predictions without systematically exaggerating closing bursts.

## Output: `data/challenger_v1/`

| File | Meaning |
| --- | --- |
| `result_speed_figures.csv.gz` | All runners: V4 rating alongside new result rating, sectional-clock rating, split indices, quality flags |
| `standard_times.csv` | New per-course, surface, code and trip standards, sample sizes and shrinkage |
| `result_standard_comparison.csv.gz` | Race-by-race new vs V4 standard/going differences |
| `race_clock_and_going_audit.csv.gz` | Clock candidates, distance provenance, meeting going allowance and disputed records |
| `class_calibration.csv`, `going_priors.csv` | Historical training calibrations |
| `sectional_splits.csv.gz` | Per-furlong actual times, expected times, split indexes and sample counts |
| `sectional_runner_summary.csv.gz` | Per-runner early/late indices and winner-clock verification |
| `head_to_head_picks.csv` | Same-race ranking comparison using past figures only (exploratory) |
| `audit.json` | Counts, coverage, training cutoff, issues and exploratory win rates |

Sectional files are omitted if no clean sectionals exist.

## How to evaluate fairly

1. Freeze a **source snapshot** at a known date (for example, results up to 12 September 2026, if that is the true latest date present). Confirm race counts and missing data.
2. Calibrate both systems using the **same historical training period**. Do **not** permit either to use the eventual test races to estimate standard times, going priors, sectional pars or pace boosts.
3. For each 2026 race, generate a pre-race ranking from each horse's previously known ratings. Use the same runners and compare only races where both models had eligible runners.
4. Compare winner hit rate, race-level log loss and Brier score **once model probabilities have actually been calibrated**, ranking correlation with subsequent performances, and market-relative results using independently captured BSP. Segment by Flat turf, AW, hurdles/chases, distance band, going, and age cohort (especially 2yos).
5. Use date-blocked confidence intervals and record the winner on **out-of-sample results**, not by inspecting historical best-case examples. Fix methodology or parser defects before adopting any figure.

**Limitation of the included pick report:** the existing V4 `weighted_fig` file may already incorporate standards fitted using future test races. Its ratings are therefore an exploratory reference, **not** a clean out-of-time competitor. A production-quality showdown requires a frozen V4 recalibration and scoring process, plus per-horse historic point-in-time ratings. It would be misleading to declare a winner from this prototype's `head_to_head_picks.csv` alone.

### Known V1 boundaries

- Not yet calibrated on your actual horse history (the complete local `data/` tree is unavailable in this conversation).
- The independent method still reuses V4 factual parsing and lengths/weight conventions, which can share upstream errors.
- No special standalone two-year-old-only scale has yet been validated; compare that age cohort separately.
- Course layouts are inherited from the prepared race source; new layout splits are not inferred automatically.
- Pace-shape pars rely on clean Racing TV splits; no splits means no sectional numbers.
- The training standard uses a course/trip quantile and shrunk historical class/going priors. It is a candidate methodology, **not a proven unbiased standard time**.
- Numeric differences from the existing V4 scale are expected and do not by themselves establish which is superior.

## Tests

```bat
py -3 -m unittest discover -s tests -p test_challenger.py -v
```

Three automated tests cover clock agreement/quarantine, robust quantiles, and an end-to-end synthetic 400-race/2,000-runner fixture with 12,000 split rows. Synthetic data **cannot** prove predictive value on real races.
