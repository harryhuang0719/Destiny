from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from historical_research import SkyfieldEphemeris, parse_utc, signed_angle_deg

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "jpl_horizons_de440s_golden.json"
KERNEL_ENV = "DESTINY_TEST_DE440S"
EXPECTED_BODIES = {
    "sun": {"command": "10", "name": "Sun", "target_label": "sun", "naif_id": 10},
    "moon": {"command": "301", "name": "Moon", "target_label": "moon", "naif_id": 301},
    "mars": {
        "command": "4",
        "name": "Mars Barycenter",
        "target_label": "mars barycenter",
        "naif_id": 4,
    },
    "jupiter": {
        "command": "5",
        "name": "Jupiter Barycenter",
        "target_label": "jupiter barycenter",
        "naif_id": 5,
    },
}
EXPECTED_QUERY = {
    "format": "json",
    "CENTER": "500@399",
    "MAKE_EPHEM": "YES",
    "EPHEM_TYPE": "OBSERVER",
    "TIME_TYPE": "UT",
    "QUANTITIES": "2,20,31",
    "REF_SYSTEM": "ICRF",
    "REF_PLANE": "ECLIPTIC",
    "CAL_FORMAT": "CAL",
    "CAL_TYPE": "GREGORIAN",
    "TIME_DIGITS": "SECONDS",
    "ANG_FORMAT": "DEG",
    "APPARENT": "AIRLESS",
    "CSV_FORMAT": "YES",
    "EXTRA_PREC": "YES",
    "OBJ_DATA": "NO",
}
HARD_TOLERANCE_CEILINGS = {
    "longitude_deg": 0.00005,
    "latitude_deg": 0.00005,
    "right_ascension_deg": 0.00005,
    "declination_deg": 0.00002,
    "distance_au": 0.00000002,
    "longitude_velocity_deg_day": 0.0006,
}


def _fixture() -> dict:
    return json.loads(
        FIXTURE_PATH.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"non-standard JSON constant: {value}")
        ),
    )


def _assert_official_url(value: str, host: str, path: str) -> None:
    parsed = urlsplit(value)
    assert parsed.scheme == "https"
    assert parsed.hostname == host
    assert parsed.port is None
    assert parsed.username is None and parsed.password is None
    assert parsed.path == path
    assert not parsed.query and not parsed.fragment


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _angle_error_degrees(actual: float, expected: float) -> float:
    return abs(signed_angle_deg(actual, expected))


def test_horizons_fixture_has_frozen_primary_source_contract() -> None:
    fixture = _fixture()
    assert fixture["schema_version"] == "1.0.0"
    assert fixture["fixture_id"] == "jpl-horizons-geocentric-apparent-de440s-v1"
    parse_utc(fixture["captured_at_utc"], allow_pre_utc=True)

    provenance = fixture["provenance"]
    assert provenance["horizons_api_signature"] == {
        "source": "NASA/JPL Horizons API",
        "version": "1.2",
    }
    assert provenance["horizons_dynamical_ephemeris"] == "DE441"
    _assert_official_url(
        provenance["horizons_api_url"],
        "ssd.jpl.nasa.gov",
        "/api/horizons.api",
    )
    _assert_official_url(
        provenance["horizons_api_documentation_url"],
        "ssd-api.jpl.nasa.gov",
        "/doc/horizons.html",
    )
    _assert_official_url(
        provenance["horizons_user_guide_url"],
        "ssd.jpl.nasa.gov",
        "/horizons/manual.html",
    )
    kernel = provenance["official_de440s"]
    assert kernel["size_bytes"] == 32_726_016
    assert kernel["sha256"] == "c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2"
    assert set(kernel["spk_segment_target_ids"]) >= {4, 5, 10, 301, 399}
    _assert_official_url(
        kernel["download_url"],
        "ssd.jpl.nasa.gov",
        "/ftp/eph/planets/bsp/de440s.bsp",
    )
    _assert_official_url(
        kernel["naif_mirror_url"],
        "naif.jpl.nasa.gov",
        "/pub/naif/generic_kernels/spk/planets/de440s.bsp",
    )

    query = fixture["query"]
    assert query["common_parameters"] == EXPECTED_QUERY
    assert query["targets"] == {
        body: {
            "COMMAND": metadata["command"],
            "expected_name": metadata["name"],
            "naif_id": metadata["naif_id"],
        }
        for body, metadata in EXPECTED_BODIES.items()
    }
    requested_times = [parse_utc(value, allow_pre_utc=True) for value in query["tlist_utc"]]
    assert len(requested_times) == 9
    assert requested_times == sorted(requested_times)
    assert len(set(requested_times)) == len(requested_times)

    comparison = fixture["comparison_contract"]
    assert comparison["destiny_frame"] == {
        "origin": "geocentric",
        "position": "apparent",
        "ecliptic": "of-date",
        "radec_epoch": "of-date",
    }
    assert comparison["observer_naif_id"] == 399
    assert comparison["known_frame_difference"] == {
        "horizons": "IAU76/80 of-date, DE441",
        "destiny": "Skyfield IAU2000/2006 of-date, DE440s",
        "consequence": "small non-zero angular and dynamical-ephemeris differences are expected",
    }
    assert comparison["absolute_tolerances"] == HARD_TOLERANCE_CEILINGS

    epochs = fixture["epochs"]
    assert [entry["timestamp_utc"] for entry in epochs] == [
        "1972-01-01T00:00:00Z",
        "2000-01-01T12:00:00Z",
        "2025-01-01T00:00:00Z",
    ]
    for entry in epochs:
        at = parse_utc(entry["timestamp_utc"])
        assert set(entry["bodies"]) == set(EXPECTED_BODIES)
        for body, golden in entry["bodies"].items():
            expected = EXPECTED_BODIES[body]
            assert golden["horizons_target_name"] == expected["name"]
            assert golden["target_naif_id"] == expected["naif_id"]
            assert golden["observer_naif_id"] == 399
            assert golden["destiny_expected_target_label"] == expected["target_label"]
            for field in (
                "right_ascension_deg",
                "declination_deg",
                "distance_au",
                "range_rate_km_s",
                "longitude_deg",
                "latitude_deg",
            ):
                assert isinstance(golden[field], (int, float))
                assert math.isfinite(golden[field])
            support = golden["velocity_support"]
            before = parse_utc(support["before_timestamp_utc"], allow_pre_utc=True)
            after = parse_utc(support["after_timestamp_utc"], allow_pre_utc=True)
            assert at - before == after - at == timedelta(minutes=30)
            derived = (
                signed_angle_deg(support["after_longitude_deg"], support["before_longitude_deg"])
                * 24.0
            )
            assert support["derived_longitude_velocity_deg_day"] == pytest.approx(
                derived, abs=1e-12
            )


