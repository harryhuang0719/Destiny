from __future__ import annotations

import copy
import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import history_cli
import pytest
import research_contracts
from research_common import ResearchError

UTC = timezone.utc


def _incremental_hypothesis() -> dict[str, Any]:
    return {
        "hypothesis_schema_version": "2.0.0",
        "hypothesis_id": "incremental-fixture-v1",
        "registered_at_utc": "2019-01-01T00:00:00Z",
        "registered_commit": "fixture",
        "mode": "pseudo_oos",
        "features": [{"name": "astro_signal", "direction": "two-sided"}],
        "train_end_utc": "2020-01-01T00:00:00Z",
        "validation_end_utc": "2021-01-01T00:00:00Z",
        "embargo_hours": 0,
        "max_feature_staleness_hours": 24,
        "placebo_runs": 99,
        "seed": 7,
        "incremental_model": {
            "enabled": True,
            "estimator": "ridge_linear_v1",
            "control_ids": ["past_return_5d", "realized_volatility_20d"],
            "alpha_grid": [1e-8, 0.01, 1.0],
            "fit_intercept": True,
            "standardization": "population_zscore_fit_rows_only",
            "missing_data_policy": "complete_case_no_imputation",
            "primary_loss": "squared_error",
            "hac_lag": 5,
            "bootstrap": {
                "method": "circular_block_v1",
                "runs": 999,
                "block_length": 10,
                "confidence_level": 0.95,
                "seed": 2026082601,
            },
            "full_pipeline_placebo": {
                "method": "joint_circular_shift_v1",
                "runs": 99,
                "seed": 2026082602,
            },
            "multiple_testing": {
                "family_id": "spx-5d-return-v1",
                "family_size": 20,
                "family_index": 1,
                "method": "bonferroni",
                "alpha": 0.05,
            },
        },
    }


def _control_definition(
    control_id: str,
    *,
    revision_policy: str = "as_published_revisions",
    max_staleness_hours: float = 168,
) -> dict[str, Any]:
    return {
        "control_id": control_id,
        "description": f"Fixture {control_id}",
        "control_family": "lagged_target",
        "vendor": "fixture-vendor",
        "source": "fixture-source",
        "source_vintage": "fixture-v1",
        "unit": "decimal_return",
        "frequency": "session",
        "calendar": "fixture-calendar-v1",
        "exchange_timezone": "UTC",
        "revision_policy": revision_policy,
        "methodology_version": "v1",
        "max_staleness_hours": max_staleness_hours,
    }


def _catalog(
    controls_hash: str = "0" * 64,
    *,
    definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "catalog_id": "financial-controls-fixture-v1",
        "controls_file_sha256": controls_hash,
        "row_semantics": "long_point_in_time_v1",
        "missing_marker": "empty_value_only",
        "controls": definitions
        or [
            _control_definition("past_return_5d"),
            _control_definition("realized_volatility_20d"),
        ],
    }


def _series_catalog() -> dict[str, Any]:
    return {
        "series_id": "SERIES",
        "vendor": "fixture",
        "source": "fixture",
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
    }


def _write_controls(path: Path, rows: list[dict[str, str]]) -> str:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=research_contracts.CONTROL_CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw_control(
    control_id: str,
    observation: str,
    available: str,
    value: str,
    *,
    vintage: str = "v1",
) -> dict[str, str]:
    return {
        "control_id": control_id,
        "observation_time_utc": observation,
        "available_at_utc": available,
        "vintage_id": vintage,
        "value": value,
    }


def _dt(day: float) -> datetime:
    return datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=day)


def _loaded_control(
    ordinal: int,
    control_id: str,
    observation_day: float,
    available_day: float,
    value: float | None,
    *,
    vintage: str = "v1",
) -> dict[str, Any]:
    return {
        "row_ordinal": ordinal,
        "control_id": control_id,
        "observation_time_utc": _dt(observation_day),
        "available_at_utc": _dt(available_day),
        "vintage_id": vintage,
        "value": value,
    }


