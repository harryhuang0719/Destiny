from __future__ import annotations

import builtins
import hashlib
import json
import math

import numpy as np
import pytest
import research_statistics as rs
from research_common import ResearchError


def _factorial_rows(repeats: int = 1) -> list[tuple[float, float]]:
    base = [
        (-2.0, -1.0),
        (-2.0, 1.0),
        (-1.0, -1.0),
        (-1.0, 1.0),
        (1.0, -1.0),
        (1.0, 1.0),
        (2.0, -1.0),
        (2.0, 1.0),
    ]
    return base * repeats


def _controls(rows: list[tuple[float, float]]) -> list[list[float]]:
    return [[control] for control, _astronomy in rows]


def _astronomy(rows: list[tuple[float, float]]) -> list[list[float]]:
    return [[astronomy] for _control, astronomy in rows]


def _target(rows: list[tuple[float, float]], astronomy_coefficient: float) -> list[float]:
    return [2.0 * control + astronomy_coefficient * astronomy for control, astronomy in rows]


def test_numpy_import_failure_has_clear_research_error(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object):
        if name == "numpy":
            raise ModuleNotFoundError("synthetic missing numpy")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ResearchError, match="requires NumPy"):
        rs._require_numpy()


def test_one_column_ridge_matches_hand_solution_and_rejects_small_alpha() -> None:
    fit = rs.ridge_fit_standardized([[-1.0], [1.0]], [-1.0, 1.0], 1.0)

    assert fit["coefficients_standardized"] == pytest.approx([0.5])
    assert fit["target_mean"] == 0.0
    assert fit["condition_number"] == pytest.approx(1.0)
    assert fit["relative_residual"] == pytest.approx(0.0)
    assert rs._ridge_predictions([[-1.0], [1.0]], fit) == pytest.approx([-0.5, 0.5])
    with pytest.raises(ResearchError, match="ridge alpha"):
        rs.ridge_fit_standardized([[-1.0], [1.0]], [-1.0, 1.0], 0.0)
    with pytest.raises(ResearchError, match="ridge alpha"):
        rs.ridge_fit_standardized([[-1.0], [1.0]], [-1.0, 1.0], 1e-9)


def test_two_column_ridge_matches_direct_frozen_equation() -> None:
    x = np.asarray([[-1.0, 0.0], [0.0, -1.0], [1.0, 1.0]], dtype=np.float64)
    y = np.asarray([-1.0, -2.0, 3.0], dtype=np.float64)
    alpha = 0.25
    expected = np.linalg.solve(
        x.T @ x + len(x) * alpha * np.eye(2),
        x.T @ (y - y.mean()),
    )

    fit = rs.ridge_fit_standardized(x, y, alpha)

    assert fit["coefficients_standardized"] == pytest.approx(expected.tolist())


def test_alpha_tie_selects_largest_and_test_is_not_used_for_selection() -> None:
    train_x = [[-2.0], [-1.0], [1.0], [2.0]]
    validation_x = [[-3.0], [3.0]]
    train_y = [7.0] * 4
    validation_y = [7.0, 7.0]
    alphas = [1e-8, 0.1, 10.0]

    ordinary_test = rs.fit_ridge_model(
        train_x,
        validation_x,
        [[0.0], [1.0]],
        train_y,
        validation_y,
        ["x"],
        alphas,
    )
    extreme_test = rs.fit_ridge_model(
        train_x,
        validation_x,
        [[-1e100], [1e100]],
        train_y,
        validation_y,
        ["x"],
        alphas,
    )

    assert ordinary_test["selection"]["selected_alpha"] == 10.0
    assert extreme_test["selection"]["selected_alpha"] == 10.0
    assert ordinary_test["selection"] == extreme_test["selection"]


def test_train_constant_column_stays_dropped_during_refit_and_test() -> None:
    train = [[-2.0, 5.0], [-1.0, 5.0], [1.0, 5.0], [2.0, 5.0]]
    validation = [[-3.0, -999.0], [3.0, 999.0]]
    target_train = [-4.0, -2.0, 2.0, 4.0]
    target_validation = [-6.0, 6.0]

    first = rs.fit_ridge_model(
        train,
        validation,
        [[0.5, -1e50], [1.5, 1e50]],
        target_train,
        target_validation,
        ["signal", "train_constant"],
        [1e-8, 0.1],
    )
    second = rs.fit_ridge_model(
        train,
        validation,
        [[0.5, 123.0], [1.5, 456.0]],
        target_train,
        target_validation,
        ["signal", "train_constant"],
        [1e-8, 0.1],
    )

    assert first["columns"] == {
        "declared": ["signal", "train_constant"],
        "retained": ["signal"],
        "dropped_constant": ["train_constant"],
    }
    assert first["selection"]["fit_transform"]["means"] == pytest.approx([0.0])
    assert first["refit"]["fit_transform"]["retained_columns"] == ["signal"]
    assert "train_constant" not in first["refit"]["coefficients_raw"]
    assert first["test_predictions"] == pytest.approx(second["test_predictions"])


