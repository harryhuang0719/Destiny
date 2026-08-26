# Portable agent prompt

Use this only when an agent platform does not discover `SKILL.md` automatically.

```text
You have access to the Destiny repository, an offline-first traditional Chinese
calendar and chart engine with an optional historical astronomy research layer.

First resolve DESTINY_ROOT to the repository directory that contains SKILL.md.
Run DESTINY_ROOT/destiny doctor --json. Do not assume an OpenClaw-specific path.

For chart work:
- Confirm Gregorian/lunar date, leap month, local time (including minutes),
  birthplace/timezone, and the algorithm's gender parameter.
- Use DESTINY_ROOT/destiny <mode> ... --json --no-llm.
- Separate deterministic output from traditional interpretation.
- Bazi strength is a lightweight visible-character heuristic.
- The I Ching module casts and transforms hexagrams; it is not full Wen-Wang Najia.
- Treat all results as cultural/entertainment material, never high-stakes advice.

For a user-authored question, use --question-stdin and the execution tool's stdin
channel. Never concatenate or interpolate user text into a shell command.

For historical research:
- Read references/historical-research.md.
- Use only an explicitly supplied and hashed JPL kernel.
- Never auto-download or redistribute market data.
- Require the point-in-time target schema, series catalog, preregistered
  hypothesis, and append-only trial registry.
- Treat absent/exactly-disabled `incremental_model` as the legacy univariate
  schema-1.0 path. For enabled schema-2.0 incremental research, also require the
  hashed long controls CSV/catalog pair.
- Keep M0 controls and M2 controls-plus-all-astronomy on identical rows/folds;
  report paired loss, HAC, circular block bootstrap, full-pipeline circular
  placebo, robust max-p, Bonferroni scope, failures, evidence status, and limits.
- A valid conclusion is that no incremental OOS loss reduction exists beyond
  the exact supplied controls. Never turn `threshold_met` into confirmation.

Never invoke an external LLM unless the user explicitly selects the provider and
consents to sending the relevant personal data outside the machine.
```

## Command map

Run all commands from `DESTINY_ROOT`, or invoke the `destiny` wrapper by absolute path.

```bash
# Core — pure JSON, offline
./destiny calendar 2026 8 26 --json
./destiny lunar 2024 1 1 --json
./destiny bazi 1990 1 15 14 1 --minute 30 --sect 2 --json
./destiny ziwei 1990 1 15 14 男 --minute 30 --json
./destiny comprehensive 1990 1 15 14 1 --minute 30 --json
./destiny liunian 1990 1 15 14 1 --year 2026 --json
./destiny hepan 1990 1 15 14 1 1992 3 20 8 0 --json
./destiny zeji 结婚 --month 2026-09 --json

# True solar time; city resolves historical IANA offset/DST
./destiny bazi 1990 6 15 14 1 --minute 30 --solar --city 上海 --json

# User question: start process with stdin, then write the original text through
# the tool's stdin channel. Do not insert it into this shell line.
./destiny iching dayan --question-stdin --seed 42 --json

# Historical layer
./destiny history kernel-info --kernel /absolute/path/de440s.bsp
./destiny history astro --kernel /absolute/path/de440s.bsp \
  --at 2000-01-01T12:00:00Z
./destiny history build --kernel /absolute/path/de440s.bsp \
  --start 2000-01-01T00:00:00Z --end 2001-01-01T00:00:00Z \
  --step-hours 24 --out /absolute/path/astro_features.csv
./destiny history research --features /absolute/path/astro_features.csv \
  --targets /absolute/path/targets.csv --catalog /absolute/path/series_catalog.json \
  --hypothesis /absolute/path/hypothesis.json \
  --trial-registry /absolute/path/trials.ndjson --out /absolute/path/result.json

# Incremental path: both controls arguments are required together
./destiny history research --features /absolute/path/astro_features.csv \
  --targets /absolute/path/targets.csv --catalog /absolute/path/series_catalog.json \
  --hypothesis /absolute/path/hypothesis.incremental.json \
  --controls /absolute/path/controls.csv \
  --controls-catalog /absolute/path/controls.catalog.json \
  --trial-registry /absolute/path/trials.ndjson --out /absolute/path/result.json
```

The CLI accepts `--llm --provider minimax|deepseek|custom`, but an agent should
normally interpret the offline JSON itself. `--llm-fallback` is a separate,
explicit privacy decision because it can send the same data to another provider.
