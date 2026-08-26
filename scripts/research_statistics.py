"""Association statistics and transparent strategy diagnostics."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import platform
import random
import re
import statistics
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

if __package__:  # package import
    from .research_common import MAX_PLACEBO_OPERATIONS, ResearchError
else:  # direct scripts import
    from research_common import MAX_PLACEBO_OPERATIONS, ResearchError


RIDGE_MIN_ALPHA = 1e-8
RIDGE_MAX_ALPHA = 1e12
RIDGE_MAX_CONDITION = 1e12
RIDGE_MAX_RELATIVE_RESIDUAL = 1e-10
MAX_INCREMENTAL_COLUMNS = 384
MAX_INCREMENTAL_CELLS = 5_000_000
MAX_ALPHA_CANDIDATES = 16
MAX_HAC_TERMS = 50_000_000
MAX_BOOTSTRAP_SAMPLED_VALUES = 25_000_000
MAX_FULL_PIPELINE_PLACEBO_RUNS = 2_000
MAX_RIDGE_PLACEBO_WORK = 1_000_000_000


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 3:
        raise ResearchError("相关系数至少需要 3 个成对样本")
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    numerator = math.fsum(a * b for a, b in zip(centered_x, centered_y, strict=True))
    denominator = math.sqrt(
        math.fsum(value * value for value in centered_x)
        * math.fsum(value * value for value in centered_y)
    )
    return numerator / denominator if denominator else 0.0


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2.0
        for index in order[start:end]:
            ranks[index] = average
        start = end
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(_rank(x), _rank(y))


def bh_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=p_values.__getitem__)
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[original_index] * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def _ic(rows: list[dict[str, Any]], feature: str) -> dict[str, float | int]:
    x = [row["features"][feature] for row in rows]
    y = [row["target"] for row in rows]
    return {"n": len(rows), "pearson": pearson(x, y), "spearman": spearman(x, y)}


def _placebo_inference(
    test: list[dict[str, Any]],
    feature_names: list[str],
    statistics_by_feature: list[dict[str, Any]],
    requested_runs: int,
    seed: int,
) -> tuple[int, list[float], list[float], list[float]]:
    """Run the preregistered finite circular-shift null family."""
    rng = random.Random(seed)
    target_values = [row["target"] for row in test]
    if len(test) < 3:
        raise ResearchError("test 样本太少，无法运行 placebo")

    def transform_statistic(correlation: float, direction: str) -> float:
        if direction == "positive":
            return correlation
        if direction == "negative":
            return -correlation
        return abs(correlation)

    observed_statistics = [
        transform_statistic(item["test"]["pearson"], item["direction"])
        for item in statistics_by_feature
    ]
    exceed_individual = [0] * len(feature_names)
    exceed_max = [0] * len(feature_names)
    effective_runs = min(requested_runs, len(test))
    if effective_runs * len(test) * len(feature_names) > MAX_PLACEBO_OPERATIONS:
        raise ResearchError(f"placebo workload 超过 {MAX_PLACEBO_OPERATIONS:,} operations 安全上限")
    shifts = (
        list(range(len(test)))
        if effective_runs == len(test)
        else [0, *rng.sample(range(1, len(test)), effective_runs - 1)]
    )
    original_features = {name: [row["features"][name] for row in test] for name in feature_names}
    for shift in shifts:
        null_values = []
        for feature_index, (name, item) in enumerate(
            zip(feature_names, statistics_by_feature, strict=True)
        ):
            original = original_features[name]
            shifted = original if shift == 0 else original[-shift:] + original[:-shift]
            statistic = transform_statistic(pearson(shifted, target_values), item["direction"])
            null_values.append(statistic)
            if statistic >= observed_statistics[feature_index]:
                exceed_individual[feature_index] += 1
        null_max = max(null_values)
        for feature_index, observed in enumerate(observed_statistics):
            if null_max >= observed:
                exceed_max[feature_index] += 1

    p_individual = [value / effective_runs for value in exceed_individual]
    p_max = [value / effective_runs for value in exceed_max]
    return effective_runs, p_individual, p_max, bh_adjust(p_individual)


def _decorate_feature_statistics(
    statistics_by_feature: list[dict[str, Any]],
    splits: dict[str, list[dict[str, Any]]],
    hypothesis: dict[str, Any],
    catalog: dict[str, Any],
    effective_runs: int,
    p_individual: list[float],
    p_max: list[float],
    q_values: list[float],
) -> None:
    """Attach placebo, identifiability, direction, and strategy diagnostics."""
    requested_runs = int(hypothesis["placebo_runs"])
    test = splits["test"]
    train_span_days = (
        splits["train"][-1]["decision_at_utc"] - splits["train"][0]["decision_at_utc"]
    ).total_seconds() / 86400
    test_span_days = (
        splits["test"][-1]["decision_at_utc"] - splits["test"][0]["decision_at_utc"]
    ).total_seconds() / 86400
    cost_bps = float(hypothesis.get("cost_bps", 0.0))
    for index, item in enumerate(statistics_by_feature):
        item["placebo"] = {
            "method": "joint circular time-shift of preregistered feature rows",
            "requested_runs": requested_runs,
            "effective_unique_shifts": effective_runs,
            "finite_group_size": len(test),
            "alternative": item["direction"],
            "empirical_p": p_individual[index],
            "familywise_maxT_p": p_max[index],
            "bh_q": q_values[index],
        }
        period = item["effective_period_days"]
        identifiable = False
        if period is not None:
            item["train_cycles"] = train_span_days / float(period)
            item["test_cycles"] = test_span_days / float(period)
            identifiable = item["train_cycles"] >= 3 and item["test_cycles"] >= 1
        signs = [
            math.copysign(1, item[split]["pearson"]) if item[split]["pearson"] != 0 else 0
            for split in ("train", "validation", "test")
        ]
        expected_sign = (
            1
            if item["direction"] == "positive"
            else -1
            if item["direction"] == "negative"
            else None
        )
        item["direction_matches_manifest"] = (
            signs[2] != 0 if expected_sign is None else signs[2] == expected_sign
        )
        item["direction_stable"] = (
            signs[0] != 0
            and signs[0] == signs[1] == signs[2]
            and item["direction_matches_manifest"]
        )
        item["evidence_status"] = "EXPLORATORY_TESTED" if identifiable else "DESCRIPTIVE"
        item["strategy"] = _strategy_metrics(
            splits["train"],
            splits["test"],
            item["name"],
            item["direction"],
            catalog,
            cost_bps,
        )


def _strategy_metrics(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    feature: str,
    direction: str,
    catalog: dict[str, Any],
    cost_bps: float,
) -> dict[str, Any] | None:
    if not catalog["tradable"] or catalog["overlapping_targets"]:
        return None
    if catalog["target_kind"] not in ("simple_return", "log_return"):
        return None
    target_values = [row["target"] for row in [*train, *test]]
    if catalog["target_kind"] == "simple_return" and any(
        value <= -1 or abs(value) > 100 for value in target_values
    ):
        return None
    if catalog["target_kind"] == "log_return" and any(abs(value) > 100 for value in target_values):
        return None
    train_x = [row["features"][feature] for row in train]
    if len(set(train_x)) < 2:
        return None
    threshold = statistics.median(train_x)
    train_ic = pearson(train_x, [row["target"] for row in train])
    sign = (
        1.0
        if direction == "positive"
        else -1.0
        if direction == "negative"
        else (1.0 if train_ic >= 0 else -1.0)
    )
    positions = [sign if row["features"][feature] > threshold else -sign for row in test]
    net_returns = []
    previous = 0.0
    cost_rate = cost_bps / 10_000.0
    for position, row in zip(positions, test, strict=True):
        one_way_notional = abs(position - previous)
        cost_fraction = one_way_notional * cost_rate
        if catalog["target_kind"] == "log_return":
            if cost_fraction >= 1:
                return None
            net_returns.append(position * row["target"] + math.log1p(-cost_fraction))
        else:
            net_returns.append(position * row["target"] - cost_fraction)
        previous = position
    mean_return = statistics.fmean(net_returns)
    stdev = statistics.stdev(net_returns) if len(net_returns) > 1 else 0.0
    periods = float(catalog["periods_per_year"])
    sharpe = mean_return / stdev * math.sqrt(periods) if stdev else 0.0
    if catalog["target_kind"] == "log_return":
        equity = [
            math.exp(math.fsum(net_returns[: index + 1])) for index in range(len(net_returns))
        ]
        baseline_equity = [
            math.exp(math.fsum(row["target"] for row in test[: index + 1]))
            for index in range(len(test))
        ]
    else:
        equity, baseline_equity = [], []
        current_strategy = current_baseline = 1.0
        for value, row in zip(net_returns, test, strict=True):
            if value <= -1 or row["target"] <= -1:
                return None
            current_strategy *= 1 + value
            current_baseline *= 1 + row["target"]
            equity.append(current_strategy)
            baseline_equity.append(current_baseline)

    def max_drawdown(curve: list[float]) -> float:
        peak, worst = curve[0], 0.0
        for value in curve:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        return worst

    baseline_returns = [row["target"] for row in test]
    baseline_std = statistics.stdev(baseline_returns) if len(baseline_returns) > 1 else 0.0
    baseline_sharpe = (
        statistics.fmean(baseline_returns) / baseline_std * math.sqrt(periods)
        if baseline_std
        else 0.0
    )
    return {
        "rule": "train-median threshold; direction fixed from manifest or learned once in train",
        "threshold_fit_on_train": threshold,
        "direction": sign,
        "cost_bps_per_one_way_notional": cost_bps,
        "oos_periods": len(test),
        "annualized_sharpe": sharpe,
        "baseline_definition": "always-long target return (not financial-control model M0)",
        "baseline_annualized_sharpe": baseline_sharpe,
        "delta_sharpe": sharpe - baseline_sharpe,
        "ending_equity": equity[-1],
        "baseline_ending_equity": baseline_equity[-1],
        "max_drawdown": max_drawdown(equity),
    }


# Incremental ridge/statistical kernel. NumPy stays lazy so the legacy
# univariate path above remains usable in a stdlib-only research install.


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise ResearchError(
            "incremental ridge research requires NumPy; install the research extra"
        ) from exc
    return np


def _numpy_runtime_metadata(np: Any) -> dict[str, Any]:
    """Return useful runtime identity without build paths or host-specific directories."""

    def safe_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or len(text) > 128 or "/" in text or "\\" in text:
            return None
        return text

    dependencies: dict[str, Any] = {}
    try:
        config = np.show_config(mode="dicts")
    except (AttributeError, TypeError, ValueError):
        config = {}
    if isinstance(config, dict):
        raw_dependencies = config.get("Build Dependencies", {})
        if isinstance(raw_dependencies, dict):
            for dependency_name in ("blas", "lapack"):
                raw = raw_dependencies.get(dependency_name)
                if not isinstance(raw, dict):
                    continue
                identity = {
                    "name": safe_text(raw.get("name")),
                    "version": safe_text(raw.get("version")),
                    "found": raw.get("found") if isinstance(raw.get("found"), bool) else None,
                }
                dependencies[dependency_name] = identity
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "numpy": str(np.__version__),
        "platform": {
            "system": safe_text(platform.system()),
            "machine": safe_text(platform.machine()),
        },
        "linear_algebra": dependencies,
    }


def _require_int(value: Any, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        raise ResearchError(f"{label} must be {bound}")
    return value


def _require_finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ResearchError(f"{label} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ResearchError(f"{label} must be a finite number")
    return number


def _validate_column_names(column_names: Sequence[str], expected: int) -> list[str]:
    names = list(column_names)
    if len(names) != expected or any(not isinstance(name, str) or not name for name in names):
        raise ResearchError("column_names must be non-empty strings matching matrix width")
    if len(set(names)) != len(names):
        raise ResearchError("column_names must be unique and ordered")
    return names


def _as_float_matrix(values: Any, label: str) -> Any:
    np = _require_numpy()
    try:
        matrix = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, MemoryError) as exc:
        raise ResearchError(f"{label} must be a rectangular float64 matrix") from exc
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise ResearchError(f"{label} must be a non-empty two-dimensional matrix")
    cells = int(matrix.shape[0]) * int(matrix.shape[1])
    if cells > MAX_INCREMENTAL_CELLS:
        raise ResearchError(f"{label} exceeds {MAX_INCREMENTAL_CELLS:,} float64 cell safety limit")
    if not bool(np.isfinite(matrix).all()):
        raise ResearchError(f"{label} contains a non-finite value")
    return matrix


def _as_float_vector(values: Any, label: str, *, expected: int | None = None) -> Any:
    np = _require_numpy()
    try:
        vector = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, MemoryError) as exc:
        raise ResearchError(f"{label} must be a finite float64 vector") from exc
    if vector.ndim != 1 or vector.shape[0] < 1:
        raise ResearchError(f"{label} must be a non-empty one-dimensional vector")
    if expected is not None and int(vector.shape[0]) != expected:
        raise ResearchError(f"{label} length does not match the model rows")
    if not bool(np.isfinite(vector).all()):
        raise ResearchError(f"{label} contains a non-finite value")
    return vector


def _validate_alpha_grid(alpha_grid: Sequence[float]) -> list[float]:
    alphas = [_require_finite(value, "ridge alpha") for value in alpha_grid]
    if not 1 <= len(alphas) <= MAX_ALPHA_CANDIDATES:
        raise ResearchError(f"alpha_grid must contain 1-{MAX_ALPHA_CANDIDATES} values")
    if any(alpha < RIDGE_MIN_ALPHA or alpha > RIDGE_MAX_ALPHA for alpha in alphas):
        raise ResearchError(f"ridge alpha must be in [{RIDGE_MIN_ALPHA:g}, {RIDGE_MAX_ALPHA:g}]")
    if any(right <= left for left, right in itertools.pairwise(alphas)):
        raise ResearchError("alpha_grid must be unique and strictly increasing")
    return alphas


def fit_frozen_standardizer(
    fit_matrix: Any,
    column_names: Sequence[str],
    *,
    frozen_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fit a population z-score transform and freeze ordered column membership."""
    np = _require_numpy()
    matrix = _as_float_matrix(fit_matrix, "standardizer fit matrix")
    names = _validate_column_names(column_names, int(matrix.shape[1]))
    index_by_name = {name: index for index, name in enumerate(names)}

    if frozen_columns is None:
        constant_mask = np.all(matrix == matrix[0, :], axis=0)
        retained = [
            name for name, is_constant in zip(names, constant_mask, strict=True) if not is_constant
        ]
    else:
        retained = list(frozen_columns)
        if not retained or len(set(retained)) != len(retained):
            raise ResearchError("frozen_columns must be non-empty and unique")
        if any(name not in index_by_name for name in retained):
            raise ResearchError("frozen_columns contains a column absent from the declared matrix")
        retained_set = set(retained)
        if retained != [name for name in names if name in retained_set]:
            raise ResearchError("frozen_columns must preserve declared column order")

    if not retained:
        raise ResearchError("no non-constant columns remain on the fit rows")
    retained_indices = [index_by_name[name] for name in retained]
    selected = matrix[:, retained_indices]
    with np.errstate(over="raise", invalid="raise"):
        try:
            means = np.mean(selected, axis=0, dtype=np.float64)
            scales = np.std(selected, axis=0, ddof=0, dtype=np.float64)
        except FloatingPointError as exc:
            raise ResearchError("standardizer statistics were non-finite") from exc
    if not bool(np.isfinite(means).all()) or not bool(np.isfinite(scales).all()):
        raise ResearchError("standardizer statistics were non-finite")
    if bool((scales == 0.0).any()):
        raise ResearchError(
            "a non-constant retained column has zero or unrepresentable population scale"
        )

    retained_set = set(retained)
    return {
        "fit_rows": int(matrix.shape[0]),
        "ddof": 0,
        "declared_columns": names,
        "retained_columns": retained,
        "dropped_constant_columns": [name for name in names if name not in retained_set],
        "means": [float(value) for value in means],
        "scales": [float(value) for value in scales],
    }