def test_exact_constant_detection_handles_repeated_noninteger_and_near_values() -> None:
    repeated = rs.fit_frozen_standardizer(
        [[0.1, 0.0], [0.1, 1.0], [0.1, 2.0]],
        ["repeated_decimal", "signal"],
    )
    adjacent = math.nextafter(0.1, math.inf)
    near = rs.fit_frozen_standardizer(
        [[0.1, 0.0], [adjacent, 1.0], [0.1, 2.0]],
        ["near_but_distinct", "signal"],
    )

    assert repeated["retained_columns"] == ["signal"]
    assert repeated["dropped_constant_columns"] == ["repeated_decimal"]
    assert near["retained_columns"] == ["near_but_distinct", "signal"]
    assert near["scales"][0] > 0.0


def test_paired_ridge_control_only_null_and_astronomy_signal() -> None:
    train = _factorial_rows(3)
    validation = _factorial_rows()
    test = _factorial_rows()
    alpha_grid = [1e-8, 0.01, 1.0]

    null_fit = rs.fit_paired_ridge_models(
        _controls(train),
        _controls(validation),
        _controls(test),
        _astronomy(train),
        _astronomy(validation),
        _astronomy(test),
        _target(train, 0.0),
        _target(validation, 0.0),
        ["control"],
        ["astro"],
        alpha_grid,
    )
    null_metrics = rs.paired_loss_metrics(
        _target(test, 0.0),
        null_fit["test_predictions"]["m0"],
        null_fit["test_predictions"]["m2"],
        refit_target_mean=0.0,
    )
    signal_fit = rs.fit_paired_ridge_models(
        _controls(train),
        _controls(validation),
        _controls(test),
        _astronomy(train),
        _astronomy(validation),
        _astronomy(test),
        _target(train, 3.0),
        _target(validation, 3.0),
        ["control"],
        ["astro"],
        alpha_grid,
    )
    signal_metrics = rs.paired_loss_metrics(
        _target(test, 3.0),
        signal_fit["test_predictions"]["m0"],
        signal_fit["test_predictions"]["m2"],
        refit_target_mean=0.0,
    )

    assert null_fit["columns"]["m0"] == ["control"]
    assert null_fit["columns"]["m2"] == ["control", "astro"]
    assert null_metrics["primary"]["mean_loss_differential"] == pytest.approx(0.0, abs=1e-20)
    assert signal_metrics["primary"]["mean_loss_differential"] == pytest.approx(9.0)
    assert signal_metrics["secondary"]["delta_r2_oos"] > 0
    runtime = signal_fit["runtime"]
    assert runtime["python"]
    assert runtime["python_implementation"]
    assert runtime["numpy"]
    assert set(runtime["platform"]) == {"system", "machine"}
    assert isinstance(runtime["linear_algebra"], dict)
    runtime_text = json.dumps(runtime, sort_keys=True)
    assert "/Users/" not in runtime_text and "/private/" not in runtime_text
    linear_algebra_text = json.dumps(runtime["linear_algebra"], sort_keys=True)
    assert "/" not in linear_algebra_text and "\\" not in linear_algebra_text


def test_paired_loss_translation_invariance_and_null_reasons() -> None:
    target = [1.0, 2.0, 1.0, 2.0]
    p0 = [0.0, 0.0, 0.0, 0.0]
    p2 = [0.0, 1.0, 0.0, 1.0]
    original = rs.paired_loss_metrics(target, p0, p2, refit_target_mean=1.5)
    translated = rs.paired_loss_metrics(
        [value + 100.0 for value in target],
        [value + 100.0 for value in p0],
        [value + 100.0 for value in p2],
        refit_target_mean=101.5,
    )

    assert original["loss_differential"] == [0.0, 3.0, 0.0, 3.0]
    assert original["primary"]["mean_loss_differential"] == 1.5
    assert translated["loss_differential"] == original["loss_differential"]
    assert original["secondary"]["m0_pearson_prediction_ic"] is None
    assert (
        original["secondary"]["null_reasons"]["m0_pearson_prediction_ic"]
        == "zero_prediction_variance"
    )


