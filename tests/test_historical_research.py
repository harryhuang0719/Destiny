from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from historical_research import (
    ResearchError,
    _atomic_write_text,
    _strategy_metrics,
    append_trial_registry,
    aspect_score,
    bh_adjust,
    ensure_distinct_paths,
    features_from_state,
    minimum_angle_deg,
    parse_utc,
    run_point_in_time_research,
    sha256_file,
    signed_angle_deg,
)
from history_cli import main as history_main


def test_circular_geometry_wrap_and_symmetry() -> None:
    assert minimum_angle_deg(359.9, 0.1) == pytest.approx(0.2)
    assert signed_angle_deg(359.9, 0.1) == pytest.approx(-0.2)
    assert signed_angle_deg(0.1, 359.9) == pytest.approx(0.2)
    assert signed_angle_deg(180, 0) == -180
    assert aspect_score(90, 90, 3) == 1.0
    assert aspect_score(80, 90, 3) < 0.01


def test_parse_utc_fails_closed_on_naive_and_pre_utc() -> None:
    with pytest.raises(ResearchError, match="naive"):
        parse_utc("2020-01-01T00:00:00")
    with pytest.raises(ResearchError, match="1972"):
        parse_utc("1950-01-01T00:00:00Z")
    parsed = parse_utc("1950-01-01T08:00:00+08:00", allow_pre_utc=True)
    assert parsed == datetime(1950, 1, 1, tzinfo=timezone.utc)


def test_iso_utc_rejects_naive_datetime() -> None:
    from historical_research import iso_utc

    with pytest.raises(ResearchError, match="主机本地时区"):
        iso_utc(datetime(2020, 1, 1))


def test_features_preserve_directed_and_minimum_angles() -> None:
    state = {
        "timestamp_utc": "2020-01-01T00:00:00Z",
        "bodies": {
            "sun": {
                "longitude_deg": 359.9,
                "latitude_deg": 0,
                "distance_au": 1,
                "longitude_velocity_deg_day": 1,
                "retrograde": False,
            },
            "moon": {
                "longitude_deg": 0.1,
                "latitude_deg": 1,
                "distance_au": 0.0025,
                "longitude_velocity_deg_day": 13,
                "retrograde": False,
            },
        },
    }
    features = features_from_state(state, [("moon", "sun")], harmonics=2)
    assert features["sun_moon_signed_angle_deg"] == pytest.approx(-0.2)
    assert features["sun_moon_separation_deg"] == pytest.approx(0.2)
    assert features["moon_phase_deg"] == pytest.approx(0.2)
    assert features["moon_phase_sin"] ** 2 + features["moon_phase_cos"] ** 2 == pytest.approx(1)
    assert 0 <= features["moon_phase_illumination_proxy"] <= 1


def test_bh_adjust_reference_values() -> None:
    assert bh_adjust([0.01, 0.04, 0.03, 0.002]) == pytest.approx([0.02, 0.04, 0.04, 0.008])