@pytest.mark.research
def test_de440s_matches_independent_horizons_goldens() -> None:
    kernel_value = os.getenv(KERNEL_ENV)
    if not kernel_value:
        pytest.skip(f"set {KERNEL_ENV} to the pinned official de440s.bsp")
    kernel = Path(kernel_value).expanduser()
    try:
        metadata = kernel.lstat()
    except OSError as exc:
        pytest.fail(f"cannot inspect {KERNEL_ENV}: {exc}")
    assert not stat.S_ISLNK(metadata.st_mode), "golden kernel path must not be a symlink"
    assert stat.S_ISREG(metadata.st_mode), "golden kernel path must be a regular file"

    fixture = _fixture()
    kernel_contract = fixture["provenance"]["official_de440s"]
    assert metadata.st_size == kernel_contract["size_bytes"]
    assert _sha256(kernel) == kernel_contract["sha256"]

    comparison = fixture["comparison_contract"]
    tolerances = comparison["absolute_tolerances"]
    backend = SkyfieldEphemeris(kernel)
    try:
        assert backend.kernel_sha256 == kernel_contract["sha256"]
        for entry in fixture["epochs"]:
            at = parse_utc(entry["timestamp_utc"])
            state = backend.state(at, tuple(EXPECTED_BODIES))
            assert state["timestamp_utc"] == entry["timestamp_utc"]
            assert state["frame"] == comparison["destiny_frame"]
            assert state["kernel"]["sha256"] == kernel_contract["sha256"]
            for body, golden in entry["bodies"].items():
                actual = state["bodies"][body]
                assert actual["target_label"] == golden["destiny_expected_target_label"]
                assert actual["target_naif_id"] == golden["target_naif_id"]
                assert actual["observer_naif_id"] == golden["observer_naif_id"]
                assert (
                    _angle_error_degrees(actual["longitude_deg"], golden["longitude_deg"])
                    <= tolerances["longitude_deg"]
                )
                assert (
                    abs(actual["latitude_deg"] - golden["latitude_deg"])
                    <= tolerances["latitude_deg"]
                )
                assert (
                    _angle_error_degrees(
                        actual["right_ascension_hours"] * 15.0,
                        golden["right_ascension_deg"],
                    )
                    <= tolerances["right_ascension_deg"]
                )
                assert (
                    abs(actual["declination_deg"] - golden["declination_deg"])
                    <= tolerances["declination_deg"]
                )
                assert (
                    abs(actual["distance_au"] - golden["distance_au"]) <= tolerances["distance_au"]
                )
                assert (
                    abs(
                        actual["longitude_velocity_deg_day"]
                        - golden["velocity_support"]["derived_longitude_velocity_deg_day"]
                    )
                    <= tolerances["longitude_velocity_deg_day"]
                )
    finally:
        backend.close()
