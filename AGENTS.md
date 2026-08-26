# Contributor and agent guide

Destiny has two deliberately separate layers:

1. Offline traditional calendar/chart engines in `scripts/*_engine.py`.
2. Optional, falsifiable historical astronomy research in
   `scripts/historical_research.py` and `scripts/history_cli.py`.

Read `SKILL.md` for product behavior and the relevant file under `references/`
before changing a convention.

## Setup and verification

```bash
python3 scripts/bootstrap.py --llm --research --dev
./destiny doctor --json
.venv/bin/python -m pytest -q
npm audit --omit=dev
```

On Windows use `.venv\Scripts\python.exe` and `destiny.cmd` or `destiny.ps1`.
Tests must not make live LLM calls. The JPL integration test runs only when
`DESTINY_TEST_KERNEL` points to a local SPK file.

## Non-negotiable invariants

- JSON mode writes exactly one JSON document to stdout. Diagnostics go to stderr.
- Core operation is offline. External LLM use requires explicit provider choice.
- Never search the home directory for `.env` or pass the full parent environment
  to Node.
- Never construct JavaScript or shell source from user input. Zi Wei uses the
  static stdin bridge; questions use `--question-stdin`/`--question-file`.
- Retain minute/second precision. Record true-solar-time source and result.
- Preserve Bazi sect and Zi Wei late-Zi conventions in output.
- Do not call I Ching output full Wen-Wang Najia or call Zeji a comprehensive ranking.
- Historical timestamps are aware UTC labels; pre-1972 use needs an explicit policy.
- Historical joins are backward as-of only. Every target row must satisfy the
  point-in-time inequality in `references/historical-research.md`.
- Market data, JPL kernels, generated charts, trials, and research results never enter Git.
- Swiss Ephemeris/pyswisseph is not an allowed dependency without a deliberate
  repository-wide license decision.
- A null result is a first-class result. Never hide failed hypotheses or tune on test.

## Change checklist

- Add a regression test for every corrected calculation or boundary.
- For algorithm changes, cite the convention and add an independent golden fixture.
- Bump `schema_version` for incompatible JSON changes.
- Keep `package.json`, lockfile, pyproject, `_meta.json`, README, and SKILL versions aligned.
- Run core, Node, historical synthetic, security, and pure-JSON tests.
- Inspect `git ls-files` for secrets, caches, kernels, market data, or personal reports.
- Keep README claims narrower than the evidence.
