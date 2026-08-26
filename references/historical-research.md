# Historical astronomy × financial markets

This layer implements the falsifiable backtracking portion of the accompanying
[research blueprint](../docs/Historical_Astronomical_Data_Financial_Markets_Research_Blueprint.md).
The blueprint is a research agenda. Destiny implements two deliberately
separate, audited paths: the v2.1-compatible univariate screen and the opt-in
v2.2 paired incremental model. Neither is the full 250–300-feature program.
Absent/disabled incremental configuration preserves result schema `1.0.0`;
enabled incremental configuration emits result schema `2.0.0`.

## What exists now

- Explicit local JPL SPK loading through optional `skyfield==1.55`; no implicit download.
- Geocentric apparent, ecliptic-of-date longitude/latitude/distance, RA/Dec,
  finite-difference longitude velocity, and retrograde flag.
- Body target metadata records the actual SPK label and NAIF IDs, including
  outer-planet system barycenters in `de440s`.
- Circular longitude encoding, directed/signed/minimum pair angles, relative
  velocity, harmonics `k=1..6`, Gaussian aspect scores, and Moon–Sun phase/illumination.
- An offline independent NASA/JPL Horizons golden for Sun, Moon, Mars
  barycenter, and Jupiter barycenter at three epochs, with explicit frame
  differences and hard tolerance ceilings.
- CSV feature builds with kernel and output SHA-256 manifests.
- A BYOD target contract with point-in-time timestamps and backward-only as-of joins.
- Legacy preregistered feature families, chronological split/purge,
  deterministic time-shift placebos, empirical p-values, familywise maxT, BH
  q-values, identifiability labels, and an append-only trial registry.
- An enabled incremental path with hashed long-form controls, identical M0/M2
  complete-case rows, train→validation ridge selection, train+validation refit,
  and a once-opened chronological test fold.
- Paired squared-loss inference with declared HAC, circular moving-block
  bootstrap, full-pipeline joint circular shifts, conservative robust max-p,
  and Bonferroni adjustment over the declared family.
- A small train-fitted threshold strategy only for explicitly tradable,
  non-overlapping return targets. Indicators and overlapping labels never emit
  a fake portfolio backtest.

## Deliberate exclusions

- Swiss Ephemeris / `pyswisseph`: AGPL or commercial dual licensing is not
  silently compatible with this MIT repository.
- Market-data downloaders and bundled history: availability and redistribution
  rights vary by vendor and series.
- Houses/Ascendant, topocentric exchange astrology, asteroids, sidereal systems,
  automatic feature mining, nonlinear ML, futures rolls, capacity, and live trading.
- Claims that supplied controls form a complete or adequate financial baseline;
  the controls catalog records provenance, not baseline sufficiency.
- Claims that a retrospective reconstruction is the same ephemeris vintage a
  historical trader possessed.

## Time policy

Skyfield calculates continuous astronomical instants using TT/TDB/UT1. UTC is
the financial join label from 1972 onward. Before 1972, strict mode refuses the
input; `--allow-pre-utc` produces an explicitly marked proleptic UTC label for
descriptive reconstruction. It must not be advertised as historically strict UTC.

Every target row must satisfy:

```text
observation_time_utc
  <= available_at_utc
  <= decision_at_utc
  <  execution_at_utc
  <= target_start_utc
  <  target_end_utc
```

The research runner fails on the first violation. Astro features are joined
using the latest timestamp at or before `decision_at_utc`; nearest/future joins
are forbidden. Market calendars, early closes, revisions, total returns,
delistings, futures rolls, and target construction remain the data owner's
responsibility and must be declared in the series catalog.

Incremental controls obey their own point-in-time rule:

```text
control.observation_time_utc <= control.available_at_utc <= decision_at_utc
```

For each declared control, the runner selects the greatest eligible observation
time and then the greatest eligible availability time. Stale values, a blank
latest vintage, or no eligible vintage drop the row. There is no future/nearest
join, interpolation, backfill, post-decision revision, or fallback to an older
value. M0 and M2 then use the same complete-case rows and split IDs.

