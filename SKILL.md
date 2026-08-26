---
name: destiny
description: Use for Chinese calendar conversion, Bazi, Zi Wei Dou Shu, I Ching hexagram casting, compatibility, annual themes, almanac date screening, or auditable historical astronomy/financial-market research. Treat results as cultural interpretation or exploratory statistics, not medical, legal, investment, or life-decision advice; this is not a full Wen-Wang Najia implementation.
license: MIT
metadata:
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
on macOS/Linux, `DESTINY_ROOT/destiny.ps1` or `destiny.cmd` on Windows. Invoke
`doctor --json`. If the environment is missing, install only when the user asked
to deploy/setup; use `python3 .../scripts/bootstrap.py` on macOS/Linux or
`py -3 ...\scripts\bootstrap.py` on Windows. Add `--research`, `--llm`, or
`--dev` only for the capability actually requested. Never download a JPL kernel
or market data implicitly.

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
3. Use only backward as-of feature joins.
4. Require a preregistered hypothesis manifest and append every test access to
   the trial registry, including failures and null results.
5. Report chronological train/validation/test results, time-shift placebos,
   family corrections, sample counts, and limitations.
6. Label already-inspected historical holdouts `PSEUDO_OOS_ONLY`. Even data
   declared as post-registration remains `PROSPECTIVE_DECLARED_UNVERIFIED`
   until an independent timestamp/sealing mechanism exists.
7. In this MVP it is valid to conclude that no stable preregistered univariate
   association exists. Do not call that an incremental-information test until
   financial controls and paired M0-vs-M2 models are implemented.

Never describe association as causation, an astronomical reconstruction as
historically available vintage data, an index/indicator as a tradable asset, or
an exploratory backtest as investment advice.

## Output contract

Prefer concise sections in this order:

1. Verified input and conventions
2. Deterministic result or research evidence
3. Interpretation / hypothesis discussion
4. Limitations, evidence status, and disclaimer

For detailed command examples, use [agent prompt](references/agent_prompt.md).
