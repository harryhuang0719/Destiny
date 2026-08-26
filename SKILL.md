---
name: destiny
description: Use for Chinese calendar conversion, Bazi, Zi Wei Dou Shu, I Ching hexagram casting, compatibility, annual themes, almanac date screening, or auditable historical astronomy/financial-market research. Treat results as cultural interpretation or exploratory statistics, not medical, legal, investment, or life-decision advice; this is not a full Wen-Wang Najia implementation.
license: MIT
metadata:
  version: "2.2.0"
  openclaw:
    emoji: "🔮"
    homepage: "https://github.com/harryhuang0719/Destiny"
    requires:
      anyBins: ["python3", "python", "py"]
---

# Destiny

Use deterministic engines to calculate first, then interpret. Keep chart facts,
traditional interpretation, and uncertainty visibly separate.

## Locate and verify

Resolve `DESTINY_ROOT` as the directory containing this `SKILL.md`; never assume
the current working directory or a user-specific absolute path.

- OpenClaw exposes this directory as `{baseDir}`.
- Claude Code exposes it as `${CLAUDE_SKILL_DIR}`.
- Codex includes the skill's file location in its skill catalog; use that parent directory.

Run the platform launcher before the first calculation: `DESTINY_ROOT/destiny`
on macOS/Linux, `DESTINY_ROOT/destiny.ps1` or `destiny.cmd` on Windows. Select
the narrowest health profile: `doctor --core --json` for calendar/Bazi/I Ching,
`doctor --research --json` for the Skyfield research runtime, or
`doctor --all --json` when Zi Wei is needed. Plain `doctor` remains equivalent
to `--all`; the research check never downloads or validates a JPL kernel.
Core/research profiles do not probe or spawn Node/iztro and report those checks
as `not_checked`. All mode strictly verifies the pinned iztro metadata and a
static `require('iztro')` smoke in a minimal OS-only environment.

If the environment is missing, install only when the user asked to deploy/setup;
use `python3 .../scripts/bootstrap.py --installer auto` on macOS/Linux or
`py -3 ...\scripts\bootstrap.py --installer auto` on Windows. Auto mode uses a
valid frozen uv lock when uv is available and otherwise falls back to pip with an
explanation. Use `--installer uv` or `--installer pip` only when the user requests
that path. Add `--research`, `--llm`, or `--dev` only for the capability actually
requested. Never download a JPL kernel or market data implicitly.

The bootstrap summary exposes a machine-safe `next_argv` string array. Pass it
directly to the process runner without shell joining or interpolation; `next` is
the quoted human-readable display form. `--skip-node` only skips this run's npm
installation and does not remove an existing `node_modules` directory.

Bootstrap gives pip/uv an exact operational environment allowlist by default;
unrelated secrets, injection settings, and private-index environment variables
are not inherited. This is not config-file isolation: retained OS directories
can still let pip/uv discover user-level configuration files. Add
`--allow-private-index-env` only when the user explicitly asks to forward the
parent process's private-index environment variables. That opt-in forwards only
the enumerated pip/uv variables and named
`UV_INDEX_<NAME>_USERNAME|PASSWORD` credentials, never the complete parent
environment.

## Privacy and safe execution

- Birth date, location, relationship details, and questions are personal data.
  Do not persist, publish, or send them elsewhere without the user's request.
- The default engine is offline. Do not add `--llm` unless the user explicitly
  chooses a provider and understands the relevant data leaves the machine.
- Never interpolate a user's question into a shell command. Run an I Ching
  command with `--question-stdin` and pass the exact text through the execution
  tool's stdin channel. If stdin is unavailable, create a temporary UTF-8 file
  with a filesystem tool and use `--question-file`.
- Never treat a chart or research result as a basis for medical, legal,
  financial, or other high-stakes decisions.

Read [privacy and safety](references/privacy-safety.md) before external LLM use
or when a request includes sensitive personal data.

## Choose a mode

- Gregorian ↔ lunar calendar or almanac: `calendar` / `lunar`.
- Complete birth details, broad reading: `comprehensive`.
- Four Pillars only: `bazi`.
- Zi Wei chart only: `ziwei`.
- A specific reflective question: `iching dayan|time|manual`.
- Two birth charts: `hepan`.
- Traditional annual themes: `liunian`.
- Almanac-based first-pass date filter: `zeji`; call it a filter, not a
  comprehensive date-selection guarantee.