def test_incremental_prediction_ic_is_overflow_stable() -> None:
    result = rs.paired_loss_metrics(
        [-1e150, 0.0, 1e150],
        [-1e150, 0.0, 1e150],
        [1e150, 0.0, -1e150],
        refit_target_mean=0.0,
    )

    assert result["secondary"]["m0_pearson_prediction_ic"] == pytest.approx(1.0)
    assert result["secondary"]["m2_pearson_prediction_ic"] == pytest.approx(-1.0)
    assert result["secondary"]["m0_spearman_prediction_ic"] == pytest.approx(1.0)
    extreme = [-1e308, 0.0, 1e308]
    stable_value, reason = rs._safe_prediction_ic(extreme, extreme, "pearson")
    assert stable_value == pytest.approx(1.0)
    assert reason is None


def test_r2_unrepresentable_ratio_is_null_with_reason_not_infinity() -> None:
    result = rs.paired_loss_metrics(
        [-1e-300, 0.0, 1e-300],
        [1.0, 1.0, 1.0],
        [0.0, 0.0, 0.0],
        refit_target_mean=0.0,
    )

    secondary = result["secondary"]
    assert secondary["m0_r2_oos"] is None
    assert secondary["m2_r2_oos"] == pytest.approx(0.0)
    assert secondary["delta_r2_oos"] is None
    assert secondary["null_reasons"]["m0_r2_oos"] == "r2_ratio_unrepresentable"
    assert secondary["null_reasons"]["delta_r2_oos"] == "component_r2_oos_null"
    json.dumps(result, allow_nan=False)


def test_identical_predictions_have_zero_d_and_no_fabricated_hac_p() -> None:
    metrics = rs.paired_loss_metrics(
        [1.0, 2.0, 3.0, 4.0],
        [0.5, 1.5, 2.5, 3.5],
        [0.5, 1.5, 2.5, 3.5],
        refit_target_mean=2.5,
    )
    hac = rs.newey_west_hac(metrics["loss_differential"], 1)

    assert metrics["loss_differential"] == [0.0, 0.0, 0.0, 0.0]
    assert hac["se"] == 0.0
    assert hac["z"] is None
    assert hac["p_one_sided"] is None
    assert hac["reason"] == "zero_long_run_variance"


def test_ridge_condition_and_residual_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(np.linalg, "cond", lambda *_args, **_kwargs: 1e13)
    with pytest.raises(ResearchError, match="condition number"):
        rs.ridge_fit_standardized([[-1.0], [1.0]], [-1.0, 1.0], 0.1)

    monkeypatch.undo()
    monkeypatch.setattr(np.linalg, "solve", lambda system, rhs: np.zeros_like(rhs))
    with pytest.raises(ResearchError, match="relative residual"):
        rs.ridge_fit_standardized([[-1.0], [1.0]], [-1.0, 1.0], 0.1)


def test_hac_numeric_golden() -> None:
    result = rs.newey_west_hac([0.0, 3.0, 0.0, 3.0], 1)

    assert result["mean_loss_differential"] == 1.5
    assert result["autocovariances"] == pytest.approx([2.25, -1.6875])
    assert result["omega_raw"] == pytest.approx(0.5625)
    assert result["omega"] == pytest.approx(0.5625)
    assert result["se"] == pytest.approx(0.375)
    assert result["z"] == pytest.approx(4.0)
    assert result["p_one_sided"] == pytest.approx(0.00003167124183311996, abs=1e-12)


def test_circular_block_bootstrap_numeric_reference() -> None:
    result = rs.circular_block_bootstrap(
        [0.0, 1.0, 4.0, 2.0, 3.0],
        runs=9,
        block_length=2,
        seed=7,
        return_replicates=True,
    )

    assert result["starts"] == [
        [2, 1, 3],
        [0, 0, 4],
        [0, 2, 4],
        [0, 4, 1],
        [0, 0, 3],
        [3, 0, 1],
        [0, 4, 3],
        [0, 4, 0],
        [1, 4, 0],
    ]
    assert result["uncentered_means"] == pytest.approx(
        [2.6, 1.0, 2.0, 1.0, 0.8, 1.4, 1.2, 0.8, 1.6]
    )
    assert result["centered_means"] == pytest.approx(
        [0.6, -1.0, 0.0, -1.0, -1.2, -0.6, -0.8, -1.2, -0.4]
    )
    assert result["percentile_ci"] == pytest.approx([0.8, 2.48])
    assert result["p_one_sided"] == pytest.approx(0.1)
    assert result["monte_carlo_se"] == pytest.approx(0.1)
    with pytest.raises(ResearchError, match="1024"):
        rs.circular_block_bootstrap(
            [0.0, 1.0, 2.0],
            runs=9,
            block_length=1_025,
            seed=7,
        )