def apply_frozen_standardizer(
    matrix_values: Any,
    column_names: Sequence[str],
    transform: dict[str, Any],
) -> Any:
    """Apply a previously frozen transform without inspecting new rows."""
    np = _require_numpy()
    matrix = _as_float_matrix(matrix_values, "standardizer transform matrix")
    names = _validate_column_names(column_names, int(matrix.shape[1]))
    if transform.get("declared_columns") != names:
        raise ResearchError("transform declared columns do not match the transform matrix")
    retained = list(transform.get("retained_columns", []))
    means = _as_float_vector(transform.get("means", []), "standardizer means")
    scales = _as_float_vector(
        transform.get("scales", []), "standardizer scales", expected=len(retained)
    )
    if int(means.shape[0]) != len(retained):
        raise ResearchError("standardizer means do not match frozen columns")
    index_by_name = {name: index for index, name in enumerate(names)}
    if any(name not in index_by_name for name in retained):
        raise ResearchError("transform matrix is missing a frozen retained column")
    if bool((scales <= 0.0).any()):
        raise ResearchError("standardizer scales must be strictly positive")
    selected = matrix[:, [index_by_name[name] for name in retained]]
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        try:
            standardized = (selected - means) / scales
        except FloatingPointError as exc:
            raise ResearchError("standardized matrix was non-finite") from exc
    if not bool(np.isfinite(standardized).all()):
        raise ResearchError("standardized matrix was non-finite")
    return standardized