- Historical astronomy query or market study: `history`; first read
  [historical research](references/historical-research.md).

For birth modes, establish all of the following before running:

1. Gregorian or lunar date; for lunar input, identify leap-month status.
2. Local civil time including minute when known; preserve seconds near solar-term boundaries.
3. Birthplace or explicit longitude and UTC offset when true-solar-time correction is requested.
4. Gender parameter required by the underlying traditional algorithm.
5. Bazi late-Zi convention (`--sect 1` or `--sect 2`, default 2). Explain the choice when 23:00 is relevant.

Use `--json --no-llm` for agent calls. Read the returned `schema_version`,
`engine_versions`, `conventions`, and any `time_correction` before interpreting.

## Interpretation workflow

1. Present the input and any conversion/correction so the user can verify it.
2. Present deterministic chart data as facts produced by the named engine.
3. Label traditional meanings as interpretations and use possibility language.
4. Call Bazi strength a visible-character counting heuristic; it omits monthly
   weighting, hidden stems, rooting, combinations, and many school-specific rules.
5. Call the I Ching engine hexagram/change analysis, not full Najia/Liuyao.
6. End with the cultural/entertainment boundary, especially for health, money,
   relationships, or major decisions.

Read [methodology and conventions](references/methodology.md) when the request
touches true solar time, late Zi hour, solar terms, randomness, cross-system
comparison, or claims of accuracy.

## Historical research workflow

Historical research must be falsifiable and point-in-time:

1. Use an explicitly supplied, hashed JPL SPK kernel; default to the Skyfield
   path and do not add Swiss Ephemeris to this MIT project.
2. Require BYOD market targets with provenance and
   `observation <= available <= decision < execution <= target_start < target_end`.
3. Choose the declared path. An absent `incremental_model` or exactly
   `{"enabled": false}` preserves the legacy univariate schema `1.0.0`. An
   enabled model requires hypothesis schema `2.0.0`, `--controls`, and
   `--controls-catalog`, and emits incremental result schema `2.0.0`.
4. Use only backward as-of joins. Incremental controls use their greatest
   eligible observation and latest eligible vintage, with complete cases and no
   imputation, interpolation, backfill, or fallback from a blank latest value.
5. Keep M0 and M2 on identical rows/folds. M0 uses every declared non-constant
   control; M2 adds every declared non-constant astronomy feature. Record
   train-constant drops. Use the same ridge alpha grid and fit budget, tune on
   train→validation, refit on train+validation, then open test once.
6. Report paired loss, declared HAC, centered-null circular block bootstrap, and
   the full M2-pipeline joint circular-shift placebo over nonzero `C_N` shifts.
   Qualify max-p robust/Bonferroni results as conditional on the supplied
   baseline and the truth/completeness of the declared family; a local runner
   cannot certify global family completeness or index uniqueness.
7. Append every test access to the trial registry, including failures and nulls.
   Label already-inspected historical holdouts `PSEUDO_OOS_ONLY`. Even data
   declared as post-registration remains `PROSPECTIVE_DECLARED_UNVERIFIED`
   until an independent timestamp/sealing mechanism exists.
8. Preserve null conclusions. It is valid to find no stable univariate
   association or no incremental OOS loss reduction beyond the declared M0.
   Never emit or infer `CONFIRMATORY_PASS` from a threshold diagnostic.

Never describe association as causation, an astronomical reconstruction as
historically available vintage data, an index/indicator as a tradable asset, or
an exploratory backtest as investment advice.

## Version compatibility

This Skill source version is `2.2.0`; it becomes a published release only after
the matching tag workflow succeeds. Package/Skill versions are independent from
wire formats: deterministic results remain schema `2.0.0`, astronomy remains
`1.0.0`, legacy research remains `1.0.0`, and enabled incremental research uses
`2.0.0`. Do not infer a schema upgrade from the package version alone.

## Output contract

Prefer concise sections in this order:

1. Verified input and conventions
2. Deterministic result or research evidence
3. Interpretation / hypothesis discussion
4. Limitations, evidence status, and disclaimer

For detailed command examples, use [agent prompt](references/agent_prompt.md).