def test_incremental_hypothesis_is_strict_and_legacy_modes_are_unchanged() -> None:
    enabled = _incremental_hypothesis()
    research_contracts.validate_hypothesis(enabled)
    assert research_contracts.incremental_model_enabled(enabled) is True

    legacy = copy.deepcopy(enabled)
    legacy.pop("hypothesis_schema_version")
    legacy.pop("incremental_model")
    research_contracts.validate_hypothesis(legacy)
    assert research_contracts.incremental_model_enabled(legacy) is False

    disabled = copy.deepcopy(legacy)
    disabled["incremental_model"] = {"enabled": False}
    research_contracts.validate_hypothesis(disabled)
    assert research_contracts.incremental_model_enabled(disabled) is False

    disabled["incremental_model"]["alpha_grid"] = [1.0]
    with pytest.raises(ResearchError, match="精确"):
        research_contracts.validate_hypothesis(disabled)

    disabled["incremental_model"] = {"enabled": 0}
    with pytest.raises(ResearchError, match="精确"):
        research_contracts.validate_hypothesis(disabled)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("hypothesis_schema_version",), "1.0.0", "hypothesis_schema_version"),
        (("incremental_model", "enabled"), 1, "enabled"),
        (("incremental_model", "estimator"), "ols", "estimator"),
        (("incremental_model", "control_ids"), ["a", "a"], "重复"),
        (("incremental_model", "alpha_grid"), [0.0], "1e-8"),
        (("incremental_model", "alpha_grid"), [1.0, 0.1], "严格递增"),
        (("incremental_model", "hac_lag"), True, "boolean"),
        (("incremental_model", "bootstrap", "runs"), 998, "999"),
        (("incremental_model", "bootstrap", "block_length"), 0, "1"),
        (("incremental_model", "bootstrap", "confidence_level"), True, "JSON number"),
        (("incremental_model", "full_pipeline_placebo", "runs"), 98, "99"),
        (("incremental_model", "multiple_testing", "family_index"), 21, "family_size"),
        (("incremental_model", "multiple_testing", "method"), "bh", "bonferroni"),
        (("incremental_model", "multiple_testing", "alpha"), 0.0, "必须在"),
    ],
)
def test_incremental_hypothesis_rejects_every_frozen_boundary(
    path: tuple[str, ...], value: Any, message: str
) -> None:
    hypothesis = _incremental_hypothesis()
    cursor: dict[str, Any] = hypothesis
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(ResearchError, match=message):
        research_contracts.validate_hypothesis(hypothesis)


def test_incremental_hypothesis_rejects_unknown_nested_keys_and_column_cap() -> None:
    unknown = _incremental_hypothesis()
    unknown["incremental_model"]["surprise"] = 1
    with pytest.raises(ResearchError, match="未知字段"):
        research_contracts.validate_hypothesis(unknown)

    oversized = _incremental_hypothesis()
    oversized["features"] = [{"name": f"feature_{index}"} for index in range(257)]
    oversized["incremental_model"]["control_ids"] = [f"control_{index}" for index in range(128)]
    with pytest.raises(ResearchError, match="384"):
        research_contracts.validate_hypothesis(oversized)


def test_controls_catalog_exact_schema_hash_and_types() -> None:
    catalog = _catalog("a" * 64)
    research_contracts.validate_controls_catalog(catalog, "a" * 64)

    tampered = copy.deepcopy(catalog)
    tampered["controls_file_sha256"] = "b" * 64
    with pytest.raises(ResearchError, match="不一致"):
        research_contracts.validate_controls_catalog(tampered, "a" * 64)

    unknown = copy.deepcopy(catalog)
    unknown["extra"] = True
    with pytest.raises(ResearchError, match="未知字段"):
        research_contracts.validate_controls_catalog(unknown, "a" * 64)

    bad_bool = copy.deepcopy(catalog)
    bad_bool["controls"][0]["max_staleness_hours"] = True
    with pytest.raises(ResearchError, match="boolean"):
        research_contracts.validate_controls_catalog(bad_bool, "a" * 64)

    bad_id = copy.deepcopy(catalog)
    bad_id["controls"][0]["control_id"] = "bad id"
    with pytest.raises(ResearchError, match="control_id"):
        research_contracts.validate_controls_catalog(bad_id, "a" * 64)

    huge_integer = copy.deepcopy(catalog)
    huge_integer["controls"][0]["max_staleness_hours"] = 10**1000
    with pytest.raises(ResearchError, match="有限数值"):
        research_contracts.validate_controls_catalog(huge_integer, "a" * 64)