def _write_research_fixture(tmp_path: Path, *, violate_time: bool = False) -> tuple[Path, ...]:
    features = tmp_path / "features.csv"
    targets = tmp_path / "targets.csv"
    catalog = tmp_path / "catalog.json"
    hypothesis = tmp_path / "hypothesis.json"
    registry = tmp_path / "trials.ndjson"
    result = tmp_path / "result.json"
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)

    with features.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_utc", "signal", "noise"])
        writer.writeheader()
        for index in range(75):
            writer.writerow(
                {
                    "timestamp_utc": (start + timedelta(days=index)).isoformat(),
                    "signal": math.sin(2 * math.pi * index / 10),
                    "noise": ((index * 17) % 23) / 23,
                }
            )

    Path(f"{features}.manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "test-v1",
                "source_type": "synthetic_fixture",
                "feature_file_sha256": sha256_file(features),
                "coordinate_profile": "synthetic",
                "frame": {},
                "pre_utc_policy": "strict",
                "body_targets": {},
            }
        ),
        encoding="utf-8",
    )

    target_fields = [
        "observation_time_utc",
        "available_at_utc",
        "decision_at_utc",
        "execution_at_utc",
        "target_start_utc",
        "target_end_utc",
        "target",
    ]
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=target_fields)
        writer.writeheader()
        for index in range(70):
            day = start + timedelta(days=index)
            observation = day.replace(hour=20)
            available = observation + timedelta(minutes=1)
            decision = observation + timedelta(minutes=2)
            execution = day + timedelta(days=1, hours=14, minutes=30)
            if violate_time and index == 4:
                available = decision + timedelta(minutes=1)
            writer.writerow(
                {
                    "observation_time_utc": observation.isoformat(),
                    "available_at_utc": available.isoformat(),
                    "decision_at_utc": decision.isoformat(),
                    "execution_at_utc": execution.isoformat(),
                    "target_start_utc": execution.isoformat(),
                    "target_end_utc": (execution + timedelta(hours=5)).isoformat(),
                    "target": 0.01 * math.sin(2 * math.pi * index / 10)
                    + 0.0001 * ((index % 3) - 1),
                }
            )

    catalog.write_text(
        json.dumps(
            {
                "series_id": "SYNTHETIC-DEMO",
                "vendor": "test-fixture",
                "source": "generated",
                "source_vintage": "v1",
                "instrument_type": "synthetic",
                "currency": "USD",
                "venue": "TEST",
                "exchange_timezone": "UTC",
                "calendar": "daily-synthetic",
                "price_type": "synthetic-total-return",
                "target_kind": "simple_return",
                "target_column": "target",
                "tradable": True,
                "methodology_version": "v1",
                "periods_per_year": 252,
                "overlapping_targets": False,
            }
        ),
        encoding="utf-8",
    )
    hypothesis.write_text(
        json.dumps(
            {
                "hypothesis_id": "synthetic-signal-v1",
                "registered_at_utc": "2019-12-01T00:00:00Z",
                "registered_commit": "fixture",
                "mode": "pseudo_oos",
                "features": [
                    {"name": "signal", "direction": "positive", "effective_period_days": 10},
                    {"name": "noise", "direction": "two-sided", "effective_period_days": 23},
                ],
                "train_end_utc": "2020-01-25T23:59:59Z",
                "validation_end_utc": "2020-02-18T23:59:59Z",
                "embargo_hours": 0,
                "max_feature_staleness_hours": 24,
                "placebo_runs": 99,
                "seed": 42,
                "cost_bps": 1,
            }
        ),
        encoding="utf-8",
    )
    return features, targets, catalog, hypothesis, registry, result


