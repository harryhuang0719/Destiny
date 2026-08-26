from __future__ import annotations

import pytest
from ziwei_engine import IZTRO_DIR, _hour_to_index, _safe_node_env, generate_ziwei


def test_ziwei_time_indices_include_late_zi() -> None:
    assert _hour_to_index(0) == 0
    assert _hour_to_index(1) == 1
    assert _hour_to_index(22) == 11
    assert _hour_to_index(23) == 12


def test_ziwei_rejects_javascript_injection() -> None:
    payload = "男'); throw new Error(process.env.DESTINY_SENTINEL);//"
    with pytest.raises(ValueError):
        generate_ziwei(2000, 8, 16, 12, payload)


def test_node_child_environment_is_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESTINY_SENTINEL", "must-not-cross")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross")
    child = _safe_node_env()
    assert "DESTINY_SENTINEL" not in child
    assert "GITHUB_TOKEN" not in child
    assert child["NODE_PATH"].endswith("node_modules")


@pytest.mark.integration
def test_ziwei_early_and_late_zi_golden() -> None:
    if not (IZTRO_DIR / "node_modules" / "iztro").is_dir():
        pytest.skip("run npm ci first")
    early = generate_ziwei(2000, 8, 16, 0, "男")
    late = generate_ziwei(2000, 8, 16, 23, "男")
    assert "error" not in early and "error" not in late
    assert all(isinstance(palace["isEmpty"], bool) for palace in early["palaces"])
    early_money = next(p for p in early["palaces"] if p["name"] == "财帛")
    late_money = next(p for p in late["palaces"] if p["name"] == "财帛")
    late_travel = next(p for p in late["palaces"] if p["name"] == "迁移")
    assert [star["name"] for star in early_money["majorStars"]] == ["天同"]
    assert [star["name"] for star in late_money["majorStars"]] == ["破军"]
    assert "廉贞" in [star["name"] for star in late_travel["majorStars"]]
