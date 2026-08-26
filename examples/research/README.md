# Research input templates

These files define contracts; they do not contain market data or a claimed result.

1. Build a JPL feature CSV with `destiny history build`.
2. Copy `series_catalog.example.json` and replace every placeholder with the
   exact series/instrument semantics and source vintage.
3. Copy `hypothesis.example.json`, freeze the feature family and split before
   opening the test result, and record the actual registration commit.
4. Produce a target CSV with the header in `target_schema.csv`. Every row must
   satisfy the point-in-time inequality documented in the catalog.
5. Run `destiny history research` with an append-only trial registry path.

The example is deliberately labeled `pseudo_oos`. Changing it to `prospective`
does not make old data prospective; even genuinely new observations receive the
label `PROSPECTIVE_DECLARED_UNVERIFIED` until an independent seal exists.
