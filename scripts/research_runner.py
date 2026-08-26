"""Audited point-in-time research orchestration and trial lifecycle."""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import re
import statistics
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
        _asof_join_incremental,
        _load_control_rows,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        incremental_model_enabled,
        target_intervals_overlap,
        target_overlap_metadata,
        validate_catalog,
        validate_controls_catalog,
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
        circular_block_bootstrap,
        fit_frozen_standardizer,
        fit_paired_ridge_models,
        fit_ridge_model,
        joint_circular_shift,
        newey_west_hac,
        ordered_prediction_integrity,
        paired_loss_metrics,
        placebo_randomization_summary,
        ridge_workload_preflight,
        robust_union_bonferroni,
        sample_circular_shifts,
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
        _asof_join_incremental,
        _load_control_rows,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        incremental_model_enabled,
        target_intervals_overlap,
        target_overlap_metadata,
        validate_catalog,
        validate_controls_catalog,
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
        circular_block_bootstrap,
        fit_frozen_standardizer,
        fit_paired_ridge_models,
        fit_ridge_model,
        joint_circular_shift,
        newey_west_hac,
        ordered_prediction_integrity,
        paired_loss_metrics,
        placebo_randomization_summary,
        ridge_workload_preflight,
        robust_union_bonferroni,
        sample_circular_shifts,
    )


INCREMENTAL_RESEARCH_SCHEMA_VERSION = "2.0.0"
INCREMENTAL_ANALYSIS_MODE = "incremental_ridge_v1"
INCREMENTAL_CLAIM_BOUNDARY = (
    "Paired predictive-loss comparison conditional on the exact supplied controls, sample, "
    "ridge specification, and null procedures. It is not causality, proof of astrology, a "
    "complete financial-information control set, evidence of tradable profit, or investment advice."
)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"无法生成 canonical JSON: {exc}") from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _package_version() -> str:
    try:
        return importlib.metadata.version("destiny-agent-skill")
    except importlib.metadata.PackageNotFoundError:
        return "2.2.0"


def _incremental_option_pair(
    controls_csv: str | Path | None,
    controls_catalog_json: str | Path | None,
) -> bool:
    if (controls_csv is None) != (controls_catalog_json is None):
        raise ResearchError("controls_csv 与 controls_catalog_json 必须同时提供")
    return controls_csv is not None


def _manifest_requests_incremental(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and incremental_model_enabled(value)


def _incremental_paths(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    feature_manifest_json: str | Path,
    controls_csv: str | Path,
    controls_catalog_json: str | Path,
) -> dict[str, Path]:
    return {
        "feature_csv": input_file_path(feature_csv, "feature CSV"),
        "feature_manifest_json": input_file_path(
            feature_manifest_json, "feature manifest", MAX_CONFIG_BYTES
        ),
        "target_csv": input_file_path(target_csv, "target CSV"),
        "catalog_json": input_file_path(catalog_json, "series catalog", MAX_CONFIG_BYTES),
        "hypothesis_json": input_file_path(
            hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES
        ),
        "controls_csv": input_file_path(controls_csv, "controls CSV"),
        "controls_catalog_json": input_file_path(
            controls_catalog_json, "controls catalog", MAX_CONFIG_BYTES
        ),
    }


def _evidence_status(mode: str) -> tuple[str, str]:
    if mode == "prospective":
        return (
            "PROSPECTIVE_DECLARED_UNVERIFIED",
            "EVALUATED_PROSPECTIVE_DECLARED_UNVERIFIED",
        )
    if mode == "pseudo_oos":
        return "PSEUDO_OOS_ONLY", "EVALUATED_PSEUDO_OOS_ONLY"
    return "EXPLORATORY", "EVALUATED_EXPLORATORY"


def _matrix(rows: list[dict[str, Any]], field: str, names: list[str]) -> list[list[float]]:
    return [[row[field][name] for name in names] for row in rows]


def _targets(rows: list[dict[str, Any]]) -> list[float]:
    return [row["target"] for row in rows]


def _row_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["row_id"] for row in rows]


