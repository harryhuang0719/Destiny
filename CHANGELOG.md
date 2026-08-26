# Changelog

Destiny follows semantic versioning for the package and Skill. JSON contracts
have their own versions and change only when their wire format changes.

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
