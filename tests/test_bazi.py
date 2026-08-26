from __future__ import annotations

import pytest
from bazi_engine import generate_bazi


def test_bazi_known_chart_and_yun_metadata() -> None:
    chart = generate_bazi(1990, 1, 15, 14, 1)
    assert [chart["pillars"][key]["ganzhi"] for key in ("year", "month", "day", "time")] == [
        "己巳",
        "丁丑",
        "庚辰",
        "癸未",
    ]
    assert sum(chart["day_master"]["wuxing_counts"].values()) == 8
    assert "启发式" in chart["day_master"]["method"]
    assert chart["da_yun"]["start_solar"] == "1993-04-04"
    assert chart["da_yun"]["start_offset"] == {
        "years": 3,
        "months": 2,
        "days": 20,
        "hours": 0,
    }
    assert chart["da_yun"]["list"][0]["ganzhi"] == "丙子"
    assert chart["da_yun"]["list"][0]["start_year"] == 1993


def test_bazi_female_yun_direction_fixture() -> None:
    chart = generate_bazi(1990, 1, 15, 14, 0)
    assert chart["da_yun"]["start_solar"] == "1996-08-25"
    assert chart["da_yun"]["start_offset"]["years"] == 6
    assert chart["da_yun"]["list"][0]["ganzhi"] == "戊寅"


def test_bazi_sect_is_explicit_at_late_zi() -> None:
    sect1 = generate_bazi(2024, 2, 10, 23, 1, sect=1)
    sect2 = generate_bazi(2024, 2, 10, 23, 1, sect=2)
    assert sect1["pillars"]["day"]["ganzhi"] == "乙巳"
    assert sect2["pillars"]["day"]["ganzhi"] == "甲辰"
    assert sect1["input"]["sect"] == 1
    assert sect2["input"]["sect"] == 2


@pytest.mark.parametrize("gender", [-1, 2, 99])
def test_bazi_rejects_invalid_gender(gender: int) -> None:
    with pytest.raises(ValueError):
        generate_bazi(2000, 1, 1, 12, gender)