def _split_output(
    splits: dict[str, list[dict[str, Any]]],
    hypothesis: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "train_end_utc": hypothesis["train_end_utc"],
        "validation_end_utc": hypothesis["validation_end_utc"],
        "embargo_hours": hypothesis["embargo_hours"],
    }
    for name, rows in splits.items():
        ids = _row_ids(rows)
        result[name] = {
            "count": len(rows),
            "shared_row_ids_sha256": _canonical_sha256(ids),
            "m0_m2_identical_rows": True,
        }
    return result


def _incremental_feature_statistics(
    splits: dict[str, list[dict[str, Any]]],
    feature_names: list[str],
    hypothesis: dict[str, Any],
    catalog: dict[str, Any],
) -> list[dict[str, Any]]:
    results = []
    for definition in hypothesis["features"]:
        name = definition["name"]
        results.append(
            {
                "name": name,
                "direction": definition.get("direction", "two-sided"),
                "effective_period_days": definition.get("effective_period_days"),
                "train": _ic(splits["train"], name),
                "validation": _ic(splits["validation"], name),
                "test": _ic(splits["test"], name),
            }
        )
    effective_runs, p_individual, p_max, q_values = _placebo_inference(
        splits["test"],
        feature_names,
        results,
        int(hypothesis["placebo_runs"]),
        int(hypothesis["seed"]),
    )
    _decorate_feature_statistics(
        results,
        splits,
        hypothesis,
        catalog,
        effective_runs,
        p_individual,
        p_max,
        q_values,
    )
    return results


def _validate_incremental_time_policy(
    feature_times: list[datetime],
    targets: list[dict[str, Any]],
    control_rows: list[dict[str, Any]],
    feature_manifest: dict[str, Any],
    hypothesis: dict[str, Any],
) -> str:
    pre_utc_policy = hypothesis.get("pre_utc_policy", "reject")
    if pre_utc_policy not in ("reject", "proleptic_utc_label"):
        raise ResearchError("pre_utc_policy 必须是 reject 或 proleptic_utc_label")
    target_times = [row[field] for row in targets for field in TARGET_REQUIRED]
    control_times = [
        row[field] for row in control_rows for field in ("observation_time_utc", "available_at_utc")
    ]
    uses_pre_utc = feature_times[0] < STRICT_UTC_START or any(
        timestamp < STRICT_UTC_START for timestamp in [*target_times, *control_times]
    )
    if uses_pre_utc and pre_utc_policy == "reject":
        raise ResearchError("研究包含 1972 年前时间；必须预注册 pre_utc_policy=proleptic_utc_label")
    if (
        feature_times[0] < STRICT_UTC_START
        and feature_manifest["pre_utc_policy"] != "explicit-proleptic"
    ):
        raise ResearchError("1972 年前 feature manifest 未声明 explicit-proleptic")
    return pre_utc_policy


def _validate_incremental_prospective(
    hypothesis: dict[str, Any],
    splits: dict[str, list[dict[str, Any]]],
    git_state: dict[str, Any],
) -> None:
    if hypothesis["mode"] != "prospective":
        return
    registered_commit = hypothesis["registered_commit"]
    registration_time = parse_utc(hypothesis["registered_at_utc"], allow_pre_utc=True)
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", registered_commit):
        raise ResearchError("prospective registered_commit 必须是完整 Git object ID")
    now = datetime.now(timezone.utc)
    if registration_time > now:
        raise ResearchError("prospective registered_at_utc 不能在未来")
    if any(
        row["observation_time_utc"] < registration_time
        or row["decision_at_utc"] < registration_time
        for row in splits["test"]
    ):
        raise ResearchError("prospective test observation/decision 必须发生在注册之后")
    if any(row["target_end_utc"] > now for row in splits["test"]):
        raise ResearchError("prospective test target 必须在评估前完整结束")
    if git_state["commit"] is None or git_state["dirty"] is not False:
        raise ResearchError("prospective 模式要求可验证且干净的 Git 工作树")
    if not _git_is_ancestor(registered_commit):
        raise ResearchError("registered_commit 不是当前 HEAD 的可验证 ancestor")


