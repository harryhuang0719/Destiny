# Contributing

Contributions are welcome when they make calculations more transparent,
portable, testable, or honest.

Before opening a change:

1. Read `AGENTS.md` and the relevant methodology reference.
2. Work from a clean branch; never add personal charts, `.env`, kernels, or market data.
3. Add an independent regression fixture for calculation changes.
4. Run `python3 scripts/bootstrap.py --installer auto --llm --research --dev`
   and the full test suite.
5. Explain the convention, source, compatibility impact, and JSON schema impact.

Research contributions must preregister their test family, preserve null and
negative results, and avoid claims of causal efficacy or guaranteed alpha.
Swiss Ephemeris contributions require a prior project-level licensing decision.

Do not pass the complete parent environment to installer or Node children. Any
new private-index variable must be deliberately enumerated, excluded by default,
and covered by tests proving unrelated credentials and execution hooks stay out.

## Versions and releases

- Keep `pyproject.toml`, `scripts/__init__.py`, `package.json`,
  `package-lock.json`, `uv.lock`, `_meta.json`, `SKILL.md`, and `CHANGELOG.md`
  on the same package/Skill version.
- Version JSON contracts independently. A behavior-preserving refactor may bump
  the package without changing the main `2.0.0` or research `1.0.0` schemas.
- Release from a clean `vX.Y.Z` tag only after tests, package checks, repository
  hygiene, reproducible artifact checksums, and the changelog all agree. Keep the
  PEP 517 build backend exact-pinned so isolated builds do not silently drift.
