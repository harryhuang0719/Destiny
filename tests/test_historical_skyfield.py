from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from historical_research import (
    ResearchError,
    SkyfieldEphemeris,
    features_from_state,
    parse_utc,
    write_feature_csv,
)
from history_cli import main as history_main


@pytest.mark.research
def test_jpl_kernel_smoke_and_target_metadata() -> None:
    kernel_value = os.getenv("DESTINY_TEST_KERNEL")
    if not kernel_value:
        pytest.skip("set DESTINY_TEST_KERNEL to a local de440s.bsp")
    kernel = Path(kernel_value)
    if not kernel.is_file():
        pytest.skip(f"kernel not found: {kernel}")
    backend = SkyfieldEphemeris(kernel)
    at = parse_utc(
        os.getenv("DESTINY_TEST_AT", "2000-01-01T12:00:00Z"),
        allow_pre_utc=True,
    )
    state = backend.state(
        at,
        ("sun", "moon", "mars", "jupiter"),
        allow_pre_utc=at < datetime(1972, 1, 1, tzinfo=timezone.utc),
    )
    assert state["kernel"]["sha256"] == backend.kernel_sha256
    assert state["frame"] == {
        "origin": "geocentric",
        "position": "apparent",
        "ecliptic": "of-date",
        "radec_epoch": "of-date",
    }
    assert state["bodies"]["jupiter"]["target_label"] == "jupiter barycenter"
    assert all(0 <= body["longitude_deg"] < 360 for body in state["bodies"].values())
    features = features_from_state(state, (("moon", "sun"), ("mars", "jupiter")))
    assert features["moon_illuminated_fraction"] == pytest.approx(0.99285, abs=1e-5)
    assert 0 <= features["moon_phase_illumination_proxy"] <= 1


@pytest.mark.research
def test_history_cli_filters_default_pairs_for_body_subset(capsys) -> None:
    kernel_value = os.getenv("DESTINY_TEST_KERNEL")
    if not kernel_value:
        pytest.skip("set DESTINY_TEST_KERNEL to a local JPL SPK")
    at = os.getenv("DESTINY_TEST_AT", "2000-01-01T12:00:00Z")
    code = history_main(
        [
            "astro",
            "--kernel",
            kernel_value,
            "--at",
            at,
            "--allow-pre-utc",
            "--bodies",
            "sun,moon,mercury,mars,jupiter,saturn",
        ]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert "venus_jupiter_h1_sin" not in result["features"]
    assert "mars_jupiter_h1_sin" in result["features"]


@pytest.mark.research
def test_feature_build_protects_manifest_and_kernel(tmp_path) -> None:
    kernel_value = os.getenv("DESTINY_TEST_KERNEL")
    if not kernel_value:
        pytest.skip("set DESTINY_TEST_KERNEL to a local JPL SPK")
    at = parse_utc(os.getenv("DESTINY_TEST_AT", "2000-01-01T12:00:00Z"), allow_pre_utc=True)
    backend = SkyfieldEphemeris(kernel_value)
    output = tmp_path / "features.csv"
    manifest = Path(f"{output}.manifest.json")
    manifest.write_text("do-not-clobber", encoding="utf-8")
    with pytest.raises(ResearchError, match="已存在"):
        write_feature_csv(
            backend,
            at,
            at,
            output,
            bodies=("sun", "moon"),
            pairs=(("sun", "moon"),),
            allow_pre_utc=at.year < 1972,
        )
    assert manifest.read_text(encoding="utf-8") == "do-not-clobber"
    assert not output.exists()
    manifest.unlink()
    built = write_feature_csv(
        backend,
        at,
        at,
        output,
        bodies=("sun", "moon"),
        pairs=(("sun", "moon"),),
        allow_pre_utc=at.year < 1972,
    )
    assert built["source_type"] == "jpl_spk"
    assert built["coordinate_profile"] == "tropical_geocentric_apparent_of_date_v1"
    assert built["feature_file_sha256"]
    with pytest.raises(ResearchError, match="路径冲突"):
        write_feature_csv(
            backend,
            at,
            at,
            kernel_value,
            bodies=("sun", "moon"),
            pairs=(("sun", "moon"),),
            allow_pre_utc=at.year < 1972,
            overwrite=True,
        )
