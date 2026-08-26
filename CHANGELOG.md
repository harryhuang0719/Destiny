# Changelog

Destiny follows semantic versioning for the package and Skill. JSON contracts
have their own versions and change only when their wire format changes.

## [2.2.0] - 2026-08-26

> This section describes the `2.2.0` source candidate. It becomes a published
> GitHub Release only after the matching `v2.2.0` tag workflow succeeds.

### Added

- Added an opt-in incremental research path with strict long-form point-in-time
  controls and hashed controls catalogs.
- Added paired ridge models on identical rows and folds: M0 uses all declared
  controls, while M2 adds every preregistered astronomy feature under the same
  alpha grid and fit budget.
- Added Newey-West HAC inference, circular moving-block bootstrap, and a full
  M2-pipeline joint circular-shift placebo over the declared cyclic group.
- Added conservative union-null max-p aggregation and Bonferroni family
  adjustment, with explicit limits on what the local runner can certify.
- Added validator-clean controls/hypothesis templates and a complete synthetic
  end-to-end incremental demo generator.

### Dependencies

- NumPy is now a direct, exact-pinned `research`/`all` dependency because the
  incremental contract directly relies on float64 arrays and `numpy.linalg`.
  Python-specific pins keep resolution explicit; the core install is unchanged.

### Compatibility and evidence boundary

- With `incremental_model` absent or exactly `{ "enabled": false }`, the legacy
  univariate path and result schema remain `1.0.0`.
- Enabled incremental hypotheses require hypothesis schema `2.0.0`, both
  controls inputs, and emit research result schema `2.0.0`. Core result schema
  remains `2.0.0`; astronomy schema remains `1.0.0`.
- A positive loss differential or adjusted threshold diagnostic does not change
  the evidence label. This release never emits `CONFIRMATORY_PASS` and does not
  claim causality, a complete financial baseline, stable alpha, or live-trading
  readiness.

## [2.1.0] - 2026-08-26

### Changed

- Split the command-line, provider, output, ephemeris, feature, contract,
  statistics, registry, and research-runner boundaries into focused modules.
  Existing commands, exit codes, and JSON behavior remain compatible.
- Added health profiles: `doctor --core`, `doctor --research`, and
  `doctor --all`; plain `doctor` remains equivalent to `--all`.
- Added `bootstrap.py --installer auto|uv|pip`. Auto mode prefers a valid frozen
  uv lock and otherwise explains why it falls back to pip.
- Added explicit `--allow-private-index-env` support. Installer children use an
  exact environment allowlist by default; the opt-in forwards only enumerated
  pip/uv private-index environment variables and named username/password
  credentials. User-level pip/uv config-file discovery is unchanged.
- Narrow doctor profiles now leave Node/iztro `not_checked`; default/all performs
  strict pinned-version metadata validation and a bounded static require smoke.
- Added a tag-driven release path with an exact-pinned build backend, two
  isolated byte-identical wheel/sdist builds, `SHA256SUMS`, and GitHub/Sigstore
  build provenance.
- Expanded the regression baseline to 122+ collected tests across the
  deterministic engines, agent-safety boundaries, and historical research.

### Compatibility and evidence boundary

- The distribution and Skill version is now `2.1.0`. The main result JSON
  schema remains `2.0.0`; astronomy and research schemas remain `1.0.0`.
- Historical research remains a preregistered **univariate association MVP**.
  This release does not claim financial-control-adjusted incremental evidence,
  a paired M0-vs-M2 result, causal efficacy, or production-trading readiness.

[2.1.0]: https://github.com/harryhuang0719/Destiny/releases/tag/v2.1.0
[2.2.0]: https://github.com/harryhuang0719/Destiny/releases/tag/v2.2.0
