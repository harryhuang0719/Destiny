from __future__ import annotations

from datetime import datetime

import pytest
from timezone_util import get_longitude, resolve_utc_offset, true_solar_time, tzdata_version


def test_new_york_city_resolves_dst_and_sane_true_solar_time() -> None:
    assert tzdata_version() == "2026.3"
    civil = datetime(1990, 6, 15, 14, 0)
    offset = resolve_utc_offset(civil, "New York")
    corrected = true_solar_time(civil, get_longitude("New York"), offset)
    assert offset == -4
    assert corrected.date() == civil.date()
    assert corrected.hour == 13
    assert 0 <= corrected.minute <= 15


def test_dst_nonexistent_and_ambiguous_times_fail_closed() -> None:
    with pytest.raises(ValueError, match="不存在时间"):
        resolve_utc_offset(datetime(2024, 3, 10, 2, 30), "New York")
    with pytest.raises(ValueError, match="歧义时间"):
        resolve_utc_offset(datetime(2024, 11, 3, 1, 30), "New York")
    assert resolve_utc_offset(datetime(2024, 11, 3, 1, 30), "New York", -5) == -5


def test_half_hour_timezone_offset_is_supported() -> None:
    dt = datetime(2020, 1, 1, 12)
    corrected = true_solar_time(dt, longitude=82.5, tz_offset_hours=5.5)
    # Longitude matches the UTC+5:30 standard meridian; only equation-of-time remains.
    assert abs((corrected - dt).total_seconds()) < 20 * 60
