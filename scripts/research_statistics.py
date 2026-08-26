"""Association statistics and transparent strategy diagnostics."""

from __future__ import annotations

import math
import random
import statistics
from typing import Any

if __package__:  # package import
    from .research_common import MAX_PLACEBO_OPERATIONS, ResearchError
else:  # direct scripts import
    from research_common import MAX_PLACEBO_OPERATIONS, ResearchError


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