## Required files

`series_catalog.json` must identify vendor/source/vintage, instrument type,
currency, venue, exchange timezone/calendar, price/target semantics, tradability,
methodology version, periods per year, and whether target intervals overlap.

`hypothesis.json` must freeze the hypothesis ID, registration time and commit,
mode, feature names/directions/effective periods, chronological boundaries,
embargo, maximum feature staleness, placebo count, seed, and optional cost.
Legacy mode is selected when `incremental_model` is absent or exactly
`{"enabled": false}`. An enabled incremental model requires
`hypothesis_schema_version: "2.0.0"` and every nested setting—there are no
incremental defaults.

The target CSV must include all six point-in-time columns plus the catalog's
`target_column` (default `target`). Dates without offsets and unordered rows fail.

The feature CSV must have its generated `<features>.manifest.json` sidecar (or
an explicit `--feature-manifest`). The runner verifies the CSV SHA-256 and embeds
kernel/frame/NAIF/runtime/time-policy metadata in every result.

Incremental mode additionally requires both:

- `controls.csv`, with the exact long header
  `control_id,observation_time_utc,available_at_utc,vintage_id,value`, strictly sorted by
  `(control_id, observation_time_utc, available_at_utc)`;
- `controls_catalog.json`, schema `2.0.0`, whose
  `controls_file_sha256` matches that exact CSV and whose ordered declarations
  identify family, vendor/source/vintage, unit, frequency, calendar/timezone,
  revision policy, methodology, and maximum staleness.

Only an empty CSV field means missing. `NA`, `NaN`, and infinities are invalid.
Non-revisioned controls permit one row per observation time; revisioned controls
must preserve each as-published availability timestamp. The hypothesis's ordered
`control_ids` must exist in both files.

See [example research configs](../examples/research/) for the exact shape.

## Incremental M0 versus M2

The registered question is narrow: on the identical test rows, does M2 reduce
squared prediction loss relative to M0?

- M0 contains every ordered, non-constant preregistered control.
- M2 contains those identical M0 columns followed by every ordered,
  non-constant preregistered astronomy feature.
- Population means/scales (`ddof=0`) are fitted on train rows only for
  validation, then on train+validation for the final refit. Targets are not
  standardized. There is no imputation, clipping, winsorization, interaction,
  feature screening, or test-dependent transform.
- Each model chooses its own ridge alpha by validation MSE from the same
  registered increasing grid and fit budget; ties choose the largest alpha.
  Test outcomes never influence selection.
- Columns constant on observed train are dropped once and remain dropped during
  validation, refit, test, coefficients, and prediction hashing.

Preflight uses the worst-case declared dimension
`p = controls + astronomy` before constant removal. It requires at least
`max(60, 2*(p+1))` train rows, `max(30, p+1)` validation rows, and
`max(40, hac_lag+2, 4*block_length)` test rows. The complete-case placebo base
must contain at least 100 rows. Declared dimensions and work estimates are
checked before model allocation.

The primary row statistic is
`d_t = loss_M0,t - loss_M2,t`; positive mean `d` favors M2. This is a paired
predictive-loss comparison conditional on the exact supplied controls, sample,
ridge contract, and inference procedures—not proof that all ordinary financial
information was controlled.

NumPy is a direct research dependency because this path directly promises
float64 population standardization and `numpy.linalg.solve`, with condition and
relative-residual failure gates. Imports remain lazy, so core chart calculation
does not acquire a NumPy dependency.

## Three null procedures, one conservative qualification

The incremental result reports three separately declared one-sided procedures:

1. Newey-West HAC on `d_t`, using the registered Bartlett lag. Overlapping
   half-open test targets require enough lag coverage.