def ridge_fit_standardized(x_standardized: Any, target: Any, alpha: float) -> dict[str, Any]:
    """Fit the frozen ridge equation and enforce solve diagnostics."""
    np = _require_numpy()
    alpha_value = _validate_alpha_grid([alpha])[0]
    x = _as_float_matrix(x_standardized, "ridge design")
    y = _as_float_vector(target, "ridge target", expected=int(x.shape[0]))
    n_rows, n_columns = int(x.shape[0]), int(x.shape[1])
    target_mean = float(np.mean(y, dtype=np.float64))
    centered_y = y - target_mean
    try:
        with np.errstate(over="raise", invalid="raise"):
            system = x.T @ x + (n_rows * alpha_value) * np.eye(n_columns, dtype=np.float64)
            rhs = x.T @ centered_y
        if not bool(np.isfinite(system).all()) or not bool(np.isfinite(rhs).all()):
            raise ResearchError("ridge penalized system was non-finite")
        condition_number = float(np.linalg.cond(system, 2))
        coefficients = np.linalg.solve(system, rhs)
        numerator = float(np.linalg.norm(system @ coefficients - rhs, 2))
        denominator = max(float(np.linalg.norm(rhs, 2)), 1.0)
        relative_residual = numerator / denominator
    except np.linalg.LinAlgError as exc:
        raise ResearchError(f"ridge linear algebra failed: {exc}") from exc
    except FloatingPointError as exc:
        raise ResearchError("ridge linear algebra produced a non-finite value") from exc

    if not math.isfinite(condition_number) or condition_number > RIDGE_MAX_CONDITION:
        raise ResearchError(
            f"ridge condition number {condition_number!r} exceeds {RIDGE_MAX_CONDITION:g}"
        )
    if not bool(np.isfinite(coefficients).all()):
        raise ResearchError("ridge coefficients were non-finite")
    if not math.isfinite(relative_residual) or relative_residual > RIDGE_MAX_RELATIVE_RESIDUAL:
        raise ResearchError(
            f"ridge relative residual {relative_residual!r} exceeds {RIDGE_MAX_RELATIVE_RESIDUAL:g}"
        )
    return {
        "alpha": alpha_value,
        "fit_rows": n_rows,
        "columns": n_columns,
        "target_mean": target_mean,
        "coefficients_standardized": [float(value) for value in coefficients],
        "condition_number": condition_number,
        "relative_residual": relative_residual,
    }


def _ridge_predictions(x_standardized: Any, fit: dict[str, Any]) -> Any:
    np = _require_numpy()
    x = _as_float_matrix(x_standardized, "ridge prediction design")
    coefficients = _as_float_vector(
        fit["coefficients_standardized"],
        "ridge coefficients",
        expected=int(x.shape[1]),
    )
    predictions = float(fit["target_mean"]) + x @ coefficients
    if not bool(np.isfinite(predictions).all()):
        raise ResearchError("ridge predictions were non-finite")
    return predictions


def _mean_squared_error(actual: Any, predicted: Any, label: str) -> float:
    np = _require_numpy()
    y = _as_float_vector(actual, f"{label} target")
    yhat = _as_float_vector(predicted, f"{label} prediction", expected=int(y.shape[0]))
    with np.errstate(over="raise", invalid="raise"):
        try:
            mse = float(np.mean((y - yhat) ** 2, dtype=np.float64))
        except FloatingPointError as exc:
            raise ResearchError(f"{label} squared loss was non-finite") from exc
    if not math.isfinite(mse):
        raise ResearchError(f"{label} squared loss was non-finite")
    return mse


