# Methodology and conventions

Destiny makes its conventions visible because traditional systems differ by
school, and tiny time-boundary choices can change a chart.

## Calendar and Bazi

- Calendar/Bazi calculations use `lunar-python==1.4.8`.
- Inputs are Gregorian civil date/time after any explicit lunar conversion or
  true-solar-time correction. Minutes and seconds are retained.
- Solar-term boundaries use the library's exact timestamps. For example, its
  2024 Lichun boundary is `2024-02-04 16:27:07`; the year/month pillars differ
  immediately before and after it.
- Bazi `--sect 1` treats late Zi according to lunar-python sect 1; `--sect 2`
  uses its midnight-based default. The selected sect is recorded in JSON.
- `day_master.strength` is only an equal-weight count of the eight visible stem
  and branch elements. It does not weight the monthly command, hidden stems,
  rooting, combinations, transformations, climate adjustment, or special
  structures. It is a prompt for discussion, not a complete useful-god engine.
- Luck-cycle output records both the exact start date and the full start offset;
  it does not mislabel the offset's year component as age.

## True solar time

Destiny applies the conventional approximation:

```text
true solar time = civil time
                + 4 minutes × (longitude − civil-zone meridian)
                + equation of time
```

Supported cities map to both longitude and an IANA timezone. Destiny loads the
pinned `tzdata==2026.3` package rather than silently inheriting a host OS
database. The historical UTC offset for the input date—including daylight saving—is resolved before the
correction. Nonexistent and ambiguous DST wall times fail closed; an ambiguous
time can be resolved with an explicit `--tz`. Custom longitudes require an
explicit, possibly fractional offset such as `--tz 5.5`.

The result records the original civil time, IANA zone, resolved offset,
longitude, corrected time, and convention version. This is still an
approximation and does not settle disagreements between schools.

## Zi Wei Dou Shu

- Zi Wei uses pinned `iztro==2.5.8` through a static Node bridge.
- Python sends validated JSON over stdin. User input never becomes JavaScript
  source, and the child receives an environment allowlist rather than API keys.
- `00:00–00:59` maps to iztro early-Zi index 0; `23:00–23:59` maps to late-Zi
  index 12. This distinction materially changes some charts.
- The JSON records that `astro.bySolar(..., fixLeap=true, zh-CN)` is used.

## I Ching scope

- Line tuples are ordered bottom-to-top. The canonical trigram bits are tested.
- Manual casts accept exactly six digits from 6 through 9.
- Dayan uses the conventional discrete ratio `6:7:8:9 = 1:5:7:3`. Every
  analyzer cast records a replayable random seed.
- Time casting uses lunar month/day and one-based earthly-branch numbers
  (`子=1 … 亥=12`). This is one explicit Meihua convention, not universal.
- The module supplies hexagram names, compact hexagram text, nuclear/changed
  hexagrams, and changing-line count guidance. It does not currently implement
  full Wen-Wang Najia, palace element, Shi/Ying, six relatives/animals placed on
  lines, void branches, monthly/day strength, or a complete line-text corpus.

## Almanac date filtering

`zeji` performs a transparent first pass: a date survives when the normalized
activity appears in `宜` and does not appear in `忌`. Results stay in calendar
order; there is no hidden ranking. It does not guarantee success, compute a full
school-specific date election, or personalize locally from Bazi. If optional LLM
use is enabled, any personal comparison is interpretation rather than engine fact.

## LLM boundary

The deterministic engines never require a model. External interpretation is
off by default. MiniMax, DeepSeek, and custom OpenAI-compatible endpoints are
single-provider opt-ins; automatic cross-provider fallback is disabled unless
the user separately requests it. Provider/model metadata is returned, never the key.