2. Circular moving-block bootstrap: an uncentered distribution supplies the
   percentile interval, while the centered `d_t - mean(d)` distribution supplies
   the null p-value. It does not capture full model-selection uncertainty.
3. Full-pipeline joint circular-shift placebo. From the complete cyclic group
   `C_N={0,...,N-1}`, nonzero shifts rotate all astronomy columns together while
   controls, targets, timestamps, and split membership stay fixed. Every chosen
   shift re-detects shifted-train astronomy constants, searches the complete
   alpha grid, refits M2, and re-evaluates paired test loss. The base rows include
   embargo-excluded complete cases; failed shifts fail the trial.

The robust null is the union of the HAC, block, and shift component nulls, so
`p_robust = max(p_HAC, p_BLOCK, p_SHIFT)` is a conservative
intersection-union max-p construction. If a component p-value is null, the
robust and family p-values are null rather than invented. The declared family
uses `p_family = min(1, family_size * p_robust)`.

That Bonferroni result is conditional on the truth and completeness of the
declared family. A local file cannot prove that all related trials were declared
or that `family_index` is globally unique. `threshold_met` is therefore a
diagnostic only and never upgrades the evidence label.

The incremental manifest contributes one joint M0-vs-M2 test. Its robust and
Bonferroni values are separate from the legacy per-feature maxT/BH outputs,
which remain visible as descriptive/univariate diagnostics.

## Provenance and lifecycle

Incremental mode snapshots and hashes all seven inputs—feature CSV/manifest,
target CSV/catalog, hypothesis, controls CSV/catalog—before the trial lifecycle
begins. After safe-path, collision, and workload checks, every opened test emits
`STARTED` and then exactly one `COMPLETED` or `FAILED` registry event.

The chronological prediction payload uses canonical row IDs and float hex
strings and receives an in-run integrity SHA-256. It is not a promise of
bit-identical predictions across BLAS libraries or platforms; cross-platform
validation uses frozen numerical tolerances.

## Evidence labels

- `EXPLORATORY`: ordinary retrospective exploration.
- `PSEUDO_OOS_ONLY`: chronological historical holdout that has already been
  available to researchers; useful process evidence, not a sealed confirmation.
- `PROSPECTIVE_DECLARED_UNVERIFIED`: the manifest declares that data accumulated
  after a registration point, and local Git/time gates passed, but this repository
  has no independent timestamp/notary service that can prove the declaration.
- Per-feature `DESCRIPTIVE`: training covers fewer than three stated cycles or
  test covers fewer than one; a p-value must not rescue an unidentified feature.
- Incremental evaluation mirrors the top-level status as
  `EVALUATED_EXPLORATORY`, `EVALUATED_PSEUDO_OOS_ONLY`, or
  `EVALUATED_PROSPECTIVE_DECLARED_UNVERIFIED`.

Neither path emits `CONFIRMATORY_PASS` or a self-certified prospective pass.
Even an incremental threshold diagnostic needs an independently complete trial
family, stronger alternative null universes, versioned market calendars,
broader independent ephemeris validation, stable eras, economic-cost sensitivity,
and genuinely future sealed evidence before stronger language is warranted.

## Data semantics that must not be blurred

- A yield series is not a bond total return.
- VIX is an indicator, not a directly held instrument.
- WTI spot is not a futures roll strategy; non-positive prices invalidate log returns.
- DXY is a proprietary ICE index and is not interchangeable with a Federal Reserve dollar index.
- An index level is not automatically an executable asset.

Destiny intentionally requires BYOD targets so these choices cannot hide behind
a convenient ticker downloader.

## Research ethic

The legacy path must be able to conclude: **no stable preregistered univariate
association was found**. The incremental path must likewise be able to conclude:
**the supplied astronomy family did not reduce OOS squared loss beyond this
declared M0 baseline**. Report every preregistered feature, null, failed shift,
sample/drop count, component p-value, correction, and limitation. A small or
adjusted p-value is neither causality, astrology validation, tradable alpha, nor
investment advice.
