"""Research input contracts, point-in-time alignment, and chronological splits."""

from __future__ import annotations

import csv
import json
import math
import re
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

if __package__:  # package import
    from .research_common import (
        MAX_CONFIG_BYTES,
        MAX_MATRIX_CELLS,
        MAX_RESEARCH_ROWS,
        ResearchError,
        input_file_path,
        parse_utc,
    )
else:  # direct scripts import
    from research_common import (
        MAX_CONFIG_BYTES,
        MAX_MATRIX_CELLS,
        MAX_RESEARCH_ROWS,
        ResearchError,
        input_file_path,
        parse_utc,
    )

CATALOG_REQUIRED = {
    "series_id",
    "vendor",
    "source",
    "source_vintage",
    "instrument_type",
    "currency",
    "venue",
    "exchange_timezone",
    "calendar",
    "price_type",
    "target_kind",
    "tradable",
    "methodology_version",
    "periods_per_year",
    "overlapping_targets",
}
TARGET_REQUIRED = {
    "observation_time_utc",
    "available_at_utc",
    "decision_at_utc",
    "execution_at_utc",
    "target_start_utc",
    "target_end_utc",
}

CONTROL_CSV_HEADER = [
    "control_id",
    "observation_time_utc",
    "available_at_utc",
    "vintage_id",
    "value",
]
CONTROL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
CONTROL_CATALOG_REQUIRED = {
    "schema_version",
    "catalog_id",
    "controls_file_sha256",
    "row_semantics",
    "missing_marker",
    "controls",
}
CONTROL_REQUIRED = {
    "control_id",
    "description",
    "control_family",
    "vendor",
    "source",
    "source_vintage",
    "unit",
    "frequency",
    "calendar",
    "exchange_timezone",
    "revision_policy",
    "methodology_version",
    "max_staleness_hours",
}
CONTROL_FAMILIES = {
    "calendar",
    "event",
    "lagged_target",
    "momentum",
    "volatility",
    "market",
    "rates",
    "fx",
    "liquidity",
    "macro",
    "other",
}
REVISION_POLICIES = {"non_revisioned", "as_published_revisions"}
INCREMENTAL_MODEL_REQUIRED = {
    "enabled",
    "estimator",
    "control_ids",
    "alpha_grid",
    "fit_intercept",
    "standardization",
    "missing_data_policy",
    "primary_loss",
    "hac_lag",
    "bootstrap",
    "full_pipeline_placebo",
    "multiple_testing",
}
BOOTSTRAP_REQUIRED = {
    "method",
    "runs",
    "block_length",
    "confidence_level",
    "seed",
}
PLACEBO_REQUIRED = {"method", "runs", "seed"}
MULTIPLE_TESTING_REQUIRED = {
    "family_id",
    "family_size",
    "family_index",
    "method",
    "alpha",
}


