from __future__ import annotations

import random
from datetime import datetime

import pytest
from iching_engine import BAGUA, dayan_one_yao, interpret, qigua_dayan, qigua_manual, qigua_time


def test_canonical_trigram_bottom_to_top_lines() -> None:
    assert {name: value["lines"] for name, value in BAGUA.items()} == {
        "乾": (1, 1, 1),
        "兑": (1, 1, 0),
        "离": (1, 0, 1),
        "震": (1, 0, 0),
        "巽": (0, 1, 1),
        "坎": (0, 1, 0),
        "艮": (0, 0, 1),
        "坤": (0, 0, 0),
    }


@pytest.mark.parametrize(
    ("lines", "ben", "changed"),
    [
        ([7, 7, 7, 7, 7, 7], "乾为天", "乾为天"),
        ([8, 8, 8, 8, 8, 8], "坤为地", "坤为地"),
        ([7, 8, 8, 7, 7, 7], "天雷无妄", "天雷无妄"),
        ([9, 7, 7, 7, 7, 7], "乾为天", "天风姤"),
    ],
)
def test_known_hexagrams(lines: list[int], ben: str, changed: str) -> None:
    result = interpret(lines)
    assert result["ben_gua"]["name"] == ben
    assert result["zhi_gua"]["name"] == changed


def test_meihua_time_fixture_uses_lunar_date_and_one_based_branches() -> None:
    lines = qigua_time(datetime(2024, 2, 10, 12))
    result = interpret(lines)
    assert result["ben_gua"]["name"] == "山水蒙"
    assert result["zhi_gua"]["name"] == "山地剥"
    assert result["changing"]["positions"] == [2]


@pytest.mark.parametrize("value", ["6789", "6789678", "6x7x8x9x7x8", "123456", ""])
def test_manual_input_is_strict(value: str) -> None:
    with pytest.raises(ValueError):
        qigua_manual(value)


def test_interpret_validates_length_and_values() -> None:
    with pytest.raises(ValueError):
        interpret([7] * 5)
    with pytest.raises(ValueError):
        interpret([7, 7, 7, 7, 7, 5])


class FixedDraw:
    def __init__(self, draw: int):
        self.draw = draw

    def randrange(self, _stop: int) -> int:
        return self.draw


@pytest.mark.parametrize(
    ("draw", "yao"), [(0, 6), (1, 7), (5, 7), (6, 8), (12, 8), (13, 9), (15, 9)]
)
def test_dayan_canonical_weight_buckets(draw: int, yao: int) -> None:
    assert dayan_one_yao(FixedDraw(draw)) == yao


def test_dayan_seed_replays_exactly() -> None:
    first = qigua_dayan(random.Random(42))
    second = qigua_dayan(random.Random(42))
    assert first == second
    assert set(first) <= {6, 7, 8, 9}
