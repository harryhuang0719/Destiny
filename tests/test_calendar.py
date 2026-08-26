from __future__ import annotations

import pytest
from bazi_engine import generate_bazi
from calendar_engine import get_jie_qi_around, lunar_to_solar, solar_to_lunar_info


def test_calendar_known_lunar_new_year() -> None:
    data = solar_to_lunar_info(2000, 2, 5)
    assert data["lunar"]["full_string"] == "二〇〇〇年正月初一"
    assert data["ganzhi"]["year"] == "庚辰"
    assert data["ganzhi"]["month"] == "戊寅"
    assert data["ganzhi"]["day"] == "癸巳"
    assert data["shengxiao"] == "龙"


def test_precise_jieqi_boundary_changes_bazi_pillars() -> None:
    before = generate_bazi(2024, 2, 4, 16, 1, 26, 0)
    after = generate_bazi(2024, 2, 4, 16, 1, 28, 0)
    assert [before["pillars"][key]["ganzhi"] for key in ("year", "month")] == [
        "癸卯",
        "乙丑",
    ]
    assert [after["pillars"][key]["ganzhi"] for key in ("year", "month")] == [
        "甲辰",
        "丙寅",
    ]
    info = solar_to_lunar_info(2024, 2, 4, 16, 28)
    assert info["jie_qi_year"]["立春"] == "2024-02-04 16:27:07"
    assert info["ganzhi"]["year"] == "甲辰"
    assert info["ganzhi"]["lunar_year"] == "癸卯"


def test_calendar_exposes_tianshen_and_precise_neighboring_jieqi() -> None:
    data = solar_to_lunar_info(2026, 6, 1)
    assert set(data["zhi_shen"]) == {"name", "type", "luck"}
    around = get_jie_qi_around(2024, 2, 4)
    assert around
    assert all(len(item["solar"]) == 19 for item in around)


def test_lunar_to_solar_roundtrip_and_invalid_date() -> None:
    converted = lunar_to_solar(2024, 1, 1)
    assert converted["solar_string"] == "2024-02-10"
    with pytest.raises(ValueError):
        lunar_to_solar(2024, 1, 31)


@pytest.mark.parametrize("args", [(2024, 2, 30, 0), (2024, 1, 1, 24), (1899, 1, 1, 0)])
def test_calendar_rejects_invalid_civil_inputs(args: tuple[int, int, int, int]) -> None:
    with pytest.raises(ValueError):
        solar_to_lunar_info(*args)
