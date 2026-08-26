from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
import research_statistics as rs
from research_common import ResearchError

SEED = 2026082603
UTC = timezone.utc


def _apply_group_shift(rows: list[tuple[float, ...]], shift: int) -> list[tuple[float, ...]]:
    return list(rows) if shift == 0 else rs.joint_circular_shift(rows, shift)


def test_complete_cyclic_group_and_joint_feature_rows_are_preserved() -> None:
    rng = random.Random(SEED)
    for _ in range(64):
        row_count = rng.randint(100, 180)
        rows = [
            (
                float(index),
                float((index * 17 + 3) % 101),
                math.sin(index / 7.0),
            )
            for index in range(row_count)
        ]
        first = rng.randrange(1, row_count)
        second = rng.randrange(1, row_count)
        inverse = (-first) % row_count
        composed = (first + second) % row_count

        shifted_once = rs.joint_circular_shift(rows, first)
        shifted_twice = rs.joint_circular_shift(shifted_once, second)
        assert shifted_twice == _apply_group_shift(rows, composed)
        assert _apply_group_shift(shifted_once, inverse) == rows

        # A joint shift must preserve full feature tuples and every pairwise
        # cross-feature relationship, not just each marginal column.
        assert sorted(shifted_once) == sorted(rows)
        for left, right in ((0, 1), (0, 2), (1, 2)):
            assert sorted((row[left], row[right]) for row in shifted_once) == sorted(
                (row[left], row[right]) for row in rows
            )

        exhaustive = rs.sample_circular_shifts(row_count, row_count - 1, rng.randrange(2**32))
        assert exhaustive["group_size"] == row_count
        assert exhaustive["evaluated_shifts"] == list(range(1, row_count))


def test_incremental_correlation_is_symmetric_scale_stable_and_bounded() -> None:
    rng = random.Random(SEED + 1)
    scales = (1e-300, 1e-150, 1e-20, 1.0, 1e20, 1e150, 1e300)
    for case in range(80):
        count = rng.randint(6, 40)
        left = [rng.uniform(-1.0, 1.0) + index * 1e-4 for index in range(count)]
        right = [
            0.35 * value + rng.uniform(-0.8, 0.8) + index * 2e-4 for index, value in enumerate(left)
        ]
        correlation = rs._overflow_stable_pearson(left, right)
        reverse = rs._overflow_stable_pearson(right, left)
        scale_left = scales[case % len(scales)]
        scale_right = scales[(case * 3 + 1) % len(scales)]
        scaled = rs._overflow_stable_pearson(
            [value * scale_left for value in left],
            [value * scale_right for value in right],
        )
        sign_flipped = rs._overflow_stable_pearson(
            [-value * scale_left for value in left],
            [value * scale_right for value in right],
        )

        assert math.isfinite(correlation)
        assert -1.0 <= correlation <= 1.0
        assert reverse == pytest.approx(correlation, abs=2e-14)
        assert scaled == pytest.approx(correlation, abs=2e-14)
        assert sign_flipped == pytest.approx(-correlation, abs=2e-14)

    extreme = [-1e308, -1e200, 0.0, 1e200, 1e308]
    assert rs._overflow_stable_pearson(extreme, extreme) == pytest.approx(1.0)
    assert rs._overflow_stable_pearson(extreme, list(reversed(extreme))) == pytest.approx(-1.0)


def test_frozen_standardizer_membership_and_transform_shapes_are_invariant() -> None:
    rng = random.Random(SEED + 2)
    for _ in range(64):
        row_count = rng.randint(8, 30)
        constant = rng.uniform(-100.0, 100.0)
        train = [
            [
                rng.uniform(-5.0, 5.0) + index,
                constant,
                rng.uniform(-3.0, 3.0) - 0.5 * index,
                float((index * 7) % 11),
            ]
            for index in range(row_count)
        ]
        names = ["trend", "train_constant", "noise", "cycle"]
        transform = rs.fit_frozen_standardizer(train, names)
        assert transform["retained_columns"] == ["trend", "noise", "cycle"]
        assert transform["dropped_constant_columns"] == ["train_constant"]

        standardized = rs.apply_frozen_standardizer(train, names, transform)
        assert standardized.shape == (row_count, 3)
        assert np.mean(standardized, axis=0) == pytest.approx([0.0, 0.0, 0.0], abs=1e-12)
        assert np.std(standardized, axis=0, ddof=0) == pytest.approx([1.0, 1.0, 1.0], abs=1e-12)

        validation = [
            [rng.uniform(-10.0, 10.0), (-1.0) ** index * 1e100, rng.random(), float(index)]
            for index in range(5)
        ]
        transformed_validation = rs.apply_frozen_standardizer(validation, names, transform)
        assert transformed_validation.shape == (5, 3)
        refit = rs.fit_frozen_standardizer(
            [*train, *validation],
            names,
            frozen_columns=transform["retained_columns"],
        )
        assert refit["retained_columns"] == transform["retained_columns"]
        assert refit["dropped_constant_columns"] == ["train_constant"]