def fit_ridge_model(
    train_matrix: Any,
    validation_matrix: Any,
    test_matrix: Any,
    train_target: Any,
    validation_target: Any,
    column_names: Sequence[str],
    alpha_grid: Sequence[float],
    *,
    frozen_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Tune on train->validation, refit on train+validation, then predict test once."""
    np = _require_numpy()
    alphas = _validate_alpha_grid(alpha_grid)
    train_transform = fit_frozen_standardizer(
        train_matrix, column_names, frozen_columns=frozen_columns
    )
    names = list(train_transform["declared_columns"])
    train_x = apply_frozen_standardizer(train_matrix, names, train_transform)
    validation_x = apply_frozen_standardizer(validation_matrix, names, train_transform)
    train_y = _as_float_vector(train_target, "train target", expected=int(train_x.shape[0]))
    validation_y = _as_float_vector(
        validation_target, "validation target", expected=int(validation_x.shape[0])
    )

    validation_scores: list[dict[str, float]] = []
    for alpha in alphas:
        fit = ridge_fit_standardized(train_x, train_y, alpha)
        prediction = _ridge_predictions(validation_x, fit)
        validation_scores.append(
            {
                "alpha": alpha,
                "mse": _mean_squared_error(validation_y, prediction, "validation"),
                "condition_number": fit["condition_number"],
                "relative_residual": fit["relative_residual"],
            }
        )
    minimum_mse = min(item["mse"] for item in validation_scores)
    tie_tolerance = max(1e-15, abs(minimum_mse) * 1e-12)
    selected_alpha = max(
        item["alpha"] for item in validation_scores if item["mse"] <= minimum_mse + tie_tolerance
    )

    try:
        refit_matrix = np.concatenate(
            (
                _as_float_matrix(train_matrix, "train matrix"),
                _as_float_matrix(validation_matrix, "validation matrix"),
            ),
            axis=0,
        )
        refit_target = np.concatenate((train_y, validation_y), axis=0)
    except (ValueError, MemoryError) as exc:
        raise ResearchError("train and validation matrices cannot be concatenated") from exc
    if int(refit_matrix.shape[0]) * int(refit_matrix.shape[1]) > MAX_INCREMENTAL_CELLS:
        raise ResearchError("refit matrix exceeds float64 cell safety limit")
    refit_transform = fit_frozen_standardizer(
        refit_matrix,
        names,
        frozen_columns=train_transform["retained_columns"],
    )
    refit_x = apply_frozen_standardizer(refit_matrix, names, refit_transform)
    refit_fit = ridge_fit_standardized(refit_x, refit_target, selected_alpha)

    # Test is intentionally not converted or inspected until selection and refit are frozen.
    test_x = apply_frozen_standardizer(test_matrix, names, refit_transform)
    test_predictions = _ridge_predictions(test_x, refit_fit)
    standardized = list(refit_fit["coefficients_standardized"])
    raw_coefficients = [
        coefficient / scale
        for coefficient, scale in zip(standardized, refit_transform["scales"], strict=True)
    ]
    raw_intercept = float(refit_fit["target_mean"]) - math.fsum(
        mean * coefficient
        for mean, coefficient in zip(refit_transform["means"], raw_coefficients, strict=True)
    )
    if not math.isfinite(raw_intercept) or any(
        not math.isfinite(value) for value in raw_coefficients
    ):
        raise ResearchError("raw ridge coefficients were non-finite")
    retained = list(refit_transform["retained_columns"])
    return {
        "columns": {
            "declared": names,
            "retained": retained,
            "dropped_constant": list(train_transform["dropped_constant_columns"]),
        },
        "selection": {
            "fit_rows": int(train_x.shape[0]),
            "fit_transform": train_transform,
            "alpha_grid": alphas,
            "validation_scores": validation_scores,
            "minimum_validation_mse": minimum_mse,
            "tie_tolerance": tie_tolerance,
            "selected_alpha": selected_alpha,
            "tie_break": "largest_alpha_within_frozen_tolerance",
        },
        "refit": {
            "fit_rows": int(refit_x.shape[0]),
            "fit_transform": refit_transform,
            "alpha": selected_alpha,
            "condition_number": refit_fit["condition_number"],
            "relative_residual": refit_fit["relative_residual"],
            "target_mean": refit_fit["target_mean"],
            "coefficients_standardized": dict(zip(retained, standardized, strict=True)),
            "coefficients_raw": dict(zip(retained, raw_coefficients, strict=True)),
            "intercept_raw": raw_intercept,
        },
        "test_predictions": [float(value) for value in test_predictions],
        "runtime": _numpy_runtime_metadata(np),
    }


def _combine_columns(left: Any, right: Any, label: str) -> list[list[float]]:
    try:
        left_rows = list(left)
        right_rows = list(right)
    except TypeError as exc:
        raise ResearchError(f"{label} matrices must be iterable") from exc
    if len(left_rows) != len(right_rows) or not left_rows:
        raise ResearchError(f"{label} control and astronomy rows must match")
    combined: list[list[float]] = []
    for control_row, astronomy_row in zip(left_rows, right_rows, strict=True):
        try:
            combined.append([*control_row, *astronomy_row])
        except TypeError as exc:
            raise ResearchError(f"{label} matrix rows must be iterable") from exc
    return combined


def fit_paired_ridge_models(
    train_controls: Any,
    validation_controls: Any,
    test_controls: Any,
    train_astronomy: Any,
    validation_astronomy: Any,
    test_astronomy: Any,
    train_target: Any,
    validation_target: Any,
    control_names: Sequence[str],
    astronomy_names: Sequence[str],
    alpha_grid: Sequence[float],
) -> dict[str, Any]:
    """Fit paired M0/M2 models with identical rows and a frozen M0 control set."""
    controls = list(control_names)
    astronomy = list(astronomy_names)
    p_declared = len(controls) + len(astronomy)
    if not controls or not astronomy:
        raise ResearchError("paired ridge requires at least one control and astronomy column")
    if len(set(controls)) != len(controls) or len(set(astronomy)) != len(astronomy):
        raise ResearchError("paired ridge column names must be unique within each group")
    if set(controls) & set(astronomy):
        raise ResearchError("control and astronomy column names must be disjoint")
    if p_declared > MAX_INCREMENTAL_COLUMNS:
        raise ResearchError(f"declared M2 columns exceed {MAX_INCREMENTAL_COLUMNS} safety limit")
    split_rows = [len(train_controls), len(validation_controls), len(test_controls)]
    astronomy_split_rows = [
        len(train_astronomy),
        len(validation_astronomy),
        len(test_astronomy),
    ]
    if split_rows != astronomy_split_rows or any(count < 1 for count in split_rows):
        raise ResearchError("M0 and M2 must receive identical non-empty split row counts")
    if sum(split_rows) * p_declared > MAX_INCREMENTAL_CELLS:
        raise ResearchError(
            f"paired ridge exceeds {MAX_INCREMENTAL_CELLS:,} model-cell safety limit"
        )

    observed_controls = fit_frozen_standardizer(train_controls, controls)
    observed_astronomy = fit_frozen_standardizer(train_astronomy, astronomy)
    retained_controls = list(observed_controls["retained_columns"])
    retained_astronomy = list(observed_astronomy["retained_columns"])
    combined_names = [*controls, *astronomy]
    frozen_m2 = [*retained_controls, *retained_astronomy]

    m0 = fit_ridge_model(
        train_controls,
        validation_controls,
        test_controls,
        train_target,
        validation_target,
        controls,
        alpha_grid,
        frozen_columns=retained_controls,
    )
    m2 = fit_ridge_model(
        _combine_columns(train_controls, train_astronomy, "train"),
        _combine_columns(validation_controls, validation_astronomy, "validation"),
        _combine_columns(test_controls, test_astronomy, "test"),
        train_target,
        validation_target,
        combined_names,
        alpha_grid,
        frozen_columns=frozen_m2,
    )
    if m2["columns"]["retained"][: len(retained_controls)] != retained_controls:
        raise ResearchError("M0 and M2 control membership diverged")
    return {
        "p_declared": p_declared,
        "sample_counts": dict(zip(("train", "validation", "test"), split_rows, strict=True)),
        "columns": {
            "control_declared": controls,
            "control_retained": retained_controls,
            "control_dropped_constant": observed_controls["dropped_constant_columns"],
            "astronomy_declared": astronomy,
            "astronomy_retained": retained_astronomy,
            "astronomy_dropped_constant": observed_astronomy["dropped_constant_columns"],
            "m0": retained_controls,
            "m2": frozen_m2,
        },
        "selection": {"m0": m0["selection"], "m2": m2["selection"]},
        "refit": {"m0": m0["refit"], "m2": m2["refit"]},
        "test_predictions": {
            "m0": m0["test_predictions"],
            "m2": m2["test_predictions"],
        },
        "runtime": m2["runtime"],
    }


def _overflow_stable_pearson(left: Sequence[float], right: Sequence[float]) -> float:
    """Scale before centering so incremental IC cannot overflow on finite inputs."""
    if len(left) != len(right) or len(left) < 3:
        raise ResearchError("incremental correlation requires at least 3 paired values")

    def centered(values: Sequence[float]) -> list[float]:
        scale = max(abs(value) for value in values)
        if scale == 0.0:
            return [0.0] * len(values)
        scaled = [value / scale for value in values]
        mean_scaled = statistics.fmean(scaled)
        return [value - mean_scaled for value in scaled]

    centered_left = centered(left)
    centered_right = centered(right)
    numerator = math.fsum(
        first * second for first, second in zip(centered_left, centered_right, strict=True)
    )
    left_norm = math.fsum(value * value for value in centered_left)
    right_norm = math.fsum(value * value for value in centered_right)
    denominator = math.sqrt(left_norm * right_norm)
    if denominator == 0.0:
        raise ResearchError("incremental correlation variance is zero")
    correlation = numerator / denominator
    if not math.isfinite(correlation):
        raise ResearchError("incremental correlation was non-finite")
    return max(-1.0, min(1.0, correlation))


def _safe_prediction_ic(
    predictions: list[float], target: list[float], method: str
) -> tuple[float | None, str | None]:
    if len(predictions) < 3:
        return None, "insufficient_samples"
    if len(set(target)) < 2:
        return None, "zero_target_variance"
    if len(set(predictions)) < 2:
        return None, "zero_prediction_variance"
    if method == "pearson":
        value = _overflow_stable_pearson(predictions, target)
    else:
        value = _overflow_stable_pearson(_rank(predictions), _rank(target))
    return value, None


def _scaled_differences(left: Sequence[float], right: Sequence[float]) -> tuple[float, list[float]]:
    raw = [first - second for first, second in zip(left, right, strict=True)]
    if all(math.isfinite(value) for value in raw):
        scale = max((abs(value) for value in raw), default=0.0)
        return (scale, [value / scale for value in raw]) if scale else (0.0, raw)
    scale = max(
        max((abs(value) for value in left), default=0.0),
        max((abs(value) for value in right), default=0.0),
    )
    if scale == 0.0:
        return 0.0, [0.0] * len(left)
    normalized = [first / scale - second / scale for first, second in zip(left, right, strict=True)]
    if any(not math.isfinite(value) for value in normalized):
        raise ResearchError("scaled residual calculation was non-finite")
    return scale, normalized


def _stable_r2_oos(
    target: list[float], prediction: list[float], refit_target_mean: float
) -> tuple[float | None, str | None]:
    numerator_scale, numerator_values = _scaled_differences(target, prediction)
    denominator_scale, denominator_values = _scaled_differences(
        target, [refit_target_mean] * len(target)
    )
    numerator_sum = math.fsum(value * value for value in numerator_values)
    denominator_sum = math.fsum(value * value for value in denominator_values)
    if denominator_scale == 0.0 or denominator_sum == 0.0:
        return None, "zero_refit_mean_denominator"
    if numerator_scale == 0.0 or numerator_sum == 0.0:
        return 1.0, None
    log_ratio = (
        2.0 * (math.log(numerator_scale) - math.log(denominator_scale))
        + math.log(numerator_sum)
        - math.log(denominator_sum)
    )
    if not math.isfinite(log_ratio) or log_ratio > math.log(sys.float_info.max):
        return None, "r2_ratio_unrepresentable"
    ratio = math.exp(log_ratio)
    r2 = 1.0 - ratio
    if not math.isfinite(ratio) or not math.isfinite(r2):
        return None, "r2_ratio_unrepresentable"
    return r2, None


def paired_loss_metrics(
    target: Sequence[float],
    prediction_m0: Sequence[float],
    prediction_m2: Sequence[float],
    *,
    refit_target_mean: float,
) -> dict[str, Any]:
    """Compute the paired squared-loss statistic and frozen secondary metrics."""
    y = [_require_finite(value, "test target") for value in target]
    p0 = [_require_finite(value, "M0 prediction") for value in prediction_m0]
    p2 = [_require_finite(value, "M2 prediction") for value in prediction_m2]
    if not y or len(y) != len(p0) or len(y) != len(p2):
        raise ResearchError("target and paired predictions must have the same non-zero length")
    refit_mean = _require_finite(refit_target_mean, "refit target mean")
    try:
        loss_m0 = [(actual - predicted) ** 2 for actual, predicted in zip(y, p0, strict=True)]
        loss_m2 = [(actual - predicted) ** 2 for actual, predicted in zip(y, p2, strict=True)]
    except OverflowError as exc:
        raise ResearchError("paired squared loss overflowed float64") from exc
    if any(not math.isfinite(value) for value in [*loss_m0, *loss_m2]):
        raise ResearchError("paired squared loss was non-finite")
    differential = [left - right for left, right in zip(loss_m0, loss_m2, strict=True)]
    mean_d = statistics.fmean(differential)
    mse_m0, mse_m2 = statistics.fmean(loss_m0), statistics.fmean(loss_m2)
    mae_m0 = statistics.fmean(
        abs(actual - predicted) for actual, predicted in zip(y, p0, strict=True)
    )
    mae_m2 = statistics.fmean(
        abs(actual - predicted) for actual, predicted in zip(y, p2, strict=True)
    )
    secondary: dict[str, Any] = {
        "m0_mse": mse_m0,
        "m2_mse": mse_m2,
        "m0_rmse": math.sqrt(mse_m0),
        "m2_rmse": math.sqrt(mse_m2),
        "m0_mae": mae_m0,
        "m2_mae": mae_m2,
    }
    null_reasons: dict[str, str] = {}
    for method in ("pearson", "spearman"):
        value_m0, reason_m0 = _safe_prediction_ic(p0, y, method)
        value_m2, reason_m2 = _safe_prediction_ic(p2, y, method)
        key_m0 = f"m0_{method}_prediction_ic"
        key_m2 = f"m2_{method}_prediction_ic"
        delta_key = f"delta_{method}_prediction_ic"
        secondary[key_m0] = value_m0
        secondary[key_m2] = value_m2
        if reason_m0:
            null_reasons[key_m0] = reason_m0
        if reason_m2:
            null_reasons[key_m2] = reason_m2
        if value_m0 is None or value_m2 is None:
            secondary[delta_key] = None
            null_reasons[delta_key] = "component_prediction_ic_null"
        else:
            secondary[delta_key] = value_m2 - value_m0

    r2_m0, reason_r2_m0 = _stable_r2_oos(y, p0, refit_mean)
    r2_m2, reason_r2_m2 = _stable_r2_oos(y, p2, refit_mean)
    secondary["m0_r2_oos"] = r2_m0
    secondary["m2_r2_oos"] = r2_m2
    if reason_r2_m0:
        null_reasons["m0_r2_oos"] = reason_r2_m0
    if reason_r2_m2:
        null_reasons["m2_r2_oos"] = reason_r2_m2
    if r2_m0 is None or r2_m2 is None:
        secondary["delta_r2_oos"] = None
        null_reasons["delta_r2_oos"] = "component_r2_oos_null"
    else:
        delta_r2 = r2_m2 - r2_m0
        if math.isfinite(delta_r2):
            secondary["delta_r2_oos"] = delta_r2
        else:
            secondary["delta_r2_oos"] = None
            null_reasons["delta_r2_oos"] = "r2_delta_unrepresentable"
    secondary["null_reasons"] = null_reasons
    return {
        "primary": {
            "loss": "squared_error",
            "alternative": "greater",
            "positive_favors": "m2",
            "mean_loss_differential": mean_d,
        },
        "secondary": secondary,
        "loss_m0": loss_m0,
        "loss_m2": loss_m2,
        "loss_differential": differential,
    }


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
        raise ResearchError(f"canonical JSON serialization failed: {exc}") from exc


_CANONICAL_ROW_ID = re.compile(
    r"^(?P<ordinal>[1-9][0-9]*):"
    r"(?P<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z)$"
)


def _parse_canonical_row_id(row_id: str) -> tuple[int, datetime]:
    match = _CANONICAL_ROW_ID.fullmatch(row_id)
    if match is None:
        raise ResearchError("prediction row ID is not in canonical ordinal:UTC format")
    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ResearchError("prediction row ID contains an invalid UTC timestamp") from exc
    return int(match.group("ordinal")), timestamp


def ordered_prediction_integrity(
    row_ids: Sequence[str],
    target: Sequence[float],
    prediction_m0: Sequence[float],
    prediction_m2: Sequence[float],
) -> dict[str, Any]:
    """Build and hash the exact ordered section-15 prediction payload."""
    ids = list(row_ids)
    y = [_require_finite(value, "prediction payload target") for value in target]
    p0 = [_require_finite(value, "prediction payload M0") for value in prediction_m0]
    p2 = [_require_finite(value, "prediction payload M2") for value in prediction_m2]
    if not ids or len(ids) != len(y) or len(ids) != len(p0) or len(ids) != len(p2):
        raise ResearchError("ordered prediction payload vectors must have equal non-zero length")
    if any(not isinstance(row_id, str) or not row_id for row_id in ids):
        raise ResearchError("prediction row IDs must be non-empty strings")
    if len(set(ids)) != len(ids):
        raise ResearchError("prediction row IDs must be unique")
    parsed_ids = [_parse_canonical_row_id(row_id) for row_id in ids]
    if any(
        right_ordinal <= left_ordinal or right_time <= left_time
        for (left_ordinal, left_time), (right_ordinal, right_time) in itertools.pairwise(parsed_ids)
    ):
        raise ResearchError("prediction row IDs must be in strict chronological target-row order")
    payload = [
        {
            "prediction_m0": float.hex(left),
            "prediction_m2": float.hex(right),
            "row_id": row_id,
            "target": float.hex(actual),
        }
        for row_id, actual, left, right in zip(ids, y, p0, p2, strict=True)
    ]
    canonical = _canonical_json(payload)
    return {
        "rows": len(payload),
        "payload": payload,
        "canonical_json": canonical,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def newey_west_hac(loss_differential: Sequence[float], hac_lag: int) -> dict[str, Any]:
    """Compute the frozen row-lag Bartlett Newey-West statistic."""
    values = [_require_finite(value, "loss differential") for value in loss_differential]
    if not values:
        raise ResearchError("HAC requires at least one loss differential")
    lag = _require_int(hac_lag, "hac_lag", maximum=1024)
    n = len(values)
    if lag > n - 2:
        raise ResearchError("hac_lag must be at most n-2")
    if n * (lag + 1) > MAX_HAC_TERMS:
        raise ResearchError(f"HAC workload exceeds {MAX_HAC_TERMS:,} term safety limit")
    mean_d = statistics.fmean(values)
    centered = [value - mean_d for value in values]
    try:
        autocovariances = [
            math.fsum(
                centered[index] * centered[index - current_lag] for index in range(current_lag, n)
            )
            / n
            for current_lag in range(lag + 1)
        ]
    except (OverflowError, ValueError) as exc:
        raise ResearchError("HAC autocovariance calculation was non-finite") from exc
    if any(not math.isfinite(value) for value in autocovariances):
        raise ResearchError("HAC autocovariance calculation was non-finite")
    weighted_terms = [
        (1.0 - current_lag / (lag + 1.0)) * autocovariances[current_lag]
        for current_lag in range(1, lag + 1)
    ]
    omega_raw = autocovariances[0] + 2.0 * math.fsum(weighted_terms)
    scale = max(
        autocovariances[0],
        2.0 * math.fsum(abs(value) for value in weighted_terms),
        sys.float_info.min,
    )
    tolerance = 1e-12 * scale
    if not math.isfinite(omega_raw) or not math.isfinite(scale):
        raise ResearchError("HAC long-run variance was non-finite")
    if omega_raw < -tolerance:
        raise ResearchError("HAC long-run variance is materially negative")
    clamped = omega_raw < 0.0
    omega = 0.0 if clamped else omega_raw
    if omega == 0.0:
        return {
            "n": n,
            "lag": lag,
            "mean_loss_differential": mean_d,
            "autocovariances": autocovariances,
            "omega_raw": omega_raw,
            "omega": 0.0,
            "scale": scale,
            "tolerance": tolerance,
            "negative_roundoff_clamped": clamped,
            "se": 0.0,
            "z": None,
            "p_one_sided": None,
            "p_two_sided": None,
            "reason": "zero_long_run_variance",
        }
    se = math.sqrt(omega / n)
    z = mean_d / se
    p_one_sided = 0.5 * math.erfc(z / math.sqrt(2.0))
    p_two_sided = math.erfc(abs(z) / math.sqrt(2.0))
    return {
        "n": n,
        "lag": lag,
        "mean_loss_differential": mean_d,
        "autocovariances": autocovariances,
        "omega_raw": omega_raw,
        "omega": omega,
        "scale": scale,
        "tolerance": tolerance,
        "negative_roundoff_clamped": clamped,
        "se": se,
        "z": z,
        "p_one_sided": p_one_sided,
        "p_two_sided": p_two_sided,
        "reason": None,
    }


def _linear_quantile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        raise ResearchError("quantile requires values")
    h = (len(sorted_values) - 1) * quantile
    lower = math.floor(h)
    upper = math.ceil(h)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = h - lower
    return float(sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction)


def circular_block_bootstrap(
    loss_differential: Sequence[float],
    *,
    runs: int,
    block_length: int,
    seed: int,
    confidence_level: float = 0.95,
    return_replicates: bool = False,
) -> dict[str, Any]:
    """Circular MBB with uncentered CI and a separately centered null."""
    values = [_require_finite(value, "bootstrap loss differential") for value in loss_differential]
    if not values:
        raise ResearchError("block bootstrap requires at least one value")
    run_count = _require_int(runs, "bootstrap runs", minimum=1, maximum=10_000)
    block = _require_int(block_length, "bootstrap block_length", minimum=1, maximum=1_024)
    seed_value = _require_int(seed, "bootstrap seed", maximum=2**63 - 1)
    if block > len(values):
        raise ResearchError("bootstrap block_length cannot exceed sample size")
    if confidence_level != 0.95:
        raise ResearchError("bootstrap confidence_level must equal 0.95")
    if run_count * len(values) > MAX_BOOTSTRAP_SAMPLED_VALUES:
        raise ResearchError(
            f"block bootstrap exceeds {MAX_BOOTSTRAP_SAMPLED_VALUES:,} sampled-value limit"
        )
    rng = random.Random(seed_value)
    n = len(values)
    observed_mean = statistics.fmean(values)
    centered = [value - observed_mean for value in values]
    draws_per_replicate = math.ceil(n / block)
    starts_by_replicate: list[list[int]] = []
    uncentered_means: list[float] = []
    centered_means: list[float] = []
    exceedances = 0
    for _ in range(run_count):
        starts = [rng.randrange(n) for _ in range(draws_per_replicate)]
        indices: list[int] = []
        for start in starts:
            indices.extend((start + offset) % n for offset in range(block))
        indices = indices[:n]
        uncentered_mean = math.fsum(values[index] for index in indices) / n
        centered_mean = math.fsum(centered[index] for index in indices) / n
        if not math.isfinite(uncentered_mean) or not math.isfinite(centered_mean):
            raise ResearchError("block bootstrap replicate was non-finite")
        uncentered_means.append(uncentered_mean)
        centered_means.append(centered_mean)
        if centered_mean >= observed_mean:
            exceedances += 1
        if return_replicates:
            starts_by_replicate.append(starts)
    ordered = sorted(uncentered_means)
    p_value = (1 + exceedances) / (run_count + 1)
    result: dict[str, Any] = {
        "method": "circular_block_v1",
        "runs": run_count,
        "block_length": block,
        "draws_per_replicate": draws_per_replicate,
        "confidence_level": 0.95,
        "percentile_ci": [
            _linear_quantile(ordered, 0.025),
            _linear_quantile(ordered, 0.975),
        ],
        "observed_mean": observed_mean,
        "centered_null_exceedances": exceedances,
        "p_one_sided": p_value,
        "monte_carlo_se": math.sqrt(p_value * (1.0 - p_value) / run_count),
        "captures_model_selection_uncertainty": False,
    }
    if return_replicates:
        result["starts"] = starts_by_replicate
        result["uncentered_means"] = uncentered_means
        result["centered_means"] = centered_means
    return result


def sample_circular_shifts(row_count: int, requested_runs: int, seed: int) -> dict[str, Any]:
    """Select the complete or sampled nonzero elements of the finite group C_N."""
    n = _require_int(row_count, "placebo row_count", minimum=100)
    requested = _require_int(
        requested_runs,
        "placebo requested_runs",
        minimum=1,
        maximum=MAX_FULL_PIPELINE_PLACEBO_RUNS,
    )
    seed_value = _require_int(seed, "placebo seed", maximum=2**63 - 1)
    candidate_count = n - 1
    if requested >= candidate_count:
        shifts = list(range(1, n))
    else:
        shifts = sorted(random.Random(seed_value).sample(range(1, n), requested))
    effective = len(shifts)
    return {
        "method": "joint_circular_shift_v1",
        "group_size": n,
        "candidate_nonzero_shifts": candidate_count,
        "requested_runs": requested,
        "effective_runs": effective,
        "p_value_resolution": 1.0 / (effective + 1),
        "evaluated_shifts": shifts,
    }


def joint_circular_shift(rows: Sequence[Any], shift: int) -> list[Any]:
    """Apply A_s[i] = A[(i-s) mod N] jointly to complete astronomy rows."""
    values = list(rows)
    if len(values) < 2:
        raise ResearchError("joint circular shift requires at least two rows")
    offset = _require_int(shift, "circular shift", minimum=1, maximum=len(values) - 1)
    return values[-offset:] + values[:-offset]


def placebo_randomization_summary(
    observed_statistic: float,
    evaluated_shifts: Sequence[int],
    shifted_statistics: Sequence[float],
    *,
    group_size: int,
    requested_runs: int,
) -> dict[str, Any]:
    """Account and hash an evaluated nonzero C_N model-level null."""
    observed = _require_finite(observed_statistic, "observed placebo statistic")
    n = _require_int(group_size, "placebo group_size", minimum=100)
    requested = _require_int(
        requested_runs,
        "placebo requested_runs",
        minimum=1,
        maximum=MAX_FULL_PIPELINE_PLACEBO_RUNS,
    )
    shifts = list(evaluated_shifts)
    statistics_values = [
        _require_finite(value, "shifted placebo statistic") for value in shifted_statistics
    ]
    if not shifts or len(shifts) != len(statistics_values):
        raise ResearchError("placebo shifts and statistics must have equal non-zero length")
    if shifts != sorted(shifts) or len(set(shifts)) != len(shifts):
        raise ResearchError("placebo shifts must be unique and evaluated in sorted order")
    if any(
        isinstance(shift, bool) or not isinstance(shift, int) or not 1 <= shift < n
        for shift in shifts
    ):
        raise ResearchError("placebo shifts must be nonzero members of C_N")
    expected_effective = min(requested, n - 1)
    if len(shifts) != expected_effective:
        raise ResearchError("placebo shift accounting forbids failed or omitted shifts")
    exceedances = sum(value >= observed for value in statistics_values)
    p_value = (1 + exceedances) / (len(shifts) + 1)
    payload = [
        {"shift": shift, "statistic": float.hex(value)}
        for shift, value in zip(shifts, statistics_values, strict=True)
    ]
    canonical = _canonical_json(payload)
    return {
        "method": "joint_circular_shift_v1",
        "group_size": n,
        "candidate_nonzero_shifts": n - 1,
        "requested_runs": requested,
        "effective_runs": len(shifts),
        "p_value_resolution": 1.0 / (len(shifts) + 1),
        "evaluated_shifts": shifts,
        "exceedances": exceedances,
        "p_one_sided": p_value,
        "statistics_summary": {
            "minimum": min(statistics_values),
            "maximum": max(statistics_values),
            "mean": statistics.fmean(statistics_values),
        },
        "statistics_payload_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def ridge_workload_preflight(
    *,
    complete_case_n: int,
    n_train: int,
    n_validation: int,
    n_test: int,
    p_declared: int,
    alpha_count: int,
    overlap_lag: int,
    hac_lag: int,
    block_length: int,
    bootstrap_runs: int,
    placebo_effective_runs: int,
) -> dict[str, Any]:
    """Fail with integer arithmetic before allocating a prohibited ridge workload."""
    p = _require_int(p_declared, "p_declared", minimum=1, maximum=MAX_INCREMENTAL_COLUMNS)
    alphas = _require_int(alpha_count, "alpha_count", minimum=1, maximum=MAX_ALPHA_CANDIDATES)
    lag = _require_int(hac_lag, "hac_lag", maximum=1024)
    block = _require_int(block_length, "block_length", minimum=1, maximum=1024)
    bootstrap = _require_int(bootstrap_runs, "bootstrap_runs", minimum=1, maximum=10_000)
    placebo = _require_int(
        placebo_effective_runs,
        "placebo_effective_runs",
        minimum=0,
        maximum=MAX_FULL_PIPELINE_PLACEBO_RUNS,
    )
    train = _require_int(n_train, "n_train", minimum=max(60, 2 * (p + 1)))
    validation = _require_int(n_validation, "n_validation", minimum=max(30, p + 1))
    test = _require_int(n_test, "n_test", minimum=max(40, lag + 2, 4 * block))
    overlap = _require_int(overlap_lag, "overlap_lag", maximum=max(test - 1, 0))
    if lag < overlap:
        raise ResearchError("hac_lag must be at least overlap_lag")
    if block < overlap + 1:
        raise ResearchError("block_length must be at least overlap_lag + 1")
    if block > test // 4:
        raise ResearchError("block_length must be at most floor(n_test/4)")

    split_rows = train + validation + test
    full_rows = _require_int(complete_case_n, "complete_case_n", minimum=100)
    if full_rows < split_rows:
        raise ResearchError("complete_case_n cannot be smaller than used split rows")
    model_cells = full_rows * p
    if model_cells > MAX_INCREMENTAL_CELLS:
        raise ResearchError(
            f"model matrix exceeds {MAX_INCREMENTAL_CELLS:,} float64 cell safety limit"
        )
    hac_terms = test * (lag + 1)
    if hac_terms > MAX_HAC_TERMS:
        raise ResearchError(f"HAC workload exceeds {MAX_HAC_TERMS:,} term safety limit")
    bootstrap_values = bootstrap * test
    if bootstrap_values > MAX_BOOTSTRAP_SAMPLED_VALUES:
        raise ResearchError(
            f"bootstrap workload exceeds {MAX_BOOTSTRAP_SAMPLED_VALUES:,} sampled-value limit"
        )
    n_refit = train + validation
    placebo_work = (placebo + 1) * (
        train * p**2 + alphas * (p**3 + validation * p) + n_refit * p**2 + p**3 + test * p
    )
    if placebo_work > MAX_RIDGE_PLACEBO_WORK:
        raise ResearchError(
            f"ridge placebo workload exceeds {MAX_RIDGE_PLACEBO_WORK:,} work-unit limit"
        )
    matrix_bytes = model_cells * 8
    gram_bytes = p * p * 8
    return {
        "p_declared": p,
        "complete_case_n": full_rows,
        "used_split_rows": split_rows,
        "embargo_excluded_rows": full_rows - split_rows,
        "overlap_lag": overlap,
        "total_model_rows": full_rows,
        "model_cells": model_cells,
        "model_matrix_float64_bytes": matrix_bytes,
        "largest_gram_float64_bytes": gram_bytes,
        "hac_terms": hac_terms,
        "bootstrap_sampled_values": bootstrap_values,
        "placebo_effective_runs": placebo,
        "placebo_work_units": placebo_work,
        "limits": {
            "columns": MAX_INCREMENTAL_COLUMNS,
            "model_cells": MAX_INCREMENTAL_CELLS,
            "alpha_candidates": MAX_ALPHA_CANDIDATES,
            "hac_terms": MAX_HAC_TERMS,
            "bootstrap_sampled_values": MAX_BOOTSTRAP_SAMPLED_VALUES,
            "placebo_runs": MAX_FULL_PIPELINE_PLACEBO_RUNS,
            "placebo_work_units": MAX_RIDGE_PLACEBO_WORK,
        },
    }


def robust_union_bonferroni(
    p_hac: float | None,
    p_block: float | None,
    p_placebo: float | None,
    *,
    family_size: int,
    family_index: int,
    alpha: float,
    mean_loss_differential: float,
) -> dict[str, Any]:
    """Intersection-union max-p followed by declared-family Bonferroni."""
    size = _require_int(family_size, "family_size", minimum=1, maximum=10_000)
    index = _require_int(family_index, "family_index", minimum=1, maximum=size)
    alpha_value = _require_finite(alpha, "family alpha")
    if not 0.0 < alpha_value <= 0.25:
        raise ResearchError("family alpha must be in (0, 0.25]")
    mean_d = _require_finite(mean_loss_differential, "mean loss differential")
    component_values: list[float] = []
    for label, value in (("p_hac", p_hac), ("p_block", p_block), ("p_placebo", p_placebo)):
        if value is None:
            continue
        parsed = _require_finite(value, label)
        if not 0.0 <= parsed <= 1.0:
            raise ResearchError(f"{label} must be in [0, 1]")
        component_values.append(parsed)
    any_null = any(value is None for value in (p_hac, p_block, p_placebo))
    robust_p = None if any_null else max(component_values)
    family_p = None if robust_p is None else min(1.0, size * robust_p)
    threshold_met = family_p is not None and mean_d > 0.0 and family_p <= alpha_value
    return {
        "component_nulls": {
            "hac": p_hac,
            "block": p_block,
            "shift": p_placebo,
        },
        "component_null_definitions": {
            "H_HAC": "E[d] <= 0 under the declared HAC normal approximation",
            "H_BLOCK": ("E[d] <= 0 under the declared circular-block resampling approximation"),
            "H_SHIFT": (
                "the zero astronomy alignment is exchangeable under the complete C_N shift group"
            ),
        },
        "robust_null_definition": "H_ROBUST = H_HAC ∪ H_BLOCK ∪ H_SHIFT",
        "robust_union_method": "max_component_p",
        "robust_p_interpretation": "conservative intersection-union max-p construction",
        "p_robust": robust_p,
        "multiple_testing_method": "bonferroni",
        "family_size": size,
        "family_index": index,
        "family_alpha": alpha_value,
        "p_family": family_p,
        "family_p_scope": (
            "conditional on truth and completeness of the preregistered declared family; "
            "the local runner cannot prove completeness"
        ),
        "family_index_uniqueness_locally_proven": False,
        "null_reason": "component_p_value_null" if any_null else None,
        "threshold_diagnostics": {
            "mean_loss_differential_positive": mean_d > 0.0,
            "family_p_at_or_below_alpha": (None if family_p is None else family_p <= alpha_value),
            "threshold_met": threshold_met,
            "changes_evidence_label": False,
        },
    }