def _load_incremental_snapshots(
    paths: dict[str, Path],
) -> tuple[dict[str, Any], dict[str, str]]:
    snapshot_dir, snapshots, hashes = snapshot_input_files(paths)
    try:
        catalog = _load_json_object(snapshots["catalog_json"], "series catalog")
        hypothesis = _load_json_object(snapshots["hypothesis_json"], "hypothesis manifest")
        feature_manifest = _load_json_object(snapshots["feature_manifest_json"], "feature manifest")
        controls_catalog = _load_json_object(snapshots["controls_catalog_json"], "controls catalog")
        validate_catalog(catalog)
        validate_hypothesis(hypothesis)
        if not incremental_model_enabled(hypothesis):
            raise ResearchError(
                "incremental_model 未启用时禁止提供 controls_csv/controls_catalog_json"
            )
        validate_feature_manifest(feature_manifest, hashes["feature_csv"])
        validate_controls_catalog(controls_catalog, hashes["controls_csv"])
        feature_names = [item["name"] for item in hypothesis["features"]]
        model_contract = hypothesis["incremental_model"]
        control_ids = list(model_contract["control_ids"])
        try:
            feature_times, feature_rows = _load_feature_rows(
                snapshots["feature_csv"], feature_names
            )
            targets = _load_target_rows(
                snapshots["target_csv"], catalog.get("target_column", "target")
            )
            control_rows = _load_control_rows(
                snapshots["controls_csv"], controls_catalog, control_ids
            )
        except (csv.Error, UnicodeError, OSError) as exc:
            raise ResearchError(
                f"无法安全解析 incremental research CSV: {type(exc).__name__}: {exc}"
            ) from exc
    finally:
        snapshot_dir.cleanup()
    return {
        "catalog": catalog,
        "hypothesis": hypothesis,
        "feature_manifest": feature_manifest,
        "controls_catalog": controls_catalog,
        "feature_names": feature_names,
        "control_ids": control_ids,
        "feature_times": feature_times,
        "feature_rows": feature_rows,
        "targets": targets,
        "control_rows": control_rows,
    }, hashes


def _incremental_fingerprint(hashes: dict[str, str], package_version: str, code_hash: str) -> str:
    return _canonical_sha256(
        {
            "research_schema_version": INCREMENTAL_RESEARCH_SCHEMA_VERSION,
            "package_version": package_version,
            "hypothesis_sha256": hashes["hypothesis_json"],
            "feature_csv_sha256": hashes["feature_csv"],
            "feature_manifest_sha256": hashes["feature_manifest_json"],
            "target_csv_sha256": hashes["target_csv"],
            "target_catalog_sha256": hashes["catalog_json"],
            "controls_csv_sha256": hashes["controls_csv"],
            "controls_catalog_sha256": hashes["controls_catalog_json"],
            "code_source_sha256": code_hash,
        }
    )


def _prepare_incremental_context(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path,
    controls_csv: str | Path,
    controls_catalog_json: str | Path,
) -> dict[str, Any]:
    paths = _incremental_paths(
        feature_csv,
        target_csv,
        catalog_json,
        hypothesis_json,
        feature_manifest_json,
        controls_csv,
        controls_catalog_json,
    )
    registry_path = safe_output_path(trial_registry, "trial registry")
    ensure_distinct_paths({**paths, "trial_registry": registry_path})
    loaded, hashes = _load_incremental_snapshots(paths)
    catalog = loaded["catalog"]
    hypothesis = loaded["hypothesis"]
    model_contract = hypothesis["incremental_model"]

    all_overlap = target_overlap_metadata(loaded["targets"])
    if all_overlap["actual_overlapping_targets"] and not catalog["overlapping_targets"]:
        raise ResearchError(
            "target intervals 实际重叠，但 series catalog 声明 overlapping_targets=false"
        )
    pre_utc_policy = _validate_incremental_time_policy(
        loaded["feature_times"],
        loaded["targets"],
        loaded["control_rows"],
        loaded["feature_manifest"],
        hypothesis,
    )
    complete_rows, controls_alignment = _asof_join_incremental(
        loaded["feature_times"],
        loaded["feature_rows"],
        loaded["targets"],
        loaded["feature_names"],
        float(hypothesis["max_feature_staleness_hours"]),
        loaded["control_rows"],
        loaded["controls_catalog"],
        loaded["control_ids"],
    )
    train_end = parse_utc(hypothesis["train_end_utc"], allow_pre_utc=True)
    validation_end = parse_utc(hypothesis["validation_end_utc"], allow_pre_utc=True)
    splits = _split_rows(
        complete_rows,
        train_end,
        validation_end,
        float(hypothesis["embargo_hours"]),
    )
    test_overlap = target_overlap_metadata(splits["test"])
    placebo_contract = model_contract["full_pipeline_placebo"]
    shift_plan = sample_circular_shifts(
        len(complete_rows), placebo_contract["runs"], placebo_contract["seed"]
    )
    workload = ridge_workload_preflight(
        complete_case_n=len(complete_rows),
        n_train=len(splits["train"]),
        n_validation=len(splits["validation"]),
        n_test=len(splits["test"]),
        p_declared=len(loaded["control_ids"]) + len(loaded["feature_names"]),
        alpha_count=len(model_contract["alpha_grid"]),
        overlap_lag=test_overlap["overlap_lag"],
        hac_lag=model_contract["hac_lag"],
        block_length=model_contract["bootstrap"]["block_length"],
        bootstrap_runs=model_contract["bootstrap"]["runs"],
        placebo_effective_runs=shift_plan["effective_runs"],
    )
    git_state = _git_state()
    _validate_incremental_prospective(hypothesis, splits, git_state)
    package_version = _package_version()
    code_hash = code_source_sha256()
    return {
        **loaded,
        "paths": paths,
        "registry_path": registry_path,
        "hashes": hashes,
        "complete_rows": complete_rows,
        "splits": splits,
        "controls_alignment": controls_alignment,
        "all_target_overlap": all_overlap,
        "test_overlap": test_overlap,
        "shift_plan": shift_plan,
        "workload": workload,
        "pre_utc_policy": pre_utc_policy,
        "git_state": git_state,
        "package_version": package_version,
        "code_hash": code_hash,
        "experiment_fingerprint": _incremental_fingerprint(hashes, package_version, code_hash),
    }


