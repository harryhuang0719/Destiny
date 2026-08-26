from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import history_cli
import pytest
import research_runner
from research_common import ResearchError

UTC = timezone.utc
PORTABLE_LEGACY_GOLDEN = (
    Path(__file__).resolve().parent / "fixtures" / "legacy_research_normalized.json"
)
LEGACY_FLOAT_ABS_TOLERANCE = 1e-12


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _write_lf(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _write_incremental_fixture(
    root: Path,
    *,
    astronomy_coefficient: float = 3.0,
    blank_control_index: int | None = None,
    future_control_index: int | None = None,
    target_hours: float = 1 / 60,
) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    embargo_hours = 30

    def times(index: int) -> dict[str, datetime]:
        day = start + timedelta(days=index)
        execution = day + timedelta(minutes=13)
        return {
            "observation": day + timedelta(minutes=10),
            "available": day + timedelta(minutes=11),
            "decision": day + timedelta(minutes=12),
            "execution": execution,
            "target_start": execution,
            "target_end": execution + timedelta(hours=target_hours),
        }

    train_last = 59
    train_end = times(train_last)["target_end"]
    validation_first = next(
        index
        for index in range(train_last + 1, 200)
        if times(index)["decision"] > train_end + timedelta(hours=embargo_hours)
    )
    validation_last = validation_first + 29
    validation_end = times(validation_last)["target_end"]
    test_first = next(
        index
        for index in range(validation_last + 1, 250)
        if times(index)["decision"] > validation_end + timedelta(hours=embargo_hours)
    )
    row_count = test_first + 50

    features = root / "features.csv"
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "astro_signal"])
        writer.writeheader()
        for index in range(row_count):
            writer.writerow(
                {
                    "timestamp_utc": _iso(start + timedelta(days=index)),
                    "astro_signal": math.sin(2 * math.pi * index / 11)
                    + 0.25 * math.cos(2 * math.pi * index / 7),
                }
            )
    feature_manifest = root / "features.csv.manifest.json"
    feature_manifest.write_text(
        json.dumps(
            {
                "schema_version": "test-v1",
                "source_type": "synthetic_fixture",
                "feature_file_sha256": _sha(features),
                "coordinate_profile": "synthetic",
                "frame": {},
                "pre_utc_policy": "strict",
                "body_targets": {},
            }
        ),
        encoding="utf-8",
    )

    controls = root / "controls.csv"
    with controls.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "control_id",
                "observation_time_utc",
                "available_at_utc",
                "vintage_id",
                "value",
            ],
        )
        writer.writeheader()
        for index in range(row_count):
            day = start + timedelta(days=index)
            available = day + timedelta(minutes=5)
            if index == future_control_index:
                available = times(index)["decision"] + timedelta(microseconds=1)
            value = "" if index == blank_control_index else ((index * 7) % 13 - 6) / 3
            writer.writerow(
                {
                    "control_id": "baseline",
                    "observation_time_utc": _iso(day),
                    "available_at_utc": _iso(available),
                    "vintage_id": f"v{index + 1}",
                    "value": value,
                }
            )
    controls_catalog = root / "controls.catalog.json"
    controls_catalog.write_text(
        json.dumps(
            {
                "schema_version": "2.0.0",
                "catalog_id": "runner-controls-v1",
                "controls_file_sha256": _sha(controls),
                "row_semantics": "long_point_in_time_v1",
                "missing_marker": "empty_value_only",
                "controls": [
                    {
                        "control_id": "baseline",
                        "description": "Synthetic lagged financial baseline",
                        "control_family": "lagged_target",
                        "vendor": "fixture",
                        "source": "generated",
                        "source_vintage": "v1",
                        "unit": "synthetic",
                        "frequency": "session",
                        "calendar": "daily-v1",
                        "exchange_timezone": "UTC",
                        "revision_policy": "non_revisioned",
                        "methodology_version": "v1",
                        "max_staleness_hours": 48,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    targets = root / "targets.csv"
    fields = [
        "observation_time_utc",
        "available_at_utc",
        "decision_at_utc",
        "execution_at_utc",
        "target_start_utc",
        "target_end_utc",
        "target",
    ]
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(row_count):
            timeline = times(index)
            control = ((index * 7) % 13 - 6) / 3
            astronomy = math.sin(2 * math.pi * index / 11) + 0.25 * math.cos(
                2 * math.pi * index / 7
            )
            target = 2 * control + astronomy_coefficient * astronomy
            writer.writerow(
                {
                    "observation_time_utc": _iso(timeline["observation"]),
                    "available_at_utc": _iso(timeline["available"]),
                    "decision_at_utc": _iso(timeline["decision"]),
                    "execution_at_utc": _iso(timeline["execution"]),
                    "target_start_utc": _iso(timeline["target_start"]),
                    "target_end_utc": _iso(timeline["target_end"]),
                    "target": target,
                }
            )

    catalog = root / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "series_id": "SYNTHETIC-RUNNER",
                "vendor": "fixture",
                "source": "generated",
                "source_vintage": "v1",
                "instrument_type": "synthetic",
                "currency": "USD",
                "venue": "TEST",
                "exchange_timezone": "UTC",
                "calendar": "daily-v1",
                "price_type": "synthetic",
                "target_kind": "continuous_numeric",
                "target_column": "target",
                "tradable": False,
                "methodology_version": "v1",
                "periods_per_year": 252,
                "overlapping_targets": target_hours > 24,
            }
        ),
        encoding="utf-8",
    )
    hypothesis = root / "hypothesis.json"
    hypothesis.write_text(
        json.dumps(
            {
                "hypothesis_schema_version": "2.0.0",
                "hypothesis_id": "runner-incremental-v1",
                "registered_at_utc": "2019-01-01T00:00:00Z",
                "registered_commit": "fixture",
                "mode": "pseudo_oos",
                "features": [{"name": "astro_signal", "direction": "two-sided"}],
                "train_end_utc": _iso(train_end),
                "validation_end_utc": _iso(validation_end),
                "embargo_hours": embargo_hours,
                "max_feature_staleness_hours": 24,
                "placebo_runs": 99,
                "seed": 17,
                "incremental_model": {
                    "enabled": True,
                    "estimator": "ridge_linear_v1",
                    "control_ids": ["baseline"],
                    "alpha_grid": [1e-6, 0.01, 1.0],
                    "fit_intercept": True,
                    "standardization": "population_zscore_fit_rows_only",
                    "missing_data_policy": "complete_case_no_imputation",
                    "primary_loss": "squared_error",
                    "hac_lag": 1 if target_hours > 24 else 0,
                    "bootstrap": {
                        "method": "circular_block_v1",
                        "runs": 999,
                        "block_length": 2 if target_hours > 24 else 1,
                        "confidence_level": 0.95,
                        "seed": 101,
                    },
                    "full_pipeline_placebo": {
                        "method": "joint_circular_shift_v1",
                        "runs": 99,
                        "seed": 202,
                    },
                    "multiple_testing": {
                        "family_id": "runner-family-v1",
                        "family_size": 1,
                        "family_index": 1,
                        "method": "bonferroni",
                        "alpha": 0.05,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "features": features,
        "feature_manifest": feature_manifest,
        "targets": targets,
        "catalog": catalog,
        "hypothesis": hypothesis,
        "controls": controls,
        "controls_catalog": controls_catalog,
        "registry": root / "trials.ndjson",
    }


def _write_portable_legacy_fixture(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    start = datetime(2021, 1, 1, tzinfo=UTC)
    features = root / "features.csv"
    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "signal", "noise"])
        writer.writeheader()
        for index in range(75):
            writer.writerow(
                {
                    "timestamp_utc": _iso(start + timedelta(days=index)),
                    "signal": (index * 5) % 19 - 9,
                    "noise": (index * 11) % 17 - 8,
                }
            )
    manifest = root / "features.csv.manifest.json"
    _write_lf(
        manifest,
        json.dumps(
            {
                "schema_version": "portable-v1",
                "source_type": "synthetic_fixture",
                "feature_file_sha256": _sha(features),
                "coordinate_profile": "portable-integer-fixture",
                "frame": {},
                "pre_utc_policy": "strict",
                "body_targets": {},
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    targets = root / "targets.csv"
    fields = [
        "observation_time_utc",
        "available_at_utc",
        "decision_at_utc",
        "execution_at_utc",
        "target_start_utc",
        "target_end_utc",
        "target",
    ]
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index in range(70):
            day = start + timedelta(days=index)
            signal = (index * 5) % 19 - 9
            noise = (index * 11) % 17 - 8
            writer.writerow(
                {
                    "observation_time_utc": _iso(day + timedelta(minutes=1)),
                    "available_at_utc": _iso(day + timedelta(minutes=2)),
                    "decision_at_utc": _iso(day + timedelta(minutes=3)),
                    "execution_at_utc": _iso(day + timedelta(minutes=4)),
                    "target_start_utc": _iso(day + timedelta(minutes=4)),
                    "target_end_utc": _iso(day + timedelta(minutes=5)),
                    "target": 2 * signal + noise,
                }
            )
    catalog = root / "catalog.json"
    _write_lf(
        catalog,
        json.dumps(
            {
                "series_id": "PORTABLE-LEGACY",
                "vendor": "tracked-test-fixture",
                "source": "deterministic-integer-generation",
                "source_vintage": "v1",
                "instrument_type": "synthetic",
                "currency": "USD",
                "venue": "TEST",
                "exchange_timezone": "UTC",
                "calendar": "daily-v1",
                "price_type": "synthetic",
                "target_kind": "continuous_numeric",
                "target_column": "target",
                "tradable": False,
                "methodology_version": "v1",
                "periods_per_year": 252,
                "overlapping_targets": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    hypothesis = root / "hypothesis.json"
    _write_lf(
        hypothesis,
        json.dumps(
            {
                "hypothesis_id": "portable-legacy-v1",
                "registered_at_utc": "2020-01-01T00:00:00Z",
                "registered_commit": "fixture",
                "mode": "pseudo_oos",
                "features": [
                    {"name": "signal", "direction": "positive"},
                    {"name": "noise", "direction": "two-sided"},
                ],
                "train_end_utc": "2021-01-25T23:59:59Z",
                "validation_end_utc": "2021-02-18T23:59:59Z",
                "embargo_hours": 0,
                "max_feature_staleness_hours": 24,
                "placebo_runs": 99,
                "seed": 314159,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    return {
        "features": features,
        "feature_manifest": manifest,
        "targets": targets,
        "catalog": catalog,
        "hypothesis": hypothesis,
        "registry": root / "trials.ndjson",
    }


def _run_fixture(paths: dict[str, Path]) -> dict[str, Any]:
    return research_runner.run_point_in_time_research(
        paths["features"],
        paths["targets"],
        paths["catalog"],
        paths["hypothesis"],
        paths["registry"],
        paths["feature_manifest"],
        controls_csv=paths["controls"],
        controls_catalog_json=paths["controls_catalog"],
    )


def test_incremental_signal_schema_placebo_pipeline_and_determinism(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_incremental_fixture(tmp_path / "first")
    counts = {"constant_detection": 0, "shifted_fit": 0}
    original_standardizer = research_runner.fit_frozen_standardizer
    original_fit = research_runner.fit_ridge_model

    def standardizer_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["constant_detection"] += 1
        return original_standardizer(*args, **kwargs)

    def fit_spy(*args: Any, **kwargs: Any) -> dict[str, Any]:
        counts["shifted_fit"] += 1
        return original_fit(*args, **kwargs)

    monkeypatch.setattr(research_runner, "fit_frozen_standardizer", standardizer_spy)
    monkeypatch.setattr(research_runner, "fit_ridge_model", fit_spy)
    first = _run_fixture(paths)
    placebo = first["incremental_model"]["test"]["full_pipeline_placebo"]
    assert first["schema_version"] == "2.0.0"
    assert first["analysis_mode"] == "incremental_ridge_v1"
    assert first["evidence_status"] == "PSEUDO_OOS_ONLY"
    assert first["incremental_model"]["evaluation_status"] == "EVALUATED_PSEUDO_OOS_ONLY"
    assert first["incremental_model"]["sample_counts"] == {
        "complete_case_before_splits": 142,
        "train": 60,
        "validation": 30,
        "test": 50,
        "embargo_excluded": 2,
        "m0_m2_identical": True,
    }
    assert first["incremental_model"]["test"]["primary"]["mean_loss_differential"] > 1
    assert placebo["group_size"] == 142
    assert placebo["effective_runs"] == 99
    assert placebo["includes_embargo_excluded_rows"] is True
    assert counts == {"constant_detection": 99, "shifted_fit": 99}
    assert len(first["incremental_model"]["test"]["primary"]["prediction_payload_sha256"]) == 64
    assert first["alignment"]["controls"]["input_rows"] == 142
    assert first["provenance"]["trial_events"] == ["STARTED", "COMPLETED"]
    assert "CONFIRMATORY_PASS" not in json.dumps(first, allow_nan=False)
    events = [json.loads(line) for line in paths["registry"].read_text().splitlines()]
    assert [event["event"] for event in events] == ["STARTED", "COMPLETED"]
    assert events[1]["result_payload_sha256"] == research_runner._canonical_sha256(first)

    second_paths = _write_incremental_fixture(tmp_path / "second")
    second = _run_fixture(second_paths)
    assert first["incremental_model"] == second["incremental_model"]
    assert first["splits"] == second["splits"]
    assert (
        first["provenance"]["experiment_fingerprint"]
        == second["provenance"]["experiment_fingerprint"]
    )


def test_incremental_null_has_no_material_astronomy_gain(tmp_path: Path) -> None:
    result = _run_fixture(_write_incremental_fixture(tmp_path / "null", astronomy_coefficient=0.0))
    mean_d = result["incremental_model"]["test"]["primary"]["mean_loss_differential"]
    assert abs(mean_d) < 1e-8
    assert result["incremental_model"]["test"]["threshold_diagnostics"]["threshold_met"] is False


def test_control_blank_and_future_release_flow_through_complete_case_alignment(
    tmp_path: Path,
) -> None:
    blank = _write_incremental_fixture(tmp_path / "blank", blank_control_index=100)
    blank_context = research_runner._prepare_incremental_context(
        blank["features"],
        blank["targets"],
        blank["catalog"],
        blank["hypothesis"],
        blank["registry"],
        blank["feature_manifest"],
        blank["controls"],
        blank["controls_catalog"],
    )
    assert blank_context["controls_alignment"]["dropped_by_reason"]["control_blank_latest"] == 1
    assert len(blank_context["complete_rows"]) == 141

    future = _write_incremental_fixture(tmp_path / "future", future_control_index=100)
    future_context = research_runner._prepare_incremental_context(
        future["features"],
        future["targets"],
        future["catalog"],
        future["hypothesis"],
        future["registry"],
        future["feature_manifest"],
        future["controls"],
        future["controls_catalog"],
    )
    assert len(future_context["complete_rows"]) == 142
    assert sum(future_context["controls_alignment"]["dropped_by_control"].values()) == 0


def test_direct_api_mode_gates_and_disabled_legacy_path(tmp_path: Path) -> None:
    paths = _write_incremental_fixture(tmp_path / "gates")
    with pytest.raises(ResearchError, match="必须提供"):
        research_runner.run_point_in_time_research(
            paths["features"],
            paths["targets"],
            paths["catalog"],
            paths["hypothesis"],
            paths["registry"],
            paths["feature_manifest"],
        )
    assert not paths["registry"].exists()

    hypothesis = json.loads(paths["hypothesis"].read_text())
    hypothesis.pop("hypothesis_schema_version")
    hypothesis["incremental_model"] = {"enabled": False}
    paths["hypothesis"].write_text(json.dumps(hypothesis), encoding="utf-8")
    with pytest.raises(ResearchError, match="未启用"):
        _run_fixture(paths)
    assert not paths["registry"].exists()

    result = research_runner.run_point_in_time_research(
        paths["features"],
        paths["targets"],
        paths["catalog"],
        paths["hypothesis"],
        paths["registry"],
        paths["feature_manifest"],
    )
    assert result["schema_version"] == "1.0.0"
    assert "incremental_model" not in result


def test_placebo_failure_aborts_trial_and_records_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_incremental_fixture(tmp_path / "failure")

    def fail_shift(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ResearchError("synthetic shifted fit failure")

    monkeypatch.setattr(research_runner, "fit_ridge_model", fail_shift)
    with pytest.raises(ResearchError, match="shifted fit failure"):
        _run_fixture(paths)
    events = [json.loads(line)["event"] for line in paths["registry"].read_text().splitlines()]
    assert events == ["STARTED", "FAILED"]


def test_preflight_failure_occurs_before_model_allocation_or_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_incremental_fixture(tmp_path / "preflight")

    def fail_preflight(**kwargs: Any) -> dict[str, Any]:
        raise ResearchError("synthetic workload cap")

    monkeypatch.setattr(research_runner, "ridge_workload_preflight", fail_preflight)
    monkeypatch.setattr(
        research_runner,
        "fit_paired_ridge_models",
        lambda *args, **kwargs: pytest.fail("model allocated before preflight"),
    )
    with pytest.raises(ResearchError, match="workload cap"):
        _run_fixture(paths)
    assert not paths["registry"].exists()


def test_runner_carries_half_open_overlap_lag_into_preflight(tmp_path: Path) -> None:
    paths = _write_incremental_fixture(tmp_path / "overlap", target_hours=36)
    context = research_runner._prepare_incremental_context(
        paths["features"],
        paths["targets"],
        paths["catalog"],
        paths["hypothesis"],
        paths["registry"],
        paths["feature_manifest"],
        paths["controls"],
        paths["controls_catalog"],
    )
    assert context["test_overlap"]["overlap_lag"] == 1
    assert context["workload"]["overlap_lag"] == 1


def test_incremental_paths_reject_hardlink_and_registry_inode_collisions(
    tmp_path: Path,
) -> None:
    hardlink_paths = _write_incremental_fixture(tmp_path / "hardlink-input")
    controls_alias = tmp_path / "controls-hardlink.csv"
    os.link(hardlink_paths["features"], controls_alias)
    with pytest.raises(ResearchError, match=r"file identity|同一文件"):
        research_runner.run_point_in_time_research(
            hardlink_paths["features"],
            hardlink_paths["targets"],
            hardlink_paths["catalog"],
            hardlink_paths["hypothesis"],
            hardlink_paths["registry"],
            hardlink_paths["feature_manifest"],
            controls_csv=controls_alias,
            controls_catalog_json=hardlink_paths["controls_catalog"],
        )
    assert not hardlink_paths["registry"].exists()

    output_paths = _write_incremental_fixture(tmp_path / "registry-hardlink")
    os.link(output_paths["controls"], output_paths["registry"])
    with pytest.raises(ResearchError, match=r"file identity|同一文件"):
        _run_fixture(output_paths)


def test_incremental_prospective_remains_declared_unverified_and_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_incremental_fixture(tmp_path / "prospective")
    hypothesis = json.loads(paths["hypothesis"].read_text())
    hypothesis["mode"] = "prospective"
    hypothesis["registered_commit"] = "a" * 40
    paths["hypothesis"].write_text(json.dumps(hypothesis), encoding="utf-8")
    monkeypatch.setattr(
        research_runner,
        "_git_state",
        lambda: {"commit": "b" * 40, "dirty": False},
    )
    monkeypatch.setattr(research_runner, "_git_is_ancestor", lambda commit: True)
    result = _run_fixture(paths)
    assert result["evidence_status"] == "PROSPECTIVE_DECLARED_UNVERIFIED"
    assert (
        result["incremental_model"]["evaluation_status"]
        == "EVALUATED_PROSPECTIVE_DECLARED_UNVERIFIED"
    )
    assert "CONFIRMATORY_PASS" not in json.dumps(result, allow_nan=False)

    future = _write_incremental_fixture(tmp_path / "prospective-future")
    future_hypothesis = json.loads(future["hypothesis"].read_text())
    future_hypothesis["mode"] = "prospective"
    future_hypothesis["registered_commit"] = "a" * 40
    future_hypothesis["registered_at_utc"] = "2099-01-01T00:00:00Z"
    future["hypothesis"].write_text(json.dumps(future_hypothesis), encoding="utf-8")
    with pytest.raises(ResearchError, match="不能在未来"):
        _run_fixture(future)
    assert not future["registry"].exists()


def test_huge_json_integer_fails_cli_and_api_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write_incremental_fixture(tmp_path / "huge-int")
    catalog = json.loads(paths["controls_catalog"].read_text())
    catalog["controls"][0]["max_staleness_hours"] = 10**1000
    paths["controls_catalog"].write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ResearchError, match="有限数值"):
        _run_fixture(paths)
    assert not paths["registry"].exists()

    code = history_cli.main(
        [
            "research",
            "--features",
            str(paths["features"]),
            "--feature-manifest",
            str(paths["feature_manifest"]),
            "--targets",
            str(paths["targets"]),
            "--catalog",
            str(paths["catalog"]),
            "--hypothesis",
            str(paths["hypothesis"]),
            "--controls",
            str(paths["controls"]),
            "--controls-catalog",
            str(paths["controls_catalog"]),
            "--trial-registry",
            str(paths["registry"]),
            "--out",
            str(tmp_path / "result.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "有限数值" in captured.err
    assert "Traceback" not in captured.err


def _normalize_legacy_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(result))
    provenance = normalized["provenance"]
    for key, value in provenance["input_paths"].items():
        provenance["input_paths"][key] = f"<FIXTURE_DIR>/{Path(value).name}"
    provenance["trial_registry"] = "<FIXTURE_DIR>/trials.ndjson"
    provenance["trial"]["trial_id"] = "<TRIAL_ID>"
    provenance["trial"]["accessed_at_utc"] = "<RUNTIME_TIMESTAMP_UTC>"
    provenance["trial"]["code"]["commit"] = "<GIT_COMMIT>"
    provenance["trial"]["code"]["dirty"] = "<GIT_DIRTY>"
    provenance["trial"]["code"]["source_sha256"] = "<SOURCE_SHA256>"
    return normalized


def _assert_portable_json_equal(actual: Any, expected: Any, path: str = "$") -> None:
    assert type(actual) is type(expected), f"{path}: type changed"
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), f"{path}: keys changed"
        for key in expected:
            _assert_portable_json_equal(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: list length changed"
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _assert_portable_json_equal(left, right, f"{path}[{index}]")
    elif isinstance(expected, float):
        assert math.isclose(
            actual,
            expected,
            rel_tol=0.0,
            abs_tol=LEGACY_FLOAT_ABS_TOLERANCE,
        ), f"{path}: float drifted by {actual - expected!r}"
    else:
        assert actual == expected, f"{path}: value changed"


def test_legacy_v21_portable_normalized_golden(tmp_path: Path) -> None:
    fixture = _write_portable_legacy_fixture(tmp_path / "portable-legacy")
    result = research_runner.run_point_in_time_research(
        fixture["features"],
        fixture["targets"],
        fixture["catalog"],
        fixture["hypothesis"],
        fixture["registry"],
        fixture["feature_manifest"],
    )
    normalized = _normalize_legacy_result(result)
    expected = json.loads(PORTABLE_LEGACY_GOLDEN.read_text(encoding="utf-8"))
    _assert_portable_json_equal(normalized, expected)

    cross_python_roundoff = copy.deepcopy(expected)
    cross_python_roundoff["features"][0]["train"]["pearson"] += 1e-15
    _assert_portable_json_equal(normalized, cross_python_roundoff)
    real_drift = copy.deepcopy(expected)
    real_drift["features"][0]["train"]["pearson"] += 1e-8
    with pytest.raises(AssertionError, match="float drifted"):
        _assert_portable_json_equal(normalized, real_drift)