def _strict_object_keys(value: Any, required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ResearchError(f"{label} 必须是 JSON object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        raise ResearchError(f"{label} 缺少字段: {', '.join(missing)}")
    if unknown:
        raise ResearchError(f"{label} 含未知字段: {', '.join(unknown)}")
    return value


def _nonempty_string(value: Any, label: str, *, max_length: int = 1_024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ResearchError(f"{label} 必须是 1-{max_length} 字符的非空字符串")
    return value


def _json_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchError(f"{label} 必须是 JSON number，boolean 不算数值")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise ResearchError(f"{label} 必须是有限数值") from exc
    if not math.isfinite(parsed):
        raise ResearchError(f"{label} 必须是有限数值")
    return parsed


def _json_integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchError(f"{label} 必须是 JSON integer，boolean 不算整数")
    if not minimum <= value <= maximum:
        raise ResearchError(f"{label} 必须在 {minimum:,}-{maximum:,} 之间")
    return value


def incremental_model_enabled(hypothesis: dict[str, Any]) -> bool:
    """Return the frozen v2.2 mode without accepting a loose false object."""
    if "incremental_model" not in hypothesis:
        return False
    model = hypothesis["incremental_model"]
    if isinstance(model, dict) and set(model) == {"enabled"} and model["enabled"] is False:
        return False
    if not isinstance(model, dict):
        raise ResearchError("incremental_model 必须是 JSON object")
    if model.get("enabled") is not True:
        raise ResearchError('incremental_model 禁用时必须精确等于 {"enabled": false}')
    return True


def validate_controls_catalog(catalog: dict[str, Any], controls_hash: str) -> None:
    """Validate the exact v2.2 long point-in-time controls catalog."""
    _strict_object_keys(catalog, CONTROL_CATALOG_REQUIRED, "controls catalog")
    if catalog["schema_version"] != "2.0.0":
        raise ResearchError("controls catalog schema_version 必须是 2.0.0")
    _nonempty_string(catalog["catalog_id"], "controls catalog catalog_id")
    expected_hash = catalog["controls_file_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ResearchError("controls_file_sha256 必须是 64 位小写十六进制 SHA-256")
    if not isinstance(controls_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", controls_hash):
        raise ResearchError("实际 controls CSV SHA-256 无效")
    if expected_hash != controls_hash:
        raise ResearchError("controls catalog 的 SHA-256 与实际 controls CSV 不一致")
    if catalog["row_semantics"] != "long_point_in_time_v1":
        raise ResearchError("controls catalog row_semantics 必须是 long_point_in_time_v1")
    if catalog["missing_marker"] != "empty_value_only":
        raise ResearchError("controls catalog missing_marker 必须是 empty_value_only")

    controls = catalog["controls"]
    if not isinstance(controls, list) or not 1 <= len(controls) <= 128:
        raise ResearchError("controls catalog controls 必须包含 1-128 项")
    seen: set[str] = set()
    for index, raw in enumerate(controls, 1):
        label = f"controls catalog controls[{index}]"
        control = _strict_object_keys(raw, CONTROL_REQUIRED, label)
        control_id = control["control_id"]
        if not isinstance(control_id, str) or CONTROL_ID_PATTERN.fullmatch(control_id) is None:
            raise ResearchError(f"{label}.control_id 格式无效")
        if control_id in seen:
            raise ResearchError(f"controls catalog control_id 重复: {control_id}")
        seen.add(control_id)
        for key in CONTROL_REQUIRED - {
            "control_id",
            "control_family",
            "revision_policy",
            "max_staleness_hours",
        }:
            _nonempty_string(control[key], f"{label}.{key}")
        if control["control_family"] not in CONTROL_FAMILIES:
            raise ResearchError(f"{label}.control_family 无效")
        if control["revision_policy"] not in REVISION_POLICIES:
            raise ResearchError(f"{label}.revision_policy 无效")
        staleness = _json_number(control["max_staleness_hours"], f"{label}.max_staleness_hours")
        if not 0 <= staleness <= 87_600:
            raise ResearchError(f"{label}.max_staleness_hours 必须在 0-87,600 之间")


def _load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    source = input_file_path(path, label, MAX_CONFIG_BYTES)
    try:
        data = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ResearchError(f"无法读取 {label}: {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ResearchError(f"{label} 顶层必须是 JSON object")
    return data


def validate_catalog(catalog: dict[str, Any]) -> None:
    missing = sorted(CATALOG_REQUIRED - set(catalog))
    if missing:
        raise ResearchError(f"series catalog 缺少字段: {', '.join(missing)}")
    if not isinstance(catalog["tradable"], bool) or not isinstance(
        catalog["overlapping_targets"], bool
    ):
        raise ResearchError("catalog 的 tradable/overlapping_targets 必须是 boolean")
    periods_per_year = _json_number(catalog["periods_per_year"], "periods_per_year")
    if not 0 < periods_per_year <= 1_000_000:
        raise ResearchError("periods_per_year 必须在 0-1,000,000 之间")
    target_column = catalog.get("target_column", "target")
    if not isinstance(target_column, str) or not target_column.strip():
        raise ResearchError("target_column 必须是非空字符串")


def validate_feature_manifest(manifest: dict[str, Any], feature_hash: str) -> None:
    required = {
        "schema_version",
        "source_type",
        "feature_file_sha256",
        "coordinate_profile",
        "frame",
        "pre_utc_policy",
        "body_targets",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ResearchError(f"feature manifest 缺少字段: {', '.join(missing)}")
    if manifest["feature_file_sha256"] != feature_hash:
        raise ResearchError("feature manifest 的 SHA-256 与实际 feature CSV 不一致")
    if manifest["source_type"] == "jpl_spk":
        kernel_hash = manifest.get("kernel_sha256")
        if not isinstance(kernel_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", kernel_hash):
            raise ResearchError("JPL feature manifest 必须包含合法 kernel_sha256")
    elif manifest["source_type"] != "synthetic_fixture":
        raise ResearchError("feature manifest source_type 必须是 jpl_spk 或 synthetic_fixture")
    if manifest["pre_utc_policy"] not in ("strict", "explicit-proleptic"):
        raise ResearchError("feature manifest pre_utc_policy 无效")
    if not isinstance(manifest["frame"], dict) or not isinstance(manifest["body_targets"], dict):
        raise ResearchError("feature manifest frame/body_targets 必须是 objects")


def _require_fixed(value: Any, expected: Any, label: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ResearchError(f"{label} 必须精确等于 {expected!r}")


def _validate_incremental_model(hypothesis: dict[str, Any]) -> None:
    if not incremental_model_enabled(hypothesis):
        return
    if hypothesis.get("hypothesis_schema_version") != "2.0.0":
        raise ResearchError("incremental 模式的 hypothesis_schema_version 必须是 2.0.0")

    model = _strict_object_keys(
        hypothesis["incremental_model"],
        INCREMENTAL_MODEL_REQUIRED,
        "incremental_model",
    )
    for key, expected in {
        "enabled": True,
        "estimator": "ridge_linear_v1",
        "fit_intercept": True,
        "standardization": "population_zscore_fit_rows_only",
        "missing_data_policy": "complete_case_no_imputation",
        "primary_loss": "squared_error",
    }.items():
        _require_fixed(model[key], expected, f"incremental_model.{key}")

    control_ids = model["control_ids"]
    if not isinstance(control_ids, list) or not 1 <= len(control_ids) <= 128:
        raise ResearchError("incremental_model.control_ids 必须包含 1-128 项")
    seen_controls: set[str] = set()
    for control_id in control_ids:
        if not isinstance(control_id, str) or CONTROL_ID_PATTERN.fullmatch(control_id) is None:
            raise ResearchError("incremental_model.control_ids 含无效 control_id")
        if control_id in seen_controls:
            raise ResearchError(f"incremental_model.control_ids 重复: {control_id}")
        seen_controls.add(control_id)
    if len(control_ids) + len(hypothesis["features"]) > 384:
        raise ResearchError("预注册 controls 加 astronomy features 最多 384 列")

    alpha_grid = model["alpha_grid"]
    if not isinstance(alpha_grid, list) or not 1 <= len(alpha_grid) <= 16:
        raise ResearchError("incremental_model.alpha_grid 必须包含 1-16 项")
    parsed_alphas: list[float] = []
    for index, alpha in enumerate(alpha_grid):
        parsed = _json_number(alpha, f"incremental_model.alpha_grid[{index}]")
        if not 1e-8 <= parsed <= 1e12:
            raise ResearchError("incremental_model.alpha_grid 必须在 1e-8 到 1e12 之间")
        parsed_alphas.append(parsed)
    if any(left >= right for left, right in pairwise(parsed_alphas)):
        raise ResearchError("incremental_model.alpha_grid 必须严格递增且无重复")

    _json_integer(model["hac_lag"], "incremental_model.hac_lag", 0, 1_024)

    bootstrap = _strict_object_keys(
        model["bootstrap"], BOOTSTRAP_REQUIRED, "incremental_model.bootstrap"
    )
    _require_fixed(bootstrap["method"], "circular_block_v1", "incremental_model.bootstrap.method")
    _json_integer(bootstrap["runs"], "incremental_model.bootstrap.runs", 999, 10_000)
    _json_integer(
        bootstrap["block_length"],
        "incremental_model.bootstrap.block_length",
        1,
        1_024,
    )
    confidence = _json_number(
        bootstrap["confidence_level"], "incremental_model.bootstrap.confidence_level"
    )
    if confidence != 0.95:
        raise ResearchError("incremental_model.bootstrap.confidence_level 必须精确等于 0.95")
    _json_integer(
        bootstrap["seed"],
        "incremental_model.bootstrap.seed",
        0,
        2**63 - 1,
    )

    placebo = _strict_object_keys(
        model["full_pipeline_placebo"],
        PLACEBO_REQUIRED,
        "incremental_model.full_pipeline_placebo",
    )
    _require_fixed(
        placebo["method"],
        "joint_circular_shift_v1",
        "incremental_model.full_pipeline_placebo.method",
    )
    _json_integer(
        placebo["runs"],
        "incremental_model.full_pipeline_placebo.runs",
        99,
        2_000,
    )
    _json_integer(
        placebo["seed"],
        "incremental_model.full_pipeline_placebo.seed",
        0,
        2**63 - 1,
    )

    multiple = _strict_object_keys(
        model["multiple_testing"],
        MULTIPLE_TESTING_REQUIRED,
        "incremental_model.multiple_testing",
    )
    _nonempty_string(
        multiple["family_id"], "incremental_model.multiple_testing.family_id", max_length=128
    )
    family_size = _json_integer(
        multiple["family_size"],
        "incremental_model.multiple_testing.family_size",
        1,
        10_000,
    )
    family_index = _json_integer(
        multiple["family_index"],
        "incremental_model.multiple_testing.family_index",
        1,
        10_000,
    )
    if family_index > family_size:
        raise ResearchError("incremental_model.multiple_testing.family_index 不得大于 family_size")
    _require_fixed(multiple["method"], "bonferroni", "incremental_model.multiple_testing.method")
    family_alpha = _json_number(multiple["alpha"], "incremental_model.multiple_testing.alpha")
    if not 0 < family_alpha <= 0.25:
        raise ResearchError("incremental_model.multiple_testing.alpha 必须在 (0, 0.25] 内")


def validate_hypothesis(hypothesis: dict[str, Any]) -> None:
    required = {
        "hypothesis_id",
        "registered_at_utc",
        "registered_commit",
        "mode",
        "features",
        "train_end_utc",
        "validation_end_utc",
        "embargo_hours",
        "max_feature_staleness_hours",
        "placebo_runs",
        "seed",
    }
    missing = sorted(required - set(hypothesis))
    if missing:
        raise ResearchError(f"hypothesis manifest 缺少字段: {', '.join(missing)}")
    if hypothesis["mode"] not in ("exploratory", "pseudo_oos", "prospective"):
        raise ResearchError("mode 必须是 exploratory、pseudo_oos 或 prospective")
    if not isinstance(hypothesis["hypothesis_id"], str) or not hypothesis["hypothesis_id"].strip():
        raise ResearchError("hypothesis_id 必须是非空字符串")
    parse_utc(hypothesis["registered_at_utc"], allow_pre_utc=True)
    if (
        not isinstance(hypothesis["registered_commit"], str)
        or not hypothesis["registered_commit"].strip()
    ):
        raise ResearchError("registered_commit 必须是非空字符串")
    if not isinstance(hypothesis["features"], list) or not hypothesis["features"]:
        raise ResearchError("features 必须是非空数组")
    if len(hypothesis["features"]) > 300:
        raise ResearchError("单次预注册 feature family 最多 300 项")
    seen = set()
    for feature in hypothesis["features"]:
        if not isinstance(feature, dict) or "name" not in feature:
            raise ResearchError("每个 feature 必须至少包含 name")
        if not isinstance(feature["name"], str) or not 0 < len(feature["name"]) <= 200:
            raise ResearchError("feature name 必须是 1-200 字符的字符串")
        if feature["name"] in seen:
            raise ResearchError(f"重复 feature: {feature['name']}")
        seen.add(feature["name"])
        direction = feature.get("direction", "two-sided")
        if direction not in ("positive", "negative", "two-sided"):
            raise ResearchError(f"feature {feature['name']} 的 direction 无效")
        period = feature.get("effective_period_days")
        if period is not None:
            period_value = _json_number(period, "effective_period_days")
            if period_value <= 0:
                raise ResearchError("effective_period_days 必须大于 0")
    try:
        placebo_runs = int(hypothesis["placebo_runs"])
        int(hypothesis["seed"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchError("placebo/seed 参数类型无效") from exc
    embargo_hours = _json_number(hypothesis["embargo_hours"], "embargo_hours")
    staleness_hours = _json_number(
        hypothesis["max_feature_staleness_hours"], "max_feature_staleness_hours"
    )
    cost_bps = _json_number(hypothesis.get("cost_bps", 0.0), "cost_bps")
    if placebo_runs < 99 or placebo_runs > 10_000:
        raise ResearchError("placebo_runs 必须在 99-10,000 之间；确认性研究建议 1000+")
    if not 0 <= embargo_hours <= 24 * 365 * 10:
        raise ResearchError("embargo_hours 必须在 0 到 10 年之间")
    if not 0 <= staleness_hours <= 24 * 365:
        raise ResearchError("max_feature_staleness_hours 必须在 0 到 1 年之间")
    if not 0 <= cost_bps <= 10_000:
        raise ResearchError("cost_bps 必须在 0-10,000 之间")
    _validate_incremental_model(hypothesis)


def _validated_csv_header(reader: csv.DictReader, label: str) -> list[str]:
    fieldnames = reader.fieldnames
    if not fieldnames:
        raise ResearchError(f"{label} header 不能为空")
    if any(not isinstance(name, str) or not name.strip() for name in fieldnames):
        raise ResearchError(f"{label} header 不得包含空字段名")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in fieldnames:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise ResearchError(f"{label} header 含重复字段: {', '.join(sorted(duplicates))}")
    return fieldnames


def _load_feature_rows(
    path: str | Path,
    requested_features: list[str],
) -> tuple[list[datetime], list[dict[str, float]]]:
    source = input_file_path(path, "feature CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = _validated_csv_header(reader, "feature CSV")
        if "timestamp_utc" not in fieldnames:
            raise ResearchError("feature CSV 必须包含 timestamp_utc")
        if len(fieldnames) > 5_001:
            raise ResearchError("feature CSV 超过 5,000 个 feature 列安全上限")
        missing_features = sorted(set(requested_features) - set(fieldnames))
        if missing_features:
            raise ResearchError(f"feature CSV 不含预注册字段: {', '.join(missing_features)}")
        feature_names = requested_features
        times, rows = [], []
        for line_number, row in enumerate(reader, 2):
            if line_number > MAX_RESEARCH_ROWS + 1:
                raise ResearchError(f"feature CSV 超过 {MAX_RESEARCH_ROWS:,} 行安全上限")
            if (line_number - 1) * len(feature_names) > MAX_MATRIX_CELLS:
                raise ResearchError(
                    f"feature matrix 超过 {MAX_MATRIX_CELLS:,} cells 安全上限；缩小日期或预注册 family"
                )
            timestamp = parse_utc(row["timestamp_utc"], allow_pre_utc=True)
            values: dict[str, float] = {}
            for name in feature_names:
                try:
                    value = float(row[name])
                except (TypeError, ValueError) as exc:
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 不是数值") from exc
                if not math.isfinite(value):
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 非有限值")
                if abs(value) > 1e100:
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 绝对值过大")
                values[name] = value
            times.append(timestamp)
            rows.append(values)
    if not times:
        raise ResearchError("feature CSV 没有数据")
    if any(a >= b for a, b in pairwise(times)):
        raise ResearchError("feature timestamp_utc 必须严格递增且无重复")
    return times, rows


def _control_catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    controls = catalog.get("controls")
    if not isinstance(controls, list):
        raise ResearchError("controls catalog controls 必须是 array")
    return {
        control["control_id"]: control
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("control_id"), str)
    }


def _load_control_rows(
    path: str | Path,
    catalog: dict[str, Any],
    requested_control_ids: list[str],
) -> list[dict[str, Any]]:
    """Load the exact long-table contract from a stable controls snapshot."""
    catalog_by_id = _control_catalog_index(catalog)
    unknown_requested = [
        control_id for control_id in requested_control_ids if control_id not in catalog_by_id
    ]
    if unknown_requested:
        raise ResearchError(f"预注册 control 不在 controls catalog: {', '.join(unknown_requested)}")

    source = input_file_path(path, "controls CSV")
    rows: list[dict[str, Any]] = []
    previous_key: tuple[str, datetime, datetime] | None = None
    non_revisioned_seen: set[tuple[str, datetime]] = set()
    row_counts = {control_id: 0 for control_id in requested_control_ids}
    try:
        with source.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != CONTROL_CSV_HEADER:
                raise ResearchError(
                    "controls CSV header 必须精确等于: " + ",".join(CONTROL_CSV_HEADER)
                )
            for line_number, raw in enumerate(reader, 2):
                if line_number > MAX_RESEARCH_ROWS + 1:
                    raise ResearchError(f"controls CSV 超过 {MAX_RESEARCH_ROWS:,} 行安全上限")
                if None in raw or any(raw.get(field) is None for field in CONTROL_CSV_HEADER):
                    raise ResearchError(f"controls CSV 第 {line_number} 行列数与 header 不一致")

                control_id = raw["control_id"]
                if CONTROL_ID_PATTERN.fullmatch(control_id) is None:
                    raise ResearchError(f"controls CSV 第 {line_number} 行 control_id 格式无效")
                control = catalog_by_id.get(control_id)
                if control is None:
                    raise ResearchError(
                        f"controls CSV 第 {line_number} 行 control_id 不在 catalog: {control_id}"
                    )
                observation = parse_utc(raw["observation_time_utc"], allow_pre_utc=True)
                available = parse_utc(raw["available_at_utc"], allow_pre_utc=True)
                if observation > available:
                    raise ResearchError(
                        f"controls CSV 第 {line_number} 行违反 observation_time_utc <= available_at_utc"
                    )

                vintage_id = raw["vintage_id"]
                if not vintage_id.strip() or len(vintage_id) > 128:
                    raise ResearchError(
                        f"controls CSV 第 {line_number} 行 vintage_id 必须是 1-128 字符"
                    )
                raw_value = raw["value"]
                if raw_value == "":
                    value: float | None = None
                else:
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError) as exc:
                        raise ResearchError(
                            f"controls CSV 第 {line_number} 行 value 不是有限 float"
                        ) from exc
                    if not math.isfinite(value):
                        raise ResearchError(
                            f"controls CSV 第 {line_number} 行 value 不是有限 float"
                        )
                    if abs(value) > 1e100:
                        raise ResearchError(
                            f"controls CSV 第 {line_number} 行 value 绝对值超过 1e100"
                        )

                sort_key = (control_id, observation, available)
                if previous_key is not None and sort_key <= previous_key:
                    if sort_key == previous_key:
                        raise ResearchError(
                            f"controls CSV 第 {line_number} 行 ordering tuple 重复且 vintage 歧义"
                        )
                    raise ResearchError(
                        "controls CSV 必须按 "
                        "(control_id, observation_time_utc, available_at_utc) 严格递增"
                    )
                previous_key = sort_key

                observation_key = (control_id, observation)
                if control["revision_policy"] == "non_revisioned":
                    if observation_key in non_revisioned_seen:
                        raise ResearchError(
                            f"non_revisioned control {control_id} 的 observation_time_utc 重复"
                        )
                    non_revisioned_seen.add(observation_key)

                if control_id in row_counts:
                    row_counts[control_id] += 1
                rows.append(
                    {
                        "row_ordinal": line_number - 1,
                        "control_id": control_id,
                        "observation_time_utc": observation,
                        "available_at_utc": available,
                        "vintage_id": vintage_id,
                        "value": value,
                    }
                )
    except ResearchError:
        raise
    except (csv.Error, UnicodeError, OSError) as exc:
        raise ResearchError(f"无法安全解析 controls CSV: {type(exc).__name__}: {exc}") from exc

    missing_requested = [
        control_id for control_id in requested_control_ids if row_counts[control_id] == 0
    ]
    if missing_requested:
        raise ResearchError(
            f"预注册 control 在 controls CSV 中没有数据: {', '.join(missing_requested)}"
        )
    return rows


def _canonical_row_id(row_ordinal: int, decision_at_utc: datetime) -> str:
    normalized = (
        decision_at_utc.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    return f"{row_ordinal}:{normalized}"


def _load_target_rows(path: str | Path, target_column: str) -> list[dict[str, Any]]:
    source = input_file_path(path, "target CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(_validated_csv_header(reader, "target CSV"))
        missing = sorted((TARGET_REQUIRED | {target_column}) - fields)
        if missing:
            raise ResearchError(f"target CSV 缺少字段: {', '.join(missing)}")
        rows = []
        for line_number, raw in enumerate(reader, 2):
            if line_number > MAX_RESEARCH_ROWS + 1:
                raise ResearchError(f"target CSV 超过 {MAX_RESEARCH_ROWS:,} 行安全上限")
            parsed = {field: parse_utc(raw[field], allow_pre_utc=True) for field in TARGET_REQUIRED}
            if not (
                parsed["observation_time_utc"]
                <= parsed["available_at_utc"]
                <= parsed["decision_at_utc"]
                < parsed["execution_at_utc"]
                <= parsed["target_start_utc"]
                < parsed["target_end_utc"]
            ):
                raise ResearchError(
                    f"target CSV 第 {line_number} 行违反 point-in-time 顺序: "
                    "observation <= available <= decision < execution <= target_start < target_end"
                )
            try:
                target = float(raw[target_column])
            except (TypeError, ValueError) as exc:
                raise ResearchError(f"target CSV 第 {line_number} 行 target 不是数值") from exc
            if not math.isfinite(target):
                raise ResearchError(f"target CSV 第 {line_number} 行 target 非有限值")
            if abs(target) > 1e100:
                raise ResearchError(f"target CSV 第 {line_number} 行 target 绝对值过大")
            parsed["target"] = target
            parsed["row_ordinal"] = line_number - 1
            parsed["row_id"] = _canonical_row_id(line_number - 1, parsed["decision_at_utc"])
            rows.append(parsed)
    if not rows:
        raise ResearchError("target CSV 没有数据")
    decisions = [row["decision_at_utc"] for row in rows]
    if any(a >= b for a, b in pairwise(decisions)):
        raise ResearchError("decision_at_utc 必须严格递增且无重复")
    for field in ("execution_at_utc", "target_start_utc", "target_end_utc"):
        timeline = [row[field] for row in rows]
        if any(a >= b for a, b in pairwise(timeline)):
            raise ResearchError(f"{field} 必须按 decision 行顺序严格递增")
    return rows


def target_intervals_overlap(rows: list[dict[str, Any]]) -> bool:
    intervals = sorted((row["target_start_utc"], row["target_end_utc"]) for row in rows)
    latest_end: datetime | None = None
    for start, end in intervals:
        if latest_end is not None and start < latest_end:
            return True
        latest_end = end if latest_end is None else max(latest_end, end)
    return False


def target_overlap_lag(rows: list[dict[str, Any]]) -> int:
    """Return the greatest row lag among half-open overlapping intervals."""
    if len(rows) < 2:
        return 0
    starts = [row["target_start_utc"] for row in rows]
    ends = [row["target_end_utc"] for row in rows]
    if any(start >= end for start, end in zip(starts, ends, strict=True)):
        raise ResearchError("target interval 必须满足 target_start_utc < target_end_utc")
    if any(left >= right for left, right in pairwise(starts)) or any(
        left >= right for left, right in pairwise(ends)
    ):
        raise ResearchError("target intervals 必须按行保持 start/end 严格递增")

    earliest_active = 0
    overlap_lag = 0
    for index in range(1, len(rows)):
        # Half-open intervals touching at an endpoint do not overlap.
        while earliest_active < index and ends[earliest_active] <= starts[index]:
            earliest_active += 1
        if earliest_active < index:
            overlap_lag = max(overlap_lag, index - earliest_active)
    return overlap_lag


def target_overlap_metadata(rows: list[dict[str, Any]]) -> dict[str, Any]:
    overlap_lag = target_overlap_lag(rows)
    return {
        "interval_convention": "half_open_[target_start_utc,target_end_utc)",
        "overlap_condition": "max(start_j,start_i) < min(end_j,end_i)",
        "overlap_lag": overlap_lag,
        "actual_overlapping_targets": overlap_lag > 0,
    }


def _prepare_control_states(
    control_rows: list[dict[str, Any]], control_ids: list[str]
) -> dict[str, dict[str, Any]]:
    grouped = {control_id: [] for control_id in control_ids}
    for row in control_rows:
        bucket = grouped.get(row["control_id"])
        if bucket is not None:
            bucket.append(row)
    states: dict[str, dict[str, Any]] = {}
    for control_id in control_ids:
        events = sorted(
            grouped[control_id],
            key=lambda row: (
                row["available_at_utc"],
                row["observation_time_utc"],
                row["row_ordinal"],
            ),
        )
        states[control_id] = {
            "events": events,
            "cursor": 0,
            "latest_by_observation": {},
            "latest_observation": None,
        }
    return states


def _select_control_asof(
    state: dict[str, Any], decision_at_utc: datetime, max_staleness_hours: float
) -> tuple[str, dict[str, Any] | None, float | None]:
    events: list[dict[str, Any]] = state["events"]
    cursor: int = state["cursor"]
    latest_by_observation: dict[datetime, dict[str, Any]] = state["latest_by_observation"]
    latest_observation: datetime | None = state["latest_observation"]
    while cursor < len(events) and events[cursor]["available_at_utc"] <= decision_at_utc:
        row = events[cursor]
        observation = row["observation_time_utc"]
        if observation > row["available_at_utc"]:
            raise AssertionError("control row violates observation <= available")
        latest_by_observation[observation] = row
        if latest_observation is None or observation > latest_observation:
            latest_observation = observation
        cursor += 1
    state["cursor"] = cursor
    state["latest_observation"] = latest_observation
    if latest_observation is None:
        return "control_no_eligible", None, None

    selected = latest_by_observation[latest_observation]
    if selected["available_at_utc"] > decision_at_utc:
        raise AssertionError("as-of join selected a future control vintage")
    staleness = (decision_at_utc - latest_observation).total_seconds() / 3_600
    if staleness < 0:
        raise AssertionError("as-of join selected a future control observation")
    if staleness > max_staleness_hours:
        return "control_stale", selected, staleness
    if selected["value"] is None:
        return "control_blank_latest", selected, staleness
    return "ok", selected, staleness


def _asof_join_incremental(
    feature_times: list[datetime],
    feature_rows: list[dict[str, float]],
    targets: list[dict[str, Any]],
    feature_names: list[str],
    max_feature_staleness_hours: float,
    control_rows: list[dict[str, Any]],
    controls_catalog: dict[str, Any],
    control_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build one shared complete-case sample for M0 and M2."""
    decisions = [row["decision_at_utc"] for row in targets]
    if any(left >= right for left, right in pairwise(decisions)):
        raise ResearchError("incremental target decision_at_utc 必须严格递增")
    if len(feature_times) != len(feature_rows):
        raise ResearchError("feature timestamps 与 rows 数量不一致")

    catalog_by_id = _control_catalog_index(controls_catalog)
    missing_catalog = [control_id for control_id in control_ids if control_id not in catalog_by_id]
    if missing_catalog:
        raise ResearchError(f"预注册 control 不在 controls catalog: {', '.join(missing_catalog)}")
    states = _prepare_control_states(control_rows, control_ids)

    reason_names = (
        "astronomy_no_eligible",
        "astronomy_stale",
        "control_no_eligible",
        "control_stale",
        "control_blank_latest",
    )
    control_reason_names = reason_names[2:]
    dropped_by_reason = {reason: 0 for reason in reason_names}
    first_failing_control = {
        reason: {control_id: 0 for control_id in control_ids} for reason in control_reason_names
    }
    dropped_by_control = {control_id: 0 for control_id in control_ids}
    dropped_by_control_reason = {
        control_id: {reason: 0 for reason in control_reason_names} for control_id in control_ids
    }
    joined: list[dict[str, Any]] = []
    astronomy_eligible = 0

    for target in targets:
        decision = target["decision_at_utc"]
        feature_index = bisect_right(feature_times, decision) - 1
        if feature_index < 0:
            astronomy_status = "astronomy_no_eligible"
            feature_time = None
            feature_staleness = None
        else:
            feature_time = feature_times[feature_index]
            feature_staleness = (decision - feature_time).total_seconds() / 3_600
            if feature_staleness < 0:
                raise AssertionError("as-of join selected a future feature")
            astronomy_status = (
                "astronomy_stale" if feature_staleness > max_feature_staleness_hours else "ok"
            )
            if astronomy_status == "ok":
                astronomy_eligible += 1

        selected_controls: dict[str, float] = {}
        control_sources: dict[str, dict[str, Any]] = {}
        control_statuses: dict[str, str] = {}
        for control_id in control_ids:
            max_staleness = float(catalog_by_id[control_id]["max_staleness_hours"])
            status, selected, staleness = _select_control_asof(
                states[control_id], decision, max_staleness
            )
            control_statuses[control_id] = status
            if status != "ok":
                dropped_by_control[control_id] += 1
                dropped_by_control_reason[control_id][status] += 1
                continue
            if selected is None or staleness is None or selected["value"] is None:
                raise AssertionError("successful control selection is incomplete")
            selected_controls[control_id] = selected["value"]
            control_sources[control_id] = {
                "row_ordinal": selected["row_ordinal"],
                "observation_time_utc": selected["observation_time_utc"],
                "available_at_utc": selected["available_at_utc"],
                "vintage_id": selected["vintage_id"],
                "staleness_hours": staleness,
            }

        if astronomy_status != "ok":
            dropped_by_reason[astronomy_status] += 1
            continue
        first_control_failure: tuple[str, str] | None = next(
            (
                (control_id, control_statuses[control_id])
                for control_id in control_ids
                if control_statuses[control_id] != "ok"
            ),
            None,
        )
        if first_control_failure is not None:
            control_id, reason = first_control_failure
            dropped_by_reason[reason] += 1
            first_failing_control[reason][control_id] += 1
            continue

        if feature_time is None or feature_staleness is None:
            raise AssertionError("successful astronomy selection is incomplete")
        values = feature_rows[feature_index]
        missing_features = [name for name in feature_names if name not in values]
        if missing_features:
            raise ResearchError(f"feature CSV 不含预注册字段: {', '.join(missing_features)}")
        joined.append(
            {
                **target,
                "feature_timestamp_utc": feature_time,
                "feature_staleness_hours": feature_staleness,
                "features": {name: values[name] for name in feature_names},
                "controls": selected_controls,
                "control_sources": control_sources,
            }
        )

    return joined, {
        "method": "latest observation then latest available vintage; backward only",
        "complete_case_policy": "complete_case_no_imputation",
        "input_rows": len(control_rows),
        "target_rows": len(targets),
        "astronomy_eligible_rows_before_controls": astronomy_eligible,
        "complete_case_rows": len(joined),
        "dropped_rows": len(targets) - len(joined),
        "dropped_by_reason": dropped_by_reason,
        "first_failing_control": first_failing_control,
        "dropped_by_control": dropped_by_control,
        "dropped_by_control_reason": dropped_by_control_reason,
    }


def _asof_join(
    feature_times: list[datetime],
    feature_rows: list[dict[str, float]],
    targets: list[dict[str, Any]],
    feature_names: list[str],
    max_staleness_hours: float,
) -> list[dict[str, Any]]:
    joined = []
    for target in targets:
        index = bisect_right(feature_times, target["decision_at_utc"]) - 1
        if index < 0:
            continue
        feature_time = feature_times[index]
        staleness = (target["decision_at_utc"] - feature_time).total_seconds() / 3600
        if staleness < 0:
            raise AssertionError("as-of join selected a future feature")
        if staleness > max_staleness_hours:
            continue
        values = feature_rows[index]
        missing = [name for name in feature_names if name not in values]
        if missing:
            raise ResearchError(f"feature CSV 不含预注册字段: {', '.join(missing)}")
        joined.append(
            {
                **target,
                "feature_timestamp_utc": feature_time,
                "feature_staleness_hours": staleness,
                "features": {name: values[name] for name in feature_names},
            }
        )
    return joined


def _split_rows(
    rows: list[dict[str, Any]],
    train_end: datetime,
    validation_end: datetime,
    embargo_hours: float,
) -> dict[str, list[dict[str, Any]]]:
    if validation_end <= train_end:
        raise ResearchError("validation_end 必须晚于 train_end")
    embargo = timedelta(hours=embargo_hours)
    splits = {"train": [], "validation": [], "test": []}
    for row in rows:
        decision, target_end = row["decision_at_utc"], row["target_end_utc"]
        if decision <= train_end and target_end <= train_end:
            splits["train"].append(row)
        elif train_end + embargo < decision <= validation_end and target_end <= validation_end:
            splits["validation"].append(row)
        elif decision > validation_end + embargo:
            splits["test"].append(row)
    for name, split in splits.items():
        if len(split) < 8:
            raise ResearchError(f"{name} 有效样本仅 {len(split)}，至少需要 8")
    return splits