def test_hac_and_circular_block_outputs_are_finite_bounded_and_deterministic() -> None:
    rng = random.Random(SEED + 3)
    for case in range(64):
        count = rng.randint(40, 80)
        series = [
            0.2 * math.sin(index / 5.0) + 0.1 * math.cos(index / 11.0) + rng.gauss(0.0, 0.7)
            for index in range(count)
        ]
        lag = rng.randint(0, min(6, count - 2))
        block_length = rng.randint(1, max(1, count // 4))
        seed = SEED + 100 + case

        hac = rs.newey_west_hac(series, lag)
        assert all(
            math.isfinite(value)
            for value in (
                hac["mean_loss_differential"],
                hac["omega_raw"],
                hac["omega"],
                hac["scale"],
                hac["tolerance"],
                hac["se"],
            )
        )
        assert hac["omega"] >= 0.0
        if hac["p_one_sided"] is not None:
            assert 0.0 <= hac["p_one_sided"] <= 1.0
            assert 0.0 <= hac["p_two_sided"] <= 1.0
            assert math.isfinite(hac["z"])

        first = rs.circular_block_bootstrap(
            series,
            runs=79,
            block_length=block_length,
            seed=seed,
            return_replicates=True,
        )
        second = rs.circular_block_bootstrap(
            series,
            runs=79,
            block_length=block_length,
            seed=seed,
            return_replicates=True,
        )
        assert first == second
        assert 1.0 / 80.0 <= first["p_one_sided"] <= 1.0
        assert 0.0 <= first["monte_carlo_se"] <= 0.5
        assert all(math.isfinite(value) for value in first["percentile_ci"])
        assert first["percentile_ci"][0] <= first["percentile_ci"][1]
        assert all(math.isfinite(value) for value in first["uncentered_means"])
        assert all(math.isfinite(value) for value in first["centered_means"])


def _preflight(
    *,
    p_declared: int,
    alpha_count: int,
    placebo_effective_runs: int,
) -> dict[str, object]:
    return rs.ridge_workload_preflight(
        complete_case_n=350,
        n_train=200,
        n_validation=100,
        n_test=40,
        p_declared=p_declared,
        alpha_count=alpha_count,
        overlap_lag=0,
        hac_lag=0,
        block_length=1,
        bootstrap_runs=999,
        placebo_effective_runs=placebo_effective_runs,
    )


def test_workload_preflight_is_monotone_and_enforces_the_cubic_cap() -> None:
    rng = random.Random(SEED + 4)
    for _ in range(64):
        columns = rng.randint(1, 9)
        alphas = rng.randint(1, 4)
        placebos = rng.randint(0, 8)
        baseline = _preflight(
            p_declared=columns,
            alpha_count=alphas,
            placebo_effective_runs=placebos,
        )
        more_columns = _preflight(
            p_declared=columns + 1,
            alpha_count=alphas,
            placebo_effective_runs=placebos,
        )
        more_alphas = _preflight(
            p_declared=columns,
            alpha_count=alphas + 1,
            placebo_effective_runs=placebos,
        )
        more_placebos = _preflight(
            p_declared=columns,
            alpha_count=alphas,
            placebo_effective_runs=placebos + 1,
        )
        assert more_columns["placebo_work_units"] > baseline["placebo_work_units"]
        assert more_alphas["placebo_work_units"] > baseline["placebo_work_units"]
        assert more_placebos["placebo_work_units"] > baseline["placebo_work_units"]

    with pytest.raises(ResearchError, match="placebo workload"):
        rs.ridge_workload_preflight(
            complete_case_n=393,
            n_train=202,
            n_validation=101,
            n_test=80,
            p_declared=100,
            alpha_count=16,
            overlap_lag=0,
            hac_lag=0,
            block_length=1,
            bootstrap_runs=999,
            placebo_effective_runs=2_000,
        )


def test_ordered_prediction_payload_hash_is_stable_and_rejects_shuffled_rows() -> None:
    rng = random.Random(SEED + 5)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for _ in range(64):
        count = rng.randint(2, 24)
        row_ids = [
            f"{index + 1}:{(start + timedelta(seconds=index)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}"
            for index in range(count)
        ]
        target = [rng.uniform(-10.0, 10.0) for _ in range(count)]
        prediction_m0 = [value + rng.uniform(-1.0, 1.0) for value in target]
        prediction_m2 = [value + rng.uniform(-1.0, 1.0) for value in target]

        first = rs.ordered_prediction_integrity(row_ids, target, prediction_m0, prediction_m2)
        second = rs.ordered_prediction_integrity(
            list(row_ids), list(target), list(prediction_m0), list(prediction_m2)
        )
        assert first["sha256"] == second["sha256"]
        assert first["canonical_json"] == second["canonical_json"]
        assert first["payload"] == second["payload"]

        changed_target = list(target)
        changed_target[-1] = math.nextafter(changed_target[-1], math.inf)
        changed = rs.ordered_prediction_integrity(
            row_ids, changed_target, prediction_m0, prediction_m2
        )
        assert changed["sha256"] != first["sha256"]

        with pytest.raises(ResearchError, match="chronological"):
            rs.ordered_prediction_integrity(
                list(reversed(row_ids)),
                list(reversed(target)),
                list(reversed(prediction_m0)),
                list(reversed(prediction_m2)),
            )
