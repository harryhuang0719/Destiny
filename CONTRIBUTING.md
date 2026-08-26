# Contributing

Contributions are welcome when they make calculations more transparent,
portable, testable, or honest.

Before opening a change:

1. Read `AGENTS.md` and the relevant methodology reference.
2. Work from a clean branch; never add personal charts, `.env`, kernels, or market data.
3. Add an independent regression fixture for calculation changes.
4. Run `python3 scripts/bootstrap.py --llm --research --dev` and the full test suite.
5. Explain the convention, source, compatibility impact, and JSON schema impact.

Research contributions must preregister their test family, preserve null and
negative results, and avoid claims of causal efficacy or guaranteed alpha.
Swiss Ephemeris contributions require a prior project-level licensing decision.
