#!/usr/bin/env python3
"""Generate a complete, non-proprietary incremental-research demo dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
CONTROL_FIELDS = [
    "control_id",
    "observation_time_utc",
    "available_at_utc",
    "vintage_id",
    "value",
]
TARGET_FIELDS = [
    "observation_time_utc",
    "available_at_utc",
    "decision_at_utc",
    "execution_at_utc",
    "target_start_utc",
    "target_end_utc",
    "target",
]


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _number(value: float) -> str:
    return format(value, ".17g")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _timeline(start: datetime, index: int) -> dict[str, datetime]:
    day = start + timedelta(days=index)
    execution = day + timedelta(minutes=3)
    return {
        "observation": day,
        "available": day + timedelta(minutes=1),
        "decision": day + timedelta(minutes=2),
        "execution": execution,
        "target_start": execution,
        "target_end": execution + timedelta(minutes=1),
    }


def _signals(index: int) -> tuple[float, float, float, float]:
    lagged_return = ((index * 7) % 13 - 6) / 300
    realized_volatility = 0.1 + ((index * 5) % 17) / 100
    astronomy_sin = math.sin(2 * math.pi * index / 11)
    astronomy_cos = math.cos(2 * math.pi * index / 7)
    return lagged_return, realized_volatility, astronomy_sin, astronomy_cos


def generate(output: Path) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=False)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    row_count = 150

    features = output / "features.csv"
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp_utc", "astro_signal_sin", "astro_signal_cos"],
            lineterminator="\n",
        )
        writer.writeheader()
        for index in range(row_count):
            _lag, _vol, astronomy_sin, astronomy_cos = _signals(index)
            writer.writerow(
                {
                    "timestamp_utc": _iso(start + timedelta(days=index)),
                    "astro_signal_sin": _number(astronomy_sin),
                    "astro_signal_cos": _number(astronomy_cos),
                }
            )

    feature_manifest = output / "features.csv.manifest.json"
    _write_json(
        feature_manifest,
        {
            "schema_version": "synthetic-example-v1",
            "source_type": "synthetic_fixture",
            "feature_file_sha256": _sha256(features),
            "coordinate_profile": "synthetic-no-ephemeris",
            "frame": {"kind": "synthetic"},
            "pre_utc_policy": "strict",
            "body_targets": {},
        },
    )

    controls = output / "controls.csv"
    with controls.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTROL_FIELDS, lineterminator="\n")
        writer.writeheader()
        for control_id in ("lagged_return_5d", "realized_volatility_20d"):
            for index in range(row_count):
                lagged_return, realized_volatility, _sin, _cos = _signals(index)
                timeline = _timeline(start, index)
                value = lagged_return if control_id == "lagged_return_5d" else realized_volatility
                writer.writerow(
                    {
                        "control_id": control_id,
                        "observation_time_utc": _iso(timeline["observation"]),
                        "available_at_utc": _iso(timeline["available"]),
                        "vintage_id": f"synthetic-{index + 1:03d}",
                        "value": _number(value),
                    }
                )

    controls_catalog = output / "controls.catalog.json"
    definitions = [
        {
            "control_id": "lagged_return_5d",
            "description": "Synthetic lagged-return baseline known before each decision",
            "control_family": "lagged_target",
            "unit": "decimal_return",
        },
        {
            "control_id": "realized_volatility_20d",
            "description": "Synthetic trailing-volatility baseline known before each decision",
            "control_family": "volatility",
            "unit": "annualized_decimal_volatility",
        },
    ]
    _write_json(
        controls_catalog,
        {
            "schema_version": "2.0.0",
            "catalog_id": "destiny-generated-controls-demo-v1",
            "controls_file_sha256": _sha256(controls),
            "row_semantics": "long_point_in_time_v1",
            "missing_marker": "empty_value_only",
            "controls": [
                {
                    **definition,
                    "vendor": "Destiny synthetic demo",
                    "source": "deterministic local generator",
                    "source_vintage": "generated-demo-v1",
                    "frequency": "daily",
                    "calendar": "synthetic-daily-v1",
                    "exchange_timezone": "UTC",
                    "revision_policy": "non_revisioned",
                    "methodology_version": "synthetic-v1",
                    "max_staleness_hours": 48,
                }
                for definition in definitions
            ],
        },
    )

    targets = output / "targets.csv"
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TARGET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for index in range(row_count):
            timeline = _timeline(start, index)
            lagged_return, realized_volatility, astronomy_sin, astronomy_cos = _signals(index)
            target = (
                2.0 * lagged_return
                - 0.75 * realized_volatility
                + 1.5 * astronomy_sin
                + 0.4 * astronomy_cos
            )
            writer.writerow(
                {
                    "observation_time_utc": _iso(timeline["observation"]),
                    "available_at_utc": _iso(timeline["available"]),
                    "decision_at_utc": _iso(timeline["decision"]),
                    "execution_at_utc": _iso(timeline["execution"]),
                    "target_start_utc": _iso(timeline["target_start"]),
                    "target_end_utc": _iso(timeline["target_end"]),
                    "target": _number(target),
                }
            )

    series_catalog = output / "series_catalog.json"
    _write_json(
        series_catalog,
        {
            "series_id": "DESTINY-SYNTHETIC-INCREMENTAL-DEMO",
            "vendor": "Destiny synthetic demo",
            "source": "deterministic local generator",
            "source_vintage": "generated-demo-v1",
            "instrument_type": "synthetic_nontradable_series",
            "currency": "N/A",
            "venue": "SYNTHETIC",
            "exchange_timezone": "UTC",
            "calendar": "synthetic-daily-v1",
            "price_type": "synthetic_continuous_target",
            "target_kind": "continuous_numeric",
            "target_column": "target",
            "tradable": False,
            "methodology_version": "synthetic-v1",
            "periods_per_year": 365,
            "overlapping_targets": False,
        },
    )

    hypothesis = output / "hypothesis.json"
    _write_json(
        hypothesis,
        {
            "hypothesis_schema_version": "2.0.0",
            "hypothesis_id": "destiny-synthetic-incremental-demo-v1",
            "registered_at_utc": "2019-01-01T00:00:00Z",
            "registered_commit": "synthetic-demo-not-a-prospective-seal",
            "mode": "pseudo_oos",
            "pre_utc_policy": "reject",
            "features": [
                {
                    "name": "astro_signal_sin",
                    "direction": "two-sided",
                    "effective_period_days": 11,
                },
                {
                    "name": "astro_signal_cos",
                    "direction": "two-sided",
                    "effective_period_days": 7,
                },
            ],
            "train_end_utc": _iso(_timeline(start, 59)["target_end"]),
            "validation_end_utc": _iso(_timeline(start, 90)["target_end"]),
            "embargo_hours": 24,
            "max_feature_staleness_hours": 24,
            "placebo_runs": 99,
            "seed": 20260826,
            "incremental_model": {
                "enabled": True,
                "estimator": "ridge_linear_v1",
                "control_ids": ["lagged_return_5d", "realized_volatility_20d"],
                "alpha_grid": [0.000001, 0.001, 0.1, 10.0],
                "fit_intercept": True,
                "standardization": "population_zscore_fit_rows_only",
                "missing_data_policy": "complete_case_no_imputation",
                "primary_loss": "squared_error",
                "hac_lag": 0,
                "bootstrap": {
                    "method": "circular_block_v1",
                    "runs": 999,
                    "block_length": 1,
                    "confidence_level": 0.95,
                    "seed": 2026082601,
                },
                "full_pipeline_placebo": {
                    "method": "joint_circular_shift_v1",
                    "runs": 99,
                    "seed": 2026082602,
                },
                "multiple_testing": {
                    "family_id": "synthetic-demo-family-v1",
                    "family_size": 1,
                    "family_index": 1,
                    "method": "bonferroni",
                    "alpha": 0.05,
                },
            },
        },
    )

    return {
        "features": str(features),
        "feature_manifest": str(feature_manifest),
        "targets": str(targets),
        "series_catalog": str(series_catalog),
        "hypothesis": str(hypothesis),
        "controls": str(controls),
        "controls_catalog": str(controls_catalog),
        "trial_registry": str(output / "trials.ndjson"),
        "result": str(output / "result.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new output directory; must not exist")
    args = parser.parse_args()
    paths = generate(Path(args.out).expanduser().resolve())
    print(json.dumps({"status": "ok", "paths": paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