def _model_inputs(context: dict[str, Any]) -> dict[str, Any]:
    splits = context["splits"]
    control_ids = context["control_ids"]
    feature_names = context["feature_names"]
    return {
        "controls": {name: _matrix(rows, "controls", control_ids) for name, rows in splits.items()},
        "astronomy": {
            name: _matrix(rows, "features", feature_names) for name, rows in splits.items()
        },
        "targets": {name: _targets(rows) for name, rows in splits.items()},
        "row_ids": {name: _row_ids(rows) for name, rows in splits.items()},
    }


def _merge_columns(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    if len(left) != len(right):
        raise ResearchError("control 与 astronomy matrix 行数不一致")
    return [[*control, *astronomy] for control, astronomy in zip(left, right, strict=True)]


def _mean_loss_differential(
    target: list[float], prediction_m0: list[float], prediction_m2: list[float]
) -> float:
    if not target or len(target) != len(prediction_m0) or len(target) != len(prediction_m2):
        raise ResearchError("placebo target/M0/M2 prediction 行数不一致")
    try:
        values = [
            (actual - left) ** 2 - (actual - right) ** 2
            for actual, left, right in zip(target, prediction_m0, prediction_m2, strict=True)
        ]
        result = statistics.fmean(values)
    except (OverflowError, ValueError) as exc:
        raise ResearchError("placebo paired loss 非有限") from exc
    if not math.isfinite(result) or any(not math.isfinite(value) for value in values):
        raise ResearchError("placebo paired loss 非有限")
    return result


def _full_pipeline_placebo(
    context: dict[str, Any],
    inputs: dict[str, Any],
    observed_fit: dict[str, Any],
    observed_mean_d: float,
) -> dict[str, Any]:
    complete_rows = context["complete_rows"]
    feature_names = context["feature_names"]
    control_ids = context["control_ids"]
    model_contract = context["hypothesis"]["incremental_model"]
    all_astronomy = _matrix(complete_rows, "features", feature_names)
    index_by_id = {row["row_id"]: index for index, row in enumerate(complete_rows)}
    if len(index_by_id) != len(complete_rows):
        raise ResearchError("incremental complete-case row_id 必须唯一")
    split_indices = {
        name: [index_by_id[row_id] for row_id in inputs["row_ids"][name]]
        for name in ("train", "validation", "test")
    }
    retained_controls = list(observed_fit["columns"]["control_retained"])
    m0_predictions = list(observed_fit["test_predictions"]["m0"])
    m0_integrity = _canonical_sha256([float.hex(value) for value in m0_predictions])
    shifted_statistics: list[float] = []
    combined_names = [*control_ids, *feature_names]

    for shift in context["shift_plan"]["evaluated_shifts"]:
        shifted_all = joint_circular_shift(all_astronomy, shift)
        shifted = {
            name: [shifted_all[index] for index in indices]
            for name, indices in split_indices.items()
        }
        shifted_transform = fit_frozen_standardizer(shifted["train"], feature_names)
        retained_astronomy = list(shifted_transform["retained_columns"])
        fit = fit_ridge_model(
            _merge_columns(inputs["controls"]["train"], shifted["train"]),
            _merge_columns(inputs["controls"]["validation"], shifted["validation"]),
            _merge_columns(inputs["controls"]["test"], shifted["test"]),
            inputs["targets"]["train"],
            inputs["targets"]["validation"],
            combined_names,
            model_contract["alpha_grid"],
            frozen_columns=[*retained_controls, *retained_astronomy],
        )
        shifted_statistics.append(
            _mean_loss_differential(
                inputs["targets"]["test"], m0_predictions, fit["test_predictions"]
            )
        )

    if _canonical_sha256([float.hex(value) for value in m0_predictions]) != m0_integrity:
        raise AssertionError("cached M0 predictions changed during placebo evaluation")
    summary = placebo_randomization_summary(
        observed_mean_d,
        context["shift_plan"]["evaluated_shifts"],
        shifted_statistics,
        group_size=len(complete_rows),
        requested_runs=model_contract["full_pipeline_placebo"]["runs"],
    )
    return {
        **summary,
        "base_rows": "all_incremental_complete_case_rows_before_split_membership",
        "includes_embargo_excluded_rows": (
            len(complete_rows) > sum(len(rows) for rows in context["splits"].values())
        ),
        "joint_astronomy_shift": True,
        "controls_targets_timestamps_and_splits_unchanged": True,
        "shifted_train_constant_detection_rerun": True,
        "m0_cached": True,
        "m0_prediction_payload_sha256": m0_integrity,
    }


def _evaluate_incremental_model(context: dict[str, Any]) -> dict[str, Any]:
    inputs = _model_inputs(context)
    model_contract = context["hypothesis"]["incremental_model"]
    fit = fit_paired_ridge_models(
        inputs["controls"]["train"],
        inputs["controls"]["validation"],
        inputs["controls"]["test"],
        inputs["astronomy"]["train"],
        inputs["astronomy"]["validation"],
        inputs["astronomy"]["test"],
        inputs["targets"]["train"],
        inputs["targets"]["validation"],
        context["control_ids"],
        context["feature_names"],
        model_contract["alpha_grid"],
    )
    if fit["refit"]["m0"]["target_mean"] != fit["refit"]["m2"]["target_mean"]:
        raise AssertionError("M0/M2 refit target means diverged on shared rows")
    test_target = inputs["targets"]["test"]
    metrics = paired_loss_metrics(
        test_target,
        fit["test_predictions"]["m0"],
        fit["test_predictions"]["m2"],
        refit_target_mean=fit["refit"]["m0"]["target_mean"],
    )
    integrity = ordered_prediction_integrity(
        inputs["row_ids"]["test"],
        test_target,
        fit["test_predictions"]["m0"],
        fit["test_predictions"]["m2"],
    )
    hac = newey_west_hac(metrics["loss_differential"], model_contract["hac_lag"])
    bootstrap_contract = model_contract["bootstrap"]
    block = circular_block_bootstrap(
        metrics["loss_differential"],
        runs=bootstrap_contract["runs"],
        block_length=bootstrap_contract["block_length"],
        seed=bootstrap_contract["seed"],
        confidence_level=bootstrap_contract["confidence_level"],
    )
    placebo = _full_pipeline_placebo(
        context,
        inputs,
        fit,
        metrics["primary"]["mean_loss_differential"],
    )
    multiple_contract = model_contract["multiple_testing"]
    multiple = robust_union_bonferroni(
        hac["p_one_sided"],
        block["p_one_sided"],
        placebo["p_one_sided"],
        family_size=multiple_contract["family_size"],
        family_index=multiple_contract["family_index"],
        alpha=multiple_contract["alpha"],
        mean_loss_differential=metrics["primary"]["mean_loss_differential"],
    )
    primary = {
        **metrics["primary"],
        "prediction_payload_rows": integrity["rows"],
        "prediction_payload_sha256": integrity["sha256"],
        "prediction_hash_scope": "in_run_integrity_not_cross_platform_identity",
    }
    return {
        "fit": fit,
        "primary": primary,
        "secondary": metrics["secondary"],
        "hac": hac,
        "block_bootstrap": block,
        "full_pipeline_placebo": placebo,
        "multiple_testing": {
            key: value for key, value in multiple.items() if key != "threshold_diagnostics"
        },
        "threshold_diagnostics": multiple["threshold_diagnostics"],
    }


def _incremental_started_event(context: dict[str, Any], trial_id: str) -> dict[str, Any]:
    return {
        "event": "STARTED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": context["hypothesis"]["hypothesis_id"],
        "hypothesis_sha256": context["hashes"]["hypothesis_json"],
        "mode": context["hypothesis"]["mode"],
        "analysis_mode": INCREMENTAL_ANALYSIS_MODE,
        "input_sha256": context["hashes"],
        "code_source_sha256": context["code_hash"],
        "experiment_fingerprint": context["experiment_fingerprint"],
    }


def _build_incremental_result(
    context: dict[str, Any], trial: dict[str, Any], evaluation: dict[str, Any]
) -> dict[str, Any]:
    hypothesis = context["hypothesis"]
    model_contract = hypothesis["incremental_model"]
    fit = evaluation["fit"]
    overall_status, evaluation_status = _evidence_status(hypothesis["mode"])
    catalog_by_id = {item["control_id"]: item for item in context["controls_catalog"]["controls"]}
    included_families = [
        catalog_by_id[control_id]["control_family"] for control_id in context["control_ids"]
    ]
    sample_counts = {
        "complete_case_before_splits": len(context["complete_rows"]),
        **{name: len(rows) for name, rows in context["splits"].items()},
        "embargo_excluded": context["workload"]["embargo_excluded_rows"],
        "m0_m2_identical": True,
    }
    incremental = {
        "evaluation_status": evaluation_status,
        "contract": {
            **model_contract,
            "astronomy_features": context["feature_names"],
            "included_control_families": included_families,
            "baseline_adequacy_asserted": False,
            "workload_preflight": context["workload"],
        },
        "sample_counts": sample_counts,
        "overlap_lag": context["test_overlap"]["overlap_lag"],
        "columns": fit["columns"],
        "selection": fit["selection"],
        "refit": fit["refit"],
        "test": {
            "primary": evaluation["primary"],
            "secondary": evaluation["secondary"],
            "hac": evaluation["hac"],
            "block_bootstrap": evaluation["block_bootstrap"],
            "full_pipeline_placebo": evaluation["full_pipeline_placebo"],
            "multiple_testing": evaluation["multiple_testing"],
            "threshold_diagnostics": evaluation["threshold_diagnostics"],
        },
    }
    result = {
        "schema_version": INCREMENTAL_RESEARCH_SCHEMA_VERSION,
        "analysis_mode": INCREMENTAL_ANALYSIS_MODE,
        "evidence_status": overall_status,
        "claim_boundary": INCREMENTAL_CLAIM_BOUNDARY,
        "hypothesis": hypothesis,
        "series_catalog": context["catalog"],
        "controls_catalog": context["controls_catalog"],
        "feature_manifest": context["feature_manifest"],
        "provenance": {
            "input_paths": {name: str(path) for name, path in context["paths"].items()},
            "input_sha256": context["hashes"],
            "experiment_fingerprint": context["experiment_fingerprint"],
            "code": {
                **context["git_state"],
                "source_sha256": context["code_hash"],
                "package_version": context["package_version"],
            },
            "runtime": fit["runtime"],
            "trial_registry": str(context["registry_path"]),
            "trial": {key: value for key, value in trial.items() if key != "event"},
            "pre_utc_policy": context["pre_utc_policy"],
        },
        "point_in_time_invariant": (
            "observation <= available <= decision < execution <= target_start < target_end"
        ),
        "alignment": {
            "features": {
                "method": "backward as-of only",
                "input_rows": len(context["feature_rows"]),
                "max_feature_staleness_hours": hypothesis["max_feature_staleness_hours"],
            },
            "controls": context["controls_alignment"],
            "target_intervals": context["all_target_overlap"],
            "test_target_intervals": context["test_overlap"],
        },
        "splits": _split_output(context["splits"], hypothesis),
        "features": _incremental_feature_statistics(
            context["splits"],
            context["feature_names"],
            hypothesis,
            context["catalog"],
        ),
        "incremental_model": incremental,
        "limitations": [
            "The comparison is conditional on the supplied controls and does not establish that ordinary market information was comprehensively controlled.",
            "Retrospective data already inspected cannot become an independently sealed OOS sample.",
            "The joint circular-shift placebo is one declared null family, not every plausible periodic or data-mining null.",
            "Market data, target construction, releases, revisions, and calendars are BYOD and require independent audit.",
            "Prediction improvements do not establish causality, astrology, stable alpha, tradable profit, or investment suitability.",
        ],
    }
    _canonical_json(result)
    return result


def _execute_incremental_context(context: dict[str, Any], trial: dict[str, Any]) -> dict[str, Any]:
    evaluation = _evaluate_incremental_model(context)
    return _build_incremental_result(context, trial, evaluation)


def _run_incremental_trial(context: dict[str, Any]) -> dict[str, Any]:
    trial_id = uuid.uuid4().hex
    started = _incremental_started_event(context, trial_id)
    protected_paths = context["paths"].values()
    append_trial_registry(context["registry_path"], started, protected_paths=protected_paths)
    try:
        result = _execute_incremental_context(context, started)
    except Exception as exc:
        failed = {
            "event": "FAILED",
            "trial_id": trial_id,
            "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
            "hypothesis_id": context["hypothesis"]["hypothesis_id"],
            "analysis_mode": INCREMENTAL_ANALYSIS_MODE,
            "experiment_fingerprint": context["experiment_fingerprint"],
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        append_trial_registry(context["registry_path"], failed, protected_paths=protected_paths)
        raise
    result["provenance"]["trial_events"] = ["STARTED", "COMPLETED"]
    result_hash = _canonical_sha256(result)
    completed = {
        "event": "COMPLETED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": context["hypothesis"]["hypothesis_id"],
        "analysis_mode": INCREMENTAL_ANALYSIS_MODE,
        "evidence_status": result["evidence_status"],
        "input_sha256": context["hashes"],
        "experiment_fingerprint": context["experiment_fingerprint"],
        "result_payload_sha256": result_hash,
    }
    append_trial_registry(context["registry_path"], completed, protected_paths=protected_paths)
    return result


def _run_point_in_time_research_impl(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path | None = None,
    trial_id: str | None = None,
    controls_csv: str | Path | None = None,
    controls_catalog_json: str | Path | None = None,
) -> dict[str, Any]:
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    if _incremental_option_pair(controls_csv, controls_catalog_json):
        if controls_csv is None or controls_catalog_json is None:
            raise AssertionError("validated incremental paths are missing")
        context = _prepare_incremental_context(
            feature_csv,
            target_csv,
            catalog_json,
            hypothesis_json,
            trial_registry,
            feature_manifest_json,
            controls_csv,
            controls_catalog_json,
        )
        started = _incremental_started_event(context, trial_id or uuid.uuid4().hex)
        return _execute_incremental_context(context, started)
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
        if incremental_model_enabled(hypothesis):
            raise ResearchError(
                "incremental_model 启用时必须提供 controls_csv 与 controls_catalog_json"
            )
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
    controls_csv: str | Path | None = None,
    controls_catalog_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one audited trial, recording STARTED plus COMPLETED or FAILED."""
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    if _incremental_option_pair(controls_csv, controls_catalog_json):
        if controls_csv is None or controls_catalog_json is None:
            raise AssertionError("validated incremental paths are missing")
        context = _prepare_incremental_context(
            feature_csv,
            target_csv,
            catalog_json,
            hypothesis_json,
            trial_registry,
            feature_manifest_json,
            controls_csv,
            controls_catalog_json,
        )
        return _run_incremental_trial(context)
    hypothesis_path = input_file_path(hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES)
    if _manifest_requests_incremental(hypothesis_path):
        raise ResearchError(
            "incremental_model 启用时必须提供 controls_csv 与 controls_catalog_json"
        )
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
