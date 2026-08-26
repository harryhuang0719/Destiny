# Historical astronomy × financial markets

This layer implements the falsifiable backtracking portion of the accompanying
[research blueprint](../docs/Historical_Astronomical_Data_Financial_Markets_Research_Blueprint.md).
The blueprint is a research agenda; this first release is a conservative,
auditable MVP rather than the full 250–300-feature program.

## What exists now

- Explicit local JPL SPK loading through optional `skyfield==1.55`; no implicit download.
- Geocentric apparent, ecliptic-of-date longitude/latitude/distance, RA/Dec,
  finite-difference longitude velocity, and retrograde flag.
- Body target metadata records the actual SPK label and NAIF IDs, including
  outer-planet system barycenters in `de440s`.
- Circular longitude encoding, directed/signed/minimum pair angles, relative
  velocity, harmonics `k=1..6`, Gaussian aspect scores, and Moon–Sun phase/illumination.
- CSV feature builds with kernel and output SHA-256 manifests.
- A BYOD target contract with point-in-time timestamps and backward-only as-of joins.
- Preregistered feature families, chronological split/purge, deterministic
  time-shift placebos, empirical p-values, familywise maxT, BH q-values,
  identifiability labels, and an append-only trial registry.
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

## Required files

`series_catalog.json` must identify vendor/source/vintage, instrument type,
currency, venue, exchange timezone/calendar, price/target semantics, tradability,
methodology version, periods per year, and whether target intervals overlap.

`hypothesis.json` must freeze the hypothesis ID, registration time and commit,
mode, feature names/directions/effective periods, chronological boundaries,
embargo, maximum feature staleness, placebo count, seed, and optional cost.

The target CSV must include all six point-in-time columns plus the catalog's
`target_column` (default `target`). Dates without offsets and unordered rows fail.

The feature CSV must have its generated `<features>.manifest.json` sidecar (or
an explicit `--feature-manifest`). The runner verifies the CSV SHA-256 and embeds
kernel/frame/NAIF/runtime/time-policy metadata in every result.

See [example research configs](../examples/research/) for the exact shape.

## Evidence labels

- `EXPLORATORY`: ordinary retrospective exploration.
- `PSEUDO_OOS_ONLY`: chronological historical holdout that has already been
  available to researchers; useful process evidence, not a sealed confirmation.
- `PROSPECTIVE_DECLARED_UNVERIFIED`: the manifest declares that data accumulated
  after a registration point, and local Git/time gates passed, but this repository
  has no independent timestamp/notary service that can prove the declaration.
- Per-feature `DESCRIPTIVE`: training covers fewer than three stated cycles or
  test covers fewer than one; a p-value must not rescue an unidentified feature.

This MVP never emits `CONFIRMATORY_PASS` or a self-certified prospective pass. A strong claim would also require
versioned market calendars, matched null universes that rerun the complete
selection pipeline, block/HAC inference, independent reference ephemeris
validation, paired M0-vs-M2 evaluation, stable eras, economic-cost sensitivity,
and prospective evidence.

## Data semantics that must not be blurred

- A yield series is not a bond total return.
- VIX is an indicator, not a directly held instrument.
- WTI spot is not a futures roll strategy; non-positive prices invalidate log returns.
- DXY is a proprietary ICE index and is not interchangeable with a Federal Reserve dollar index.
- An index level is not automatically an executable asset.

Destiny intentionally requires BYOD targets so these choices cannot hide behind
a convenient ticker downloader.

## Research ethic

The MVP must be able to conclude: **no stable preregistered univariate
association was found**. It does not yet identify conditional or incremental
information because financial controls and paired M0-vs-M2 models are not
implemented. Report every preregistered feature, null, failure, sample count,
correction, and limitation. A small p-value is neither causality nor investment advice.