def test_point_in_time_research_is_reproducible_and_logs_trial(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    first = run_point_in_time_research(features, targets, catalog, hypothesis, registry)
    second = run_point_in_time_research(features, targets, catalog, hypothesis, registry)
    assert first["evidence_status"] == "PSEUDO_OOS_ONLY"
    assert first["point_in_time_invariant"].startswith("observation <= available")
    assert first["features"][0]["test"]["pearson"] > 0.99
    assert first["features"][0]["placebo"] == second["features"][0]["placebo"]
    assert first["features"][0]["strategy"] is not None
    placebo = first["features"][0]["placebo"]
    assert placebo["empirical_p"] >= 1 / placebo["finite_group_size"]
    assert first["features"][0]["direction_matches_manifest"] is True
    events = [
        json.loads(line)["event"] for line in registry.read_text(encoding="utf-8").splitlines()
    ]
    assert events == ["STARTED", "COMPLETED", "STARTED", "COMPLETED"]
    assert all(count >= 8 for count in first["splits"].values())


def test_point_in_time_violation_fails_closed(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(
        tmp_path, violate_time=True
    )
    with pytest.raises(ResearchError, match="point-in-time"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)
    events = [
        json.loads(line)["event"] for line in registry.read_text(encoding="utf-8").splitlines()
    ]
    assert events == ["STARTED", "FAILED"]


def test_indicators_or_overlapping_targets_do_not_emit_fake_strategy(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    data = json.loads(catalog.read_text(encoding="utf-8"))
    data["tradable"] = False
    data["instrument_type"] = "indicator"
    catalog.write_text(json.dumps(data), encoding="utf-8")
    result = run_point_in_time_research(features, targets, catalog, hypothesis, registry)
    assert all(item["strategy"] is None for item in result["features"])


def test_history_research_cli_writes_one_auditable_result(tmp_path: Path, capsys) -> None:
    features, targets, catalog, hypothesis, registry, output = _write_research_fixture(tmp_path)
    code = history_main(
        [
            "research",
            "--features",
            str(features),
            "--targets",
            str(targets),
            "--catalog",
            str(catalog),
            "--hypothesis",
            str(hypothesis),
            "--trial-registry",
            str(registry),
            "--out",
            str(output),
        ]
    )
    assert code == 0
    stdout = json.loads(capsys.readouterr().out)
    on_disk = json.loads(output.read_text(encoding="utf-8"))
    assert stdout == on_disk
    assert on_disk["evidence_status"] == "PSEUDO_OOS_ONLY"


def test_feature_manifest_tamper_fails(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    with features.open("a", encoding="utf-8") as handle:
        handle.write("2021-01-01T00:00:00+00:00,0,0\n")
    with pytest.raises(ResearchError, match="SHA-256"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_registry_and_result_may_not_collide_with_inputs(tmp_path: Path, capsys) -> None:
    features, targets, catalog, hypothesis, _registry, _ = _write_research_fixture(tmp_path)
    original_hash = sha256_file(targets)
    with pytest.raises(ResearchError, match="路径冲突"):
        run_point_in_time_research(features, targets, catalog, hypothesis, targets)
    assert sha256_file(targets) == original_hash
    code = history_main(
        [
            "research",
            "--features",
            str(features),
            "--targets",
            str(targets),
            "--catalog",
            str(catalog),
            "--hypothesis",
            str(hypothesis),
            "--trial-registry",
            str(tmp_path / "registry.ndjson"),
            "--out",
            str(features),
            "--overwrite",
        ]
    )
    assert code == 2
    assert "路径冲突" in capsys.readouterr().err


def test_actual_overlapping_targets_override_false_metadata_fails(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    rows = list(csv.DictReader(targets.open(encoding="utf-8")))
    for row in rows:
        start = datetime.fromisoformat(row["target_start_utc"])
        row["target_end_utc"] = (start + timedelta(hours=48)).isoformat()
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ResearchError, match="实际重叠"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_cross_row_execution_and_target_chronology_is_required(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    rows = list(csv.DictReader(targets.open(encoding="utf-8")))
    base = datetime(2021, 1, 1, tzinfo=timezone.utc)
    for index, row in enumerate(rows):
        execution = base + timedelta(days=len(rows) - index)
        row["execution_at_utc"] = execution.isoformat()
        row["target_start_utc"] = execution.isoformat()
        row["target_end_utc"] = (execution + timedelta(hours=5)).isoformat()
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ResearchError, match="execution_at_utc"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_positive_preregistered_direction_rejects_opposite_sign(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    rows = list(csv.DictReader(targets.open(encoding="utf-8")))
    for row in rows:
        row["target"] = str(-float(row["target"]))
    with targets.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    result = run_point_in_time_research(features, targets, catalog, hypothesis, registry)
    signal = result["features"][0]
    assert signal["test"]["pearson"] < -0.99
    assert signal["direction_matches_manifest"] is False
    assert signal["direction_stable"] is False
    assert signal["placebo"]["empirical_p"] > 0.5


def test_future_self_declared_prospective_mode_fails(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    data = json.loads(hypothesis.read_text(encoding="utf-8"))
    data["mode"] = "prospective"
    data["registered_at_utc"] = "2099-01-01T00:00:00Z"
    data["registered_commit"] = "0" * 40
    hypothesis.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ResearchError, match="不能在未来"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_pre_utc_research_requires_explicit_policy(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    features.write_text(
        features.read_text(encoding="utf-8").replace("2020-", "1952-"), encoding="utf-8"
    )
    targets.write_text(
        targets.read_text(encoding="utf-8").replace("2020-", "1952-"), encoding="utf-8"
    )
    manifest_path = Path(f"{features}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["feature_file_sha256"] = sha256_file(features)
    manifest["pre_utc_policy"] = "explicit-proleptic"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hypothesis_data = json.loads(hypothesis.read_text(encoding="utf-8"))
    hypothesis_data["train_end_utc"] = "1952-01-25T23:59:59Z"
    hypothesis_data["validation_end_utc"] = "1952-02-18T23:59:59Z"
    hypothesis.write_text(json.dumps(hypothesis_data), encoding="utf-8")
    with pytest.raises(ResearchError, match="pre_utc_policy"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_atomic_text_write_never_clobbers_without_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "existing.json"
    target.write_text("original", encoding="utf-8")
    with pytest.raises(ResearchError, match="已存在"):
        _atomic_write_text(target, "replacement")
    assert target.read_text(encoding="utf-8") == "original"


def test_distinct_path_check_detects_hardlink_alias(tmp_path: Path) -> None:
    original = tmp_path / "original.csv"
    alias = tmp_path / "alias.csv"
    original.write_text("data", encoding="utf-8")
    os.link(original, alias)
    with pytest.raises(ResearchError, match="inode"):
        ensure_distinct_paths({"input": original, "output": alias})


@pytest.mark.skipif(os.name == "nt", reason="/dev/null is POSIX-specific")
def test_trial_registry_rejects_non_regular_device() -> None:
    with pytest.raises(ResearchError, match="普通文件"):
        append_trial_registry("/dev/null", {"trial": 1})


def test_oversized_csv_field_returns_research_error_not_traceback(tmp_path: Path) -> None:
    features, targets, catalog, hypothesis, registry, _ = _write_research_fixture(tmp_path)
    with features.open("a", encoding="utf-8") as handle:
        handle.write("2021-01-01T00:00:00Z," + "9" * 200_000 + ",0\n")
    manifest_path = Path(f"{features}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["feature_file_sha256"] = sha256_file(features)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ResearchError, match="CSV"):
        run_point_in_time_research(features, targets, catalog, hypothesis, registry)


def test_binary_strategy_and_one_way_cost_accounting() -> None:
    train = [
        {"features": {"binary": value}, "target": target}
        for value, target in [(0, -0.01), (0, -0.01), (0, -0.01), (1, 0.01), (1, 0.01)]
    ]
    test = [
        {"features": {"binary": 1}, "target": 0.0},
        {"features": {"binary": 0}, "target": 0.0},
    ]
    catalog = {
        "tradable": True,
        "overlapping_targets": False,
        "target_kind": "simple_return",
        "periods_per_year": 252,
    }
    metrics = _strategy_metrics(train, test, "binary", "positive", catalog, cost_bps=100)
    assert metrics is not None
    # Initial 0→+1 costs 1%, then +1→-1 trades two one-way units and costs 2%.
    assert metrics["ending_equity"] == pytest.approx(0.99 * 0.98)


def test_history_cli_rejects_nonfinite_aspect_sigma(capsys, tmp_path: Path) -> None:
    code = history_main(
        [
            "build",
            "--kernel",
            str(tmp_path / "missing.bsp"),
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-01-02T00:00:00Z",
            "--out",
            str(tmp_path / "features.csv"),
            "--aspect-sigma",
            "nan",
            "--dry-run",
        ]
    )
    assert code == 2
    assert "有限数值" in capsys.readouterr().err
