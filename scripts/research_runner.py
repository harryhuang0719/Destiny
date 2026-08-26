"""Audited point-in-time research orchestration and trial lifecycle."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__:  # package import
    from .research_common import (
        MAX_CONFIG_BYTES,
        RESEARCH_SCHEMA_VERSION,
        STRICT_UTC_START,
        ResearchError,
        ensure_distinct_paths,
        input_file_path,
        iso_utc,
        parse_utc,
        safe_output_path,
        snapshot_input_files,
    )
    from .research_contracts import (
        TARGET_REQUIRED,
        _asof_join,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        target_intervals_overlap,
        validate_catalog,
        validate_feature_manifest,
        validate_hypothesis,
    )
    from .research_registry import (
        _git_is_ancestor,
        _git_state,
        append_trial_registry,
        code_source_sha256,
    )
    from .research_statistics import (
        _decorate_feature_statistics,
        _ic,
        _placebo_inference,
    )
else:  # direct scripts import
    from research_common import (
        MAX_CONFIG_BYTES,
        RESEARCH_SCHEMA_VERSION,
        STRICT_UTC_START,
        ResearchError,
        ensure_distinct_paths,
        input_file_path,
        iso_utc,
        parse_utc,
        safe_output_path,
        snapshot_input_files,
    )
    from research_contracts import (
        TARGET_REQUIRED,
        _asof_join,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        target_intervals_overlap,
        validate_catalog,
        validate_feature_manifest,
        validate_hypothesis,
    )
    from research_registry import (
        _git_is_ancestor,
        _git_state,
        append_trial_registry,
        code_source_sha256,
    )
    from research_statistics import (
        _decorate_feature_statistics,
        _ic,
        _placebo_inference,
    )


def _run_point_in_time_research_impl(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path | None = None,
    trial_id: str | None = None,
) -> dict[str, Any]:
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    paths = {
        "feature_csv": input_file_path(feature_csv, "feature CSV"),
        "target_csv": input_file_path(target_csv, "target CSV"),
        "catalog_json": input_file_path(catalog_json, "series catalog", MAX_CONFIG_BYTES),
        "hypothesis_json": input_file_path(
            hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES
        ),
        "feature_manifest_json": input_file_path(
            feature_manifest_json, "feature manifest", MAX_CONFIG_BYTES
        ),
    }
    registry_path = safe_output_path(trial_registry, "trial registry")
    ensure_distinct_paths({**paths, "trial_registry": registry_path})
    snapshot_dir, snapshots, hashes = snapshot_input_files(paths)
    try:
        catalog = _load_json_object(snapshots["catalog_json"], "series catalog")
        hypothesis = _load_json_object(snapshots["hypothesis_json"], "hypothesis manifest")
        feature_manifest = _load_json_object(snapshots["feature_manifest_json"], "feature manifest")
        validate_catalog(catalog)
        validate_hypothesis(hypothesis)
        validate_feature_manifest(feature_manifest, hashes["feature_csv"])
        feature_names = [item["name"] for item in hypothesis["features"]]
        try:
            feature_times, feature_rows = _load_feature_rows(
                snapshots["feature_csv"], feature_names
            )
            target_column = catalog.get("target_column", "target")
            targets = _load_target_rows(snapshots["target_csv"], target_column)
        except (csv.Error, UnicodeError, OSError) as exc:
            raise ResearchError(f"无法安全解析 research CSV: {type(exc).__name__}: {exc}") from exc
    finally:
        snapshot_dir.cleanup()

    actual_overlap = target_intervals_overlap(targets)
    if actual_overlap and not catalog["overlapping_targets"]:
        raise ResearchError(
            "target intervals 实际重叠，但 series catalog 声明 overlapping_targets=false"
        )

    pre_utc_policy = hypothesis.get("pre_utc_policy", "reject")
    if pre_utc_policy not in ("reject", "proleptic_utc_label"):
        raise ResearchError("pre_utc_policy 必须是 reject 或 proleptic_utc_label")
    all_target_times = [row[field] for row in targets for field in TARGET_REQUIRED]
    uses_pre_utc = feature_times[0] < STRICT_UTC_START or any(
        timestamp < STRICT_UTC_START for timestamp in all_target_times
    )
    if uses_pre_utc and pre_utc_policy == "reject":
        raise ResearchError("研究包含 1972 年前时间；必须预注册 pre_utc_policy=proleptic_utc_label")
    if uses_pre_utc and feature_manifest["pre_utc_policy"] != "explicit-proleptic":
        raise ResearchError("1972 年前 feature manifest 未声明 explicit-proleptic")

    joined = _asof_join(
        feature_times,
        feature_rows,
        targets,
        feature_names,
        float(hypothesis["max_feature_staleness_hours"]),
    )
    train_end = parse_utc(hypothesis["train_end_utc"], allow_pre_utc=True)
    validation_end = parse_utc(hypothesis["validation_end_utc"], allow_pre_utc=True)
    splits = _split_rows(
        joined,
        train_end,
        validation_end,
        float(hypothesis["embargo_hours"]),
    )

    git_state = _git_state()
    registration_time = parse_utc(hypothesis["registered_at_utc"], allow_pre_utc=True)
    if hypothesis["mode"] == "prospective":
        registered_commit = hypothesis["registered_commit"]
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", registered_commit):
            raise ResearchError("prospective registered_commit 必须是完整 Git object ID")
        if registration_time > datetime.now(timezone.utc):
            raise ResearchError("prospective registered_at_utc 不能在未来")
        if any(
            row["observation_time_utc"] < registration_time
            or row["decision_at_utc"] < registration_time
            for row in splits["test"]
        ):
            raise ResearchError("prospective test observation/decision 必须发生在注册之后")
        if any(row["target_end_utc"] > datetime.now(timezone.utc) for row in splits["test"]):
            raise ResearchError("prospective test target 必须在评估前完整结束")
        if git_state["commit"] is None or git_state["dirty"] is not False:
            raise ResearchError("prospective 模式要求可验证且干净的 Git 工作树")
        if not _git_is_ancestor(registered_commit):
            raise ResearchError("registered_commit 不是当前 HEAD 的可验证 ancestor")

    registry_entry = {
        "trial_id": trial_id,
        "accessed_at_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis["hypothesis_id"],
        "mode": hypothesis["mode"],
        "input_sha256": hashes,
        "code": {**git_state, "source_sha256": code_source_sha256()},
    }

    statistics_by_feature: list[dict[str, Any]] = []
    for definition in hypothesis["features"]:
        name = definition["name"]
        statistics_by_feature.append(
            {
                "name": name,
                "direction": definition.get("direction", "two-sided"),
                "effective_period_days": definition.get("effective_period_days"),
                "train": _ic(splits["train"], name),
                "validation": _ic(splits["validation"], name),
                "test": _ic(splits["test"], name),
            }
        )

    # Time-shift placebo preserves the complete multivariate feature row and its
    # autocorrelation. maxT corrects selection across this preregistered family.
    effective_runs, p_individual, p_max, q_values = _placebo_inference(
        splits["test"],
        feature_names,
        statistics_by_feature,
        int(hypothesis["placebo_runs"]),
        int(hypothesis["seed"]),
    )
    _decorate_feature_statistics(
        statistics_by_feature,
        splits,
        hypothesis,
        catalog,
        effective_runs,
        p_individual,
        p_max,
        q_values,
    )

    if hypothesis["mode"] == "prospective":
        overall_status = "PROSPECTIVE_DECLARED_UNVERIFIED"
    elif hypothesis["mode"] == "pseudo_oos":
        overall_status = "PSEUDO_OOS_ONLY"
    else:
        overall_status = "EXPLORATORY"

    return {
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "evidence_status": overall_status,
        "claim_boundary": (
            "Univariate association MVP only; no causal or incremental-information claim, no proof of astrology, and no investment advice."
        ),
        "hypothesis": hypothesis,
        "series_catalog": catalog,
        "feature_manifest": feature_manifest,
        "provenance": {
            "input_paths": {name: str(path) for name, path in paths.items()},
            "input_sha256": hashes,
            "trial_registry": str(registry_path),
            "trial": registry_entry,
            "pre_utc_policy": pre_utc_policy,
        },
        "point_in_time_invariant": (
            "observation <= available <= decision < execution <= target_start < target_end"
        ),
        "alignment": {
            "method": "backward as-of only",
            "joined_rows": len(joined),
            "dropped_rows": len(targets) - len(joined),
            "max_feature_staleness_hours": hypothesis["max_feature_staleness_hours"],
            "actual_overlapping_targets": actual_overlap,
        },
        "splits": {name: len(rows) for name, rows in splits.items()},
        "features": statistics_by_feature,
        "limitations": [
            "Retrospective data already inspected cannot become a sealed OOS sample.",
            "Time-shift placebo is one null family, not a full phase-randomized pipeline universe.",
            "No strategy metric is emitted for indicators, non-return targets, or overlapping targets.",
            "Market data and target construction are BYOD and must be independently audited.",
            "This MVP tests marginal univariate association; financial controls and paired M0-vs-M2 incremental tests are not implemented.",
        ],
    }


def run_point_in_time_research(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one audited trial, recording STARTED plus COMPLETED or FAILED."""
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    protected = {
        "feature_csv": input_file_path(feature_csv, "feature CSV"),
        "target_csv": input_file_path(target_csv, "target CSV"),
        "catalog_json": input_file_path(catalog_json, "series catalog", MAX_CONFIG_BYTES),
        "hypothesis_json": input_file_path(
            hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES
        ),
        "feature_manifest_json": input_file_path(
            feature_manifest_json, "feature manifest", MAX_CONFIG_BYTES
        ),
    }
    registry_path = safe_output_path(trial_registry, "trial registry")
    ensure_distinct_paths({**protected, "trial_registry": registry_path})
    hypothesis_bytes = protected["hypothesis_json"].read_bytes()
    hypothesis_hash = hashlib.sha256(hypothesis_bytes).hexdigest()
    hypothesis_id = None
    try:
        parsed_hypothesis = json.loads(hypothesis_bytes)
        if isinstance(parsed_hypothesis, dict):
            hypothesis_id = parsed_hypothesis.get("hypothesis_id")
    except (UnicodeError, ValueError, json.JSONDecodeError):
        pass
    trial_id = uuid.uuid4().hex
    started = {
        "event": "STARTED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis_id,
        "provided_hypothesis_sha256": hypothesis_hash,
        "code_source_sha256": code_source_sha256(),
    }
    append_trial_registry(registry_path, started, protected_paths=protected.values())
    try:
        result = _run_point_in_time_research_impl(
            feature_csv,
            target_csv,
            catalog_json,
            hypothesis_json,
            registry_path,
            feature_manifest_json,
            trial_id,
        )
    except Exception as exc:
        failed = {
            "event": "FAILED",
            "trial_id": trial_id,
            "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
            "hypothesis_id": hypothesis_id,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        append_trial_registry(registry_path, failed, protected_paths=protected.values())
        raise
    completed = {
        "event": "COMPLETED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis_id,
        "evidence_status": result["evidence_status"],
        "input_sha256": result["provenance"]["input_sha256"],
    }
    append_trial_registry(registry_path, completed, protected_paths=protected.values())
    result["provenance"]["trial_events"] = ["STARTED", "COMPLETED"]
    return result
