"""Research input contracts, point-in-time alignment, and chronological splits."""

from __future__ import annotations

import csv
import json
import math
import re
from bisect import bisect_right
from datetime import datetime, timedelta
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
    try:
        periods_per_year = float(catalog["periods_per_year"])
    except (TypeError, ValueError) as exc:
        raise ResearchError("periods_per_year 必须是数值") from exc
    if not math.isfinite(periods_per_year) or not 0 < periods_per_year <= 1_000_000:
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
            try:
                period_value = float(period)
            except (TypeError, ValueError) as exc:
                raise ResearchError("effective_period_days 必须是数值") from exc
            if not math.isfinite(period_value) or period_value <= 0:
                raise ResearchError("effective_period_days 必须大于 0")
    try:
        placebo_runs = int(hypothesis["placebo_runs"])
        int(hypothesis["seed"])
        embargo_hours = float(hypothesis["embargo_hours"])
        staleness_hours = float(hypothesis["max_feature_staleness_hours"])
        cost_bps = float(hypothesis.get("cost_bps", 0.0))
    except (TypeError, ValueError) as exc:
        raise ResearchError("placebo/seed/embargo/staleness/cost 参数类型无效") from exc
    if placebo_runs < 99 or placebo_runs > 10_000:
        raise ResearchError("placebo_runs 必须在 99-10,000 之间；确认性研究建议 1000+")
    if not math.isfinite(embargo_hours) or not 0 <= embargo_hours <= 24 * 365 * 10:
        raise ResearchError("embargo_hours 必须在 0 到 10 年之间")
    if not math.isfinite(staleness_hours) or not 0 <= staleness_hours <= 24 * 365:
        raise ResearchError("max_feature_staleness_hours 必须在 0 到 1 年之间")
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 10_000:
        raise ResearchError("cost_bps 必须在 0-10,000 之间")


def _load_feature_rows(
    path: str | Path,
    requested_features: list[str],
) -> tuple[list[datetime], list[dict[str, float]]]:
    source = input_file_path(path, "feature CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "timestamp_utc" not in reader.fieldnames:
            raise ResearchError("feature CSV 必须包含 timestamp_utc")
        if len(reader.fieldnames) > 5_001:
            raise ResearchError("feature CSV 超过 5,000 个 feature 列安全上限")
        missing_features = sorted(set(requested_features) - set(reader.fieldnames))
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


def _load_target_rows(path: str | Path, target_column: str) -> list[dict[str, Any]]:
    source = input_file_path(path, "target CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
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
