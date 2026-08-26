# Research input examples

These files are public contracts and synthetic demonstrations. They contain no
market history, proprietary vendor data, personal paths, or claimed result.

## Which example should I use?

- `series_catalog.example.json`, `hypothesis.example.json`, and
  `target_schema.csv` describe the legacy schema-1.0 univariate path.
- `controls.example.csv` and `controls_catalog.example.json` are a short,
  validator-clean example of the long point-in-time controls contract.
- `hypothesis.incremental.example.json` contains every required setting for the
  schema-2.0 paired M0/M2 path. Replace its registration, dates, features,
  controls, and family declaration before a real study.
- `generate_incremental_demo.py` creates a complete synthetic dataset large
  enough to run the incremental pipeline end to end.

The tracked controls catalog contains the SHA-256 of the canonical LF repository
bytes for the tracked controls CSV; `.gitattributes` preserves those bytes on
every platform. If either file changes, recompute the CSV hash and update the
catalog before validation. Empty control values are represented only by an empty
final field; strings such as `NA`, `NaN`, and `inf` are invalid.

## Run the complete synthetic demo

The generator refuses to reuse an existing directory. `data/` is gitignored:

```bash
python3 examples/research/generate_incremental_demo.py \
  --out data/incremental-demo

./destiny history research \
  --features data/incremental-demo/features.csv \
  --feature-manifest data/incremental-demo/features.csv.manifest.json \
  --targets data/incremental-demo/targets.csv \
  --catalog data/incremental-demo/series_catalog.json \
  --hypothesis data/incremental-demo/hypothesis.json \
  --controls data/incremental-demo/controls.csv \
  --controls-catalog data/incremental-demo/controls.catalog.json \
  --trial-registry data/incremental-demo/trials.ndjson \
  --out data/incremental-demo/result.json
```

The generated astronomy columns are periodic synthetic signals, not JPL
positions. The target deliberately contains a synthetic astronomy component so
the example exercises the machinery; it is not market evidence.

## Long controls contract

The CSV header is exact:

```text
control_id,observation_time_utc,available_at_utc,vintage_id,value
```

Rows are strictly increasing by `(control_id, observation_time_utc,
available_at_utc)`. Every timestamp includes an offset and satisfies
`observation_time_utc <= available_at_utc`. A non-revisioned control has at most
one row per observation time. For `as_published_revisions`, each later vintage
uses the same observation time and a later availability time.

At each target decision, Destiny selects the greatest eligible observation and
then its latest eligible vintage. It never joins forward, interpolates,
backfills, or falls back from a blank latest vintage. M0 and M2 use the same
complete-case rows.

## Adapt the templates to real BYOD data

1. Build a JPL feature CSV with `destiny history build`, retaining its generated
   manifest and kernel hash.
2. Produce targets using `target_schema.csv`; each row must satisfy
   `observation <= available <= decision < execution <= target_start < target_end`.
3. Export controls in the long format above and preserve source/revision
   provenance in the controls catalog.
4. Hash the exact controls snapshot (`sha256sum` on Linux or `shasum -a 256` on
   macOS) and place the lowercase digest in `controls_file_sha256`.
5. Freeze the incremental hypothesis, including the full alpha grid, HAC lag,
   circular-block bootstrap, full-pipeline placebo, and Bonferroni family,
   before opening the test result.
6. Run with both `--controls` and `--controls-catalog`; providing only one fails,
   and providing either while incremental mode is disabled also fails.

`mode: "pseudo_oos"` is deliberate. Changing it to `prospective` does not make
old data prospective; even genuinely new observations remain
`PROSPECTIVE_DECLARED_UNVERIFIED` without an independent seal.