def test_centered_block_null_avoids_uncentered_p_value_counterexample() -> None:
    result = rs.circular_block_bootstrap(
        [1.0, 1.0, 1.0, 1.0],
        runs=19,
        block_length=2,
        seed=11,
        return_replicates=True,
    )

    naive_uncentered_p = (
        1 + sum(value >= result["observed_mean"] for value in result["uncentered_means"])
    ) / 20
    assert naive_uncentered_p == 1.0
    assert result["centered_means"] == [0.0] * 19
    assert result["p_one_sided"] == pytest.approx(0.05)
    assert result["percentile_ci"] == pytest.approx([1.0, 1.0])


def test_complete_circular_shift_sampling_and_joint_rotation_are_deterministic() -> None:
    exhaustive = rs.sample_circular_shifts(100, 99, 7)
    sampled = rs.sample_circular_shifts(120, 10, 2026082602)

    assert exhaustive["evaluated_shifts"] == list(range(1, 100))
    assert exhaustive["group_size"] == 100
    assert exhaustive["candidate_nonzero_shifts"] == 99
    assert exhaustive["p_value_resolution"] == 0.01
    assert sampled == rs.sample_circular_shifts(120, 10, 2026082602)
    assert sampled["evaluated_shifts"] == sorted(sampled["evaluated_shifts"])
    assert 0 not in sampled["evaluated_shifts"]
    rows = [(index, -index) for index in range(8)]
    rotated = rs.joint_circular_shift(rows, 3)
    assert rotated == rows[-3:] + rows[:-3]
    assert sorted(rotated) == sorted(rows)
    with pytest.raises(ResearchError, match="row_count"):
        rs.sample_circular_shifts(99, 10, 1)


def test_exhaustive_c100_plus_one_placebo_reference_and_hash() -> None:
    shifts = list(range(1, 100))
    statistics_values = [2.0] * 4 + [1.0] * 95
    first = rs.placebo_randomization_summary(
        2.0,
        shifts,
        statistics_values,
        group_size=100,
        requested_runs=99,
    )
    second = rs.placebo_randomization_summary(
        2.0,
        shifts,
        statistics_values,
        group_size=100,
        requested_runs=99,
    )

    assert first["exceedances"] == 4
    assert first["p_one_sided"] == pytest.approx(0.05)
    assert first["p_value_resolution"] == pytest.approx(0.01)
    assert first["statistics_payload_sha256"] == second["statistics_payload_sha256"]


