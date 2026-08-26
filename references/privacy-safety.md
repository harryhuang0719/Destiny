# Privacy and safety

## Local by default

Core chart calculations run locally. Destiny does not search `~/.env`, other
projects, trading directories, browser stores, or credential files. An env file
is read only when the caller supplies `--env-file`, and only known Destiny LLM
keys are accepted.

Zi Wei runs a local Node child with an environment allowlist. It cannot see
unrelated GitHub, trading, cloud, or model credentials.

## External interpretation

`--llm` sends the chart and relevant question to the chosen provider. This can
include exact birth date/time, gender parameter, location-derived corrections,
relationship context, and free-form personal questions.

Before using it:

1. Obtain the subject's permission when the data is not solely the requester's.
2. Name the chosen provider and explain that the data leaves the machine.
3. Use exactly one provider. Add `--llm-fallback` only after separate consent to
   disclose the same data to configured alternatives.
4. Do not paste API keys into prompts, command output, issues, or reports.
5. Do not commit `.env`, generated charts, birth records, trial results, or PDFs.

Agents normally do not need the built-in LLM: calculate with `--json --no-llm`
and interpret within the current conversation.

## Untrusted text

Shell double quotes still expand `$()`, backticks, and variables. Therefore an
agent must not build a shell command containing the user's question, even if the
Python subprocess itself uses `shell=False`.

Use `--question-stdin` and the execution tool's stdin channel. If that channel
does not exist, write an isolated temporary UTF-8 file with a filesystem API and
pass `--question-file`; remove it through an approved/recoverable workflow after use.

## Claim and decision boundary

- Traditional interpretations are not experimentally validated predictions.
- Historical astronomy/market output is association testing, not causality.
- Never provide diagnosis, treatment, legal instruction, investment orders, or
  deterministic relationship/life decisions from Destiny output.
- When a user is distressed or facing a high-stakes decision, prioritize
  grounded information and qualified human support over divination.