def test_control_csv_loads_normalized_rows_and_stable_ordinals(tmp_path: Path) -> None:
    path = tmp_path / "controls.csv"
    rows = [
        _raw_control(
            "past_return_5d",
            "2020-01-01T08:00:00+08:00",
            "2020-01-01T08:01:00+08:00",
            "0.25",
        ),
        _raw_control(
            "realized_volatility_20d",
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:02:00Z",
            "",
        ),
    ]
    digest = _write_controls(path, rows)
    catalog = _catalog(digest)
    research_contracts.validate_controls_catalog(catalog, digest)
    loaded = research_contracts._load_control_rows(
        path, catalog, ["past_return_5d", "realized_volatility_20d"]
    )
    assert [row["row_ordinal"] for row in loaded] == [1, 2]
    assert loaded[0]["observation_time_utc"] == _dt(0)
    assert loaded[0]["available_at_utc"] == _dt(0) + timedelta(minutes=1)
    assert loaded[0]["value"] == 0.25
    assert loaded[1]["value"] is None


@pytest.mark.parametrize(
    ("rows", "definitions", "message"),
    [
        (
            [_raw_control("past_return_5d", "2020-01-02T00:00:00Z", "2020-01-01T00:00:00Z", "1")],
            [_control_definition("past_return_5d")],
            "observation_time_utc",
        ),
        (
            [
                _raw_control("past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "1"),
                _raw_control(
                    "past_return_5d",
                    "2020-01-01T00:00:00Z",
                    "2020-01-01T01:00:00Z",
                    "2",
                    vintage="v2",
                ),
            ],
            [_control_definition("past_return_5d")],
            "重复",
        ),
        (
            [
                _raw_control("past_return_5d", "2020-01-02T00:00:00Z", "2020-01-02T01:00:00Z", "1"),
                _raw_control("past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "2"),
            ],
            [_control_definition("past_return_5d")],
            "严格递增",
        ),
        (
            [
                _raw_control("past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "1"),
                _raw_control(
                    "past_return_5d",
                    "2020-01-01T00:00:00Z",
                    "2020-01-01T02:00:00Z",
                    "2",
                    vintage="v2",
                ),
            ],
            [_control_definition("past_return_5d", revision_policy="non_revisioned")],
            "non_revisioned",
        ),
        (
            [_raw_control("unknown", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "1")],
            [_control_definition("past_return_5d")],
            "不在 catalog",
        ),
        (
            [_raw_control("past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "NaN")],
            [_control_definition("past_return_5d")],
            "有限 float",
        ),
        (
            [
                _raw_control(
                    "past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "1e101"
                )
            ],
            [_control_definition("past_return_5d")],
            "1e100",
        ),
    ],
)
def test_control_csv_rejects_future_duplicate_revision_and_value_attacks(
    tmp_path: Path,
    rows: list[dict[str, str]],
    definitions: list[dict[str, Any]],
    message: str,
) -> None:
    path = tmp_path / "controls.csv"
    digest = _write_controls(path, rows)
    catalog = _catalog(digest, definitions=definitions)
    with pytest.raises(ResearchError, match=message):
        research_contracts._load_control_rows(path, catalog, [definitions[0]["control_id"]])


def test_control_csv_row_limit_and_missing_preregistered_control_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "controls.csv"
    rows = [
        _raw_control("past_return_5d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "1"),
        _raw_control(
            "realized_volatility_20d", "2020-01-01T00:00:00Z", "2020-01-01T01:00:00Z", "2"
        ),
    ]
    digest = _write_controls(path, rows)
    catalog = _catalog(
        digest,
        definitions=[
            _control_definition("past_return_5d"),
            _control_definition("realized_volatility_20d"),
            _control_definition("missing_control"),
        ],
    )
    with pytest.raises(ResearchError, match="没有数据"):
        research_contracts._load_control_rows(path, catalog, ["past_return_5d", "missing_control"])

    monkeypatch.setattr(research_contracts, "MAX_RESEARCH_ROWS", 1)
    with pytest.raises(ResearchError, match="行安全上限"):
        research_contracts._load_control_rows(
            path, catalog, ["past_return_5d", "realized_volatility_20d"]
        )


@pytest.mark.parametrize(
    "case",
    [
        "periods_per_year",
        "effective_period_days",
        "embargo_hours",
        "max_feature_staleness_hours",
        "cost_bps",
    ],
)
def test_huge_json_numbers_fail_api_and_cli_without_traceback(
    case: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hypothesis = _incremental_hypothesis()
    series_catalog = _series_catalog()
    huge = 10**500
    if case == "periods_per_year":
        series_catalog[case] = huge
    elif case == "effective_period_days":
        hypothesis["features"][0][case] = huge
    else:
        hypothesis[case] = huge

    def validator() -> None:
        if case == "periods_per_year":
            research_contracts.validate_catalog(series_catalog)
        else:
            research_contracts.validate_hypothesis(hypothesis)

    with pytest.raises(ResearchError, match="有限数值"):
        validator()

    hypothesis_path = tmp_path / f"{case}-hypothesis.json"
    catalog_path = tmp_path / f"{case}-catalog.json"
    hypothesis_path.write_text(json.dumps(hypothesis), encoding="utf-8")
    catalog_path.write_text(json.dumps(series_catalog), encoding="utf-8")

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if case == "periods_per_year":
            loaded = research_contracts._load_json_object(catalog_path, "series catalog")
            research_contracts.validate_catalog(loaded)
        else:
            loaded = research_contracts._load_json_object(hypothesis_path, "hypothesis manifest")
            research_contracts.validate_hypothesis(loaded)
        raise AssertionError("overflow validator unexpectedly returned")

    monkeypatch.setattr(history_cli, "run_point_in_time_research", fake_run)
    code = history_cli.main(
        [
            "research",
            "--features",
            str(tmp_path / f"{case}-features.csv"),
            "--targets",
            str(tmp_path / f"{case}-targets.csv"),
            "--catalog",
            str(catalog_path),
            "--hypothesis",
            str(hypothesis_path),
            "--controls",
            str(tmp_path / f"{case}-controls.csv"),
            "--controls-catalog",
            str(tmp_path / f"{case}-controls-catalog.json"),
            "--trial-registry",
            str(tmp_path / f"{case}-trials.ndjson"),
            "--out",
            str(tmp_path / f"{case}-result.json"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "有限数值" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("duplicate", ["decision_at_utc", "observation_time_utc"])
def test_target_csv_rejects_duplicate_required_headers(tmp_path: Path, duplicate: str) -> None:
    fields = [
        "observation_time_utc",
        "available_at_utc",
        "decision_at_utc",
        "execution_at_utc",
        "target_start_utc",
        "target_end_utc",
        "target",
    ]
    fields.insert(fields.index(duplicate) + 1, duplicate)
    path = tmp_path / f"duplicate-{duplicate}.csv"
    path.write_text(",".join(fields) + "\n", encoding="utf-8")
    with pytest.raises(ResearchError, match=f"重复字段: {duplicate}"):
        research_contracts._load_target_rows(path, "target")


def test_feature_csv_rejects_duplicate_and_empty_headers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate-feature.csv"
    duplicate.write_text(
        "timestamp_utc,foo,foo\n2020-01-01T00:00:00Z,1,2\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchError, match="重复字段: foo"):
        research_contracts._load_feature_rows(duplicate, ["foo"])

    empty = tmp_path / "empty-feature-header.csv"
    empty.write_text(
        "timestamp_utc,,foo\n2020-01-01T00:00:00Z,1,2\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchError, match="空字段名"):
        research_contracts._load_feature_rows(empty, ["foo"])


def test_target_csv_rejects_empty_header_but_allows_distinct_extra_columns(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty-target-header.csv"
    empty.write_text(
        "observation_time_utc,,target\n2020-01-01T00:00:00Z,x,1\n",
        encoding="utf-8",
    )
    with pytest.raises(ResearchError, match="空字段名"):
        research_contracts._load_target_rows(empty, "target")

    valid = tmp_path / "extra-target-column.csv"
    fields = [*sorted(research_contracts.TARGET_REQUIRED), "target", "extra"]
    raw = {
        "observation_time_utc": "2020-01-01T00:00:00Z",
        "available_at_utc": "2020-01-01T00:00:01Z",
        "decision_at_utc": "2020-01-01T00:00:02Z",
        "execution_at_utc": "2020-01-01T00:00:03Z",
        "target_start_utc": "2020-01-01T00:00:03Z",
        "target_end_utc": "2020-01-01T00:00:04Z",
        "target": "1",
        "extra": "allowed",
    }
    with valid.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(raw)
    assert len(research_contracts._load_target_rows(valid, "target")) == 1


def test_asof_revision_order_and_one_microsecond_future_release() -> None:
    catalog = _catalog(definitions=[_control_definition("macro", max_staleness_hours=10_000)])
    controls = [
        _loaded_control(1, "macro", 0, 1, 1.0, vintage="old-initial"),
        _loaded_control(2, "macro", 0, 4, 2.0, vintage="old-late-revision"),
        _loaded_control(3, "macro", 2, 3, 3.0, vintage="new-observation"),
        _loaded_control(
            4,
            "macro",
            5,
            5 + 1 / 86_400_000_000,
            4.0,
            vintage="one-microsecond-future",
        ),
    ]
    targets = [{"decision_at_utc": _dt(5), "row_id": "1:fixture", "target": 1.0}]
    joined, accounting = research_contracts._asof_join_incremental(
        [_dt(5)],
        [{"astro": 1.0}],
        targets,
        ["astro"],
        1,
        controls,
        catalog,
        ["macro"],
    )
    assert accounting["complete_case_rows"] == 1
    assert joined[0]["controls"] == {"macro": 3.0}
    assert joined[0]["control_sources"]["macro"]["vintage_id"] == "new-observation"
    assert joined[0]["control_sources"]["macro"]["available_at_utc"] <= _dt(5)


def test_blank_latest_vintage_never_falls_back() -> None:
    catalog = _catalog(definitions=[_control_definition("macro", max_staleness_hours=10_000)])
    controls = [
        _loaded_control(1, "macro", 0, 0, 9.0, vintage="published"),
        _loaded_control(2, "macro", 0, 1, None, vintage="withdrawn"),
    ]
    joined, accounting = research_contracts._asof_join_incremental(
        [_dt(1)],
        [{"astro": 1.0}],
        [{"decision_at_utc": _dt(1), "row_id": "1:fixture", "target": 1.0}],
        ["astro"],
        1,
        controls,
        catalog,
        ["macro"],
    )
    assert joined == []
    assert accounting["dropped_by_reason"]["control_blank_latest"] == 1
    assert accounting["first_failing_control"]["control_blank_latest"] == {"macro": 1}


def test_complete_case_drop_accounting_has_frozen_precedence_and_inclusive_counts() -> None:
    catalog = _catalog(
        definitions=[
            _control_definition("c1", max_staleness_hours=24),
            _control_definition("c2", max_staleness_hours=10_000),
        ]
    )
    controls = [
        _loaded_control(1, "c1", 0, 2.5, 1.0),
        _loaded_control(2, "c1", 4, 4, 2.0, vintage="fresh"),
        _loaded_control(3, "c2", 3, 3, None, vintage="withdrawn"),
        _loaded_control(4, "c2", 5, 5, 3.0, vintage="restored"),
    ]
    target_days = [-1, 1, 2.1, 3.5, 4, 5]
    targets = [
        {"decision_at_utc": _dt(day), "row_id": f"{index}:fixture", "target": 1.0}
        for index, day in enumerate(target_days, 1)
    ]
    feature_days = [0, 2, 3.5, 4, 5]
    joined, accounting = research_contracts._asof_join_incremental(
        [_dt(day) for day in feature_days],
        [{"astro": float(index)} for index in range(len(feature_days))],
        targets,
        ["astro"],
        12,
        controls,
        catalog,
        ["c1", "c2"],
    )
    assert [row["row_id"] for row in joined] == ["6:fixture"]
    assert accounting["input_rows"] == 4
    assert "control_input_rows" not in accounting
    assert accounting["astronomy_eligible_rows_before_controls"] == 4
    assert "eligible_rows_before_complete_case" not in accounting
    assert accounting["dropped_by_reason"] == {
        "astronomy_no_eligible": 1,
        "astronomy_stale": 1,
        "control_no_eligible": 1,
        "control_stale": 1,
        "control_blank_latest": 1,
    }
    assert sum(accounting["dropped_by_reason"].values()) == accounting["dropped_rows"] == 5
    assert accounting["dropped_by_control"] == {"c1": 4, "c2": 5}
    assert accounting["first_failing_control"]["control_no_eligible"] == {
        "c1": 1,
        "c2": 0,
    }
    assert accounting["first_failing_control"]["control_stale"] == {
        "c1": 1,
        "c2": 0,
    }
    assert accounting["first_failing_control"]["control_blank_latest"] == {
        "c1": 0,
        "c2": 1,
    }


def _interval(start: float, end: float) -> dict[str, datetime]:
    return {"target_start_utc": _dt(start), "target_end_utc": _dt(end)}


def test_half_open_overlap_metadata_freezes_endpoint_and_row_lag() -> None:
    touching = [_interval(0, 1), _interval(1, 2)]
    assert research_contracts.target_overlap_lag(touching) == 0
    assert research_contracts.target_overlap_metadata(touching) == {
        "interval_convention": "half_open_[target_start_utc,target_end_utc)",
        "overlap_condition": "max(start_j,start_i) < min(end_j,end_i)",
        "overlap_lag": 0,
        "actual_overlapping_targets": False,
    }

    overlapping = [_interval(0, 4), _interval(1, 5), _interval(3, 6)]
    assert research_contracts.target_overlap_lag(overlapping) == 2


def test_target_loader_adds_canonical_snapshot_row_id(tmp_path: Path) -> None:
    target = tmp_path / "target.csv"
    fields = [*sorted(research_contracts.TARGET_REQUIRED), "target"]
    raw = {
        "observation_time_utc": "2020-01-01T08:00:00+08:00",
        "available_at_utc": "2020-01-01T08:00:01+08:00",
        "decision_at_utc": "2020-01-01T08:00:02.123456+08:00",
        "execution_at_utc": "2020-01-01T08:00:03+08:00",
        "target_start_utc": "2020-01-01T08:00:03+08:00",
        "target_end_utc": "2020-01-01T08:00:04+08:00",
        "target": "1",
    }
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(raw)
    loaded = research_contracts._load_target_rows(target, "target")
    assert loaded[0]["row_ordinal"] == 1
    assert loaded[0]["row_id"] == "1:2020-01-01T00:00:02.123456Z"


def test_cli_control_options_are_paired_and_mode_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = history_cli.build_parser()
    parsed = parser.parse_args(
        [
            "research",
            "--features",
            "features.csv",
            "--targets",
            "targets.csv",
            "--catalog",
            "catalog.json",
            "--hypothesis",
            "hypothesis.json",
            "--trial-registry",
            "trials.ndjson",
            "--out",
            "result.json",
        ]
    )
    assert parsed.controls is None and parsed.controls_catalog is None
    with pytest.raises(ResearchError, match="同时提供"):
        history_cli._validate_control_option_pair("controls.csv", None)

    legacy_hypothesis = tmp_path / "legacy.json"
    legacy_hypothesis.write_text(json.dumps({"hypothesis_id": "legacy"}), encoding="utf-8")
    code = history_cli.main(
        [
            "research",
            "--features",
            str(tmp_path / "features.csv"),
            "--targets",
            str(tmp_path / "targets.csv"),
            "--catalog",
            str(tmp_path / "catalog.json"),
            "--hypothesis",
            str(legacy_hypothesis),
            "--controls",
            str(tmp_path / "controls.csv"),
            "--controls-catalog",
            str(tmp_path / "controls.json"),
            "--trial-registry",
            str(tmp_path / "trials.ndjson"),
            "--out",
            str(tmp_path / "result.json"),
        ]
    )
    assert code == 2
    assert "未启用时禁止" in capsys.readouterr().err

    enabled_hypothesis = tmp_path / "enabled.json"
    enabled_hypothesis.write_text(
        json.dumps({"incremental_model": {"enabled": True}}), encoding="utf-8"
    )
    code = history_cli.main(
        [
            "research",
            "--features",
            str(tmp_path / "feature-2.csv"),
            "--targets",
            str(tmp_path / "target-2.csv"),
            "--catalog",
            str(tmp_path / "catalog-2.json"),
            "--hypothesis",
            str(enabled_hypothesis),
            "--trial-registry",
            str(tmp_path / "trials-2.ndjson"),
            "--out",
            str(tmp_path / "result-2.json"),
        ]
    )
    assert code == 2
    assert "必须提供" in capsys.readouterr().err

    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"schema_version": "2.0.0"}

    monkeypatch.setattr(history_cli, "run_point_in_time_research", fake_run)
    monkeypatch.setattr(history_cli, "_write_result", lambda *args, **kwargs: None)
    code = history_cli.main(
        [
            "research",
            "--features",
            str(tmp_path / "feature-3.csv"),
            "--targets",
            str(tmp_path / "target-3.csv"),
            "--catalog",
            str(tmp_path / "catalog-3.json"),
            "--hypothesis",
            str(enabled_hypothesis),
            "--controls",
            str(tmp_path / "controls-3.csv"),
            "--controls-catalog",
            str(tmp_path / "controls-3.json"),
            "--trial-registry",
            str(tmp_path / "trials-3.ndjson"),
            "--out",
            str(tmp_path / "result-3.json"),
        ]
    )
    assert code == 0
    assert captured == {
        "controls_csv": str(tmp_path / "controls-3.csv"),
        "controls_catalog_json": str(tmp_path / "controls-3.json"),
    }