def test_prediction_integrity_preserves_input_order_and_exact_hex_payload() -> None:
    result = rs.ordered_prediction_integrity(
        ["1:2026-01-01T00:00:00.000000Z", "2:2026-01-02T00:00:00.000000Z"],
        [-0.0, 1.0],
        [0.25, 0.5],
        [-0.25, 0.75],
    )
    expected_payload = [
        {
            "prediction_m0": float.hex(0.25),
            "prediction_m2": float.hex(-0.25),
            "row_id": "1:2026-01-01T00:00:00.000000Z",
            "target": float.hex(-0.0),
        },
        {
            "prediction_m0": float.hex(0.5),
            "prediction_m2": float.hex(0.75),
            "row_id": "2:2026-01-02T00:00:00.000000Z",
            "target": float.hex(1.0),
        },
    ]
    canonical = json.dumps(
        expected_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    assert result["payload"] == expected_payload
    assert result["canonical_json"] == canonical
    assert result["sha256"] == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert result["payload"][0]["row_id"].startswith("1:")
    with pytest.raises(ResearchError, match="chronological"):
        rs.ordered_prediction_integrity(
            ["2:2026-01-02T00:00:00.000000Z", "1:2026-01-01T00:00:00.000000Z"],
            [1.0, 0.0],
            [1.0, 0.0],
            [1.0, 0.0],
        )


def _valid_preflight(**overrides: int) -> dict[str, int]:
    values = {
        "complete_case_n": 140,
        "n_train": 60,
        "n_validation": 30,
        "n_test": 40,
        "p_declared": 2,
        "alpha_count": 3,
        "overlap_lag": 1,
        "hac_lag": 1,
        "block_length": 2,
        "bootstrap_runs": 999,
        "placebo_effective_runs": 99,
    }
    values.update(overrides)
    if "complete_case_n" not in overrides:
        values["complete_case_n"] = (
            values["n_train"] + values["n_validation"] + values["n_test"] + 10
        )
    return values


def test_ridge_workload_preflight_reports_memory_without_allocating() -> None:
    result = rs.ridge_workload_preflight(**_valid_preflight())

    assert result["complete_case_n"] == 140
    assert result["embargo_excluded_rows"] == 10
    assert result["model_cells"] == 280
    assert result["model_matrix_float64_bytes"] == 2240
    assert result["largest_gram_float64_bytes"] == 32
    assert result["placebo_work_units"] == 89_200


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"p_declared": 385}, "p_declared"),
        ({"complete_case_n": 5_000_001, "p_declared": 1}, "model matrix"),
        ({"overlap_lag": 2, "hac_lag": 1}, "hac_lag"),
        ({"overlap_lag": 2, "hac_lag": 2, "block_length": 2}, "block_length"),
        ({"n_test": 50_000, "p_declared": 1, "hac_lag": 1024}, "HAC workload"),
        (
            {
                "n_test": 25_026,
                "p_declared": 1,
                "overlap_lag": 0,
                "hac_lag": 0,
                "bootstrap_runs": 1000,
            },
            "bootstrap workload",
        ),
        (
            {
                "n_train": 202,
                "n_validation": 101,
                "p_declared": 100,
                "alpha_count": 16,
                "placebo_effective_runs": 2000,
            },
            "placebo workload",
        ),
    ],
)
def test_ridge_workload_caps_fail_from_counts_only(overrides: dict[str, int], message: str) -> None:
    with pytest.raises(ResearchError, match=message):
        rs.ridge_workload_preflight(**_valid_preflight(**overrides))


def test_robust_max_p_bonferroni_is_conservative_and_null_propagates() -> None:
    result = rs.robust_union_bonferroni(
        0.01,
        0.04,
        0.02,
        family_size=10,
        family_index=3,
        alpha=0.05,
        mean_loss_differential=1.0,
    )
    missing = rs.robust_union_bonferroni(
        None,
        0.04,
        0.02,
        family_size=10,
        family_index=3,
        alpha=0.05,
        mean_loss_differential=1.0,
    )

    assert result["p_robust"] == pytest.approx(0.04)
    assert result["p_family"] == pytest.approx(0.4)
    assert result["p_family"] >= result["p_robust"]
    assert result["component_null_definitions"] == {
        "H_HAC": "E[d] <= 0 under the declared HAC normal approximation",
        "H_BLOCK": "E[d] <= 0 under the declared circular-block resampling approximation",
        "H_SHIFT": (
            "the zero astronomy alignment is exchangeable under the complete C_N shift group"
        ),
    }
    assert result["robust_null_definition"] == "H_ROBUST = H_HAC ∪ H_BLOCK ∪ H_SHIFT"
    assert result["robust_p_interpretation"] == "conservative intersection-union max-p construction"
    assert result["family_p_scope"] == (
        "conditional on truth and completeness of the preregistered declared family; "
        "the local runner cannot prove completeness"
    )
    assert result["family_index_uniqueness_locally_proven"] is False
    assert result["threshold_diagnostics"]["threshold_met"] is False
    assert missing["p_robust"] is None
    assert missing["p_family"] is None
    assert missing["null_reason"] == "component_p_value_null"
    previous = 0.0
    for family_size in (1, 2, 5, 10, 100):
        adjusted = rs.robust_union_bonferroni(
            0.01,
            0.02,
            0.015,
            family_size=family_size,
            family_index=1,
            alpha=0.05,
            mean_loss_differential=1.0,
        )["p_family"]
        assert adjusted is not None and adjusted >= previous
        previous = adjusted

    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).lower()
    for forbidden_claim in ("confirmatory_pass", "astrology_proven", "family_complete"):
        assert forbidden_claim not in serialized


def test_json_safe_outputs_reject_nonfinite_inputs() -> None:
    with pytest.raises(ResearchError, match="finite"):
        rs.ordered_prediction_integrity(["row"], [math.nan], [0.0], [0.0])
    with pytest.raises(ResearchError, match="finite"):
        rs.robust_union_bonferroni(
            math.inf,
            0.1,
            0.1,
            family_size=1,
            family_index=1,
            alpha=0.05,
            mean_loss_differential=1.0,
        )
