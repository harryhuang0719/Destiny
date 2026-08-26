from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "destiny_analyzer.py"


def run_cli(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MINIMAX_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "CUSTOM_API_KEY": "",
        "CUSTOM_API_BASE": "",
    }
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def test_json_stdout_is_exactly_one_document() -> None:
    process = run_cli("bazi", "1990", "1", "15", "14", "1", "--json", "--no-llm")
    assert process.returncode == 0, process.stderr
    data = json.loads(process.stdout)
    assert data["type"] == "bazi"
    assert data["data"]["pillars"]["day"]["ganzhi"] == "庚辰"


def test_legacy_json_mode_remains_valid() -> None:
    process = run_cli("json", "bazi", "1990", "1", "15", "14", "1", "--no-llm")
    assert process.returncode == 0
    assert json.loads(process.stdout)["schema_version"] == "2.0.0"


def test_comprehensive_no_llm_has_no_interpretation_even_with_fake_key() -> None:
    env = {**os.environ, "MINIMAX_API_KEY": "definitely-not-a-real-key"}
    process = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "comprehensive",
            "1990",
            "1",
            "15",
            "14",
            "1",
            "--no-llm",
            "--json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert "interpretation" not in json.loads(process.stdout)


def test_true_solar_diagnostic_stays_out_of_json_stdout() -> None:
    process = run_cli(
        "bazi",
        "1990",
        "6",
        "15",
        "14",
        "1",
        "--solar",
        "--city",
        "New York",
        "--json",
        "--no-llm",
    )
    assert process.returncode == 0, process.stderr
    data = json.loads(process.stdout)
    assert data["time_correction"]["utc_offset_hours"] == -4
    assert data["time_correction"]["tzdata_version"] == "2026.3"
    assert "真太阳时校正" not in process.stdout


def test_liunian_and_zeji_use_nested_calendar_fields() -> None:
    annual = run_cli("liunian", "1990", "1", "15", "14", "1", "--year", "2026", "--json")
    assert json.loads(annual.stdout)["year_ganzhi"] == "丙午"
    dates = run_cli("zeji", "结婚", "--month", "2026-09", "--json")
    candidate = json.loads(dates.stdout)["candidates"][0]
    assert candidate["lunar"]
    assert candidate["ganzhi"]
    assert candidate["zhi_shen"]["name"]


def test_question_stdin_preserves_shell_metacharacters(tmp_path: Path) -> None:
    marker = tmp_path / "must_not_exist"
    question = f'原样-$({{"touch {marker}"}})-`touch {marker}`-"quotes"\n下一行'
    process = run_cli(
        "iching",
        "manual",
        "789978",
        "--question-stdin",
        "--json",
        input_text=question,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["data"]["question"] == question
    assert not marker.exists()


@pytest.mark.parametrize(
    "args",
    [
        ("bazi", "2024", "2", "30", "12"),
        ("bazi", "2024", "1", "1", "12", "2"),
        ("ziwei", "2024", "1", "1", "12", "unknown"),
        ("iching", "manual", "123456"),
        ("bazi", "2024", "1", "1", "12", "--unknown"),
    ],
)
def test_invalid_cli_inputs_are_nonzero_without_traceback(args: tuple[str, ...]) -> None:
    process = run_cli(*args)
    assert process.returncode != 0
    assert "Traceback" not in process.stderr


def test_llm_requires_explicit_provider() -> None:
    process = run_cli("bazi", "1990", "1", "15", "14", "1", "--llm")
    assert process.returncode == 2
    assert "--provider" in process.stderr


def test_utf8_json_and_question_stdin_ignore_legacy_pipe_encoding() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    process = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "iching",
            "manual",
            "789978",
            "--question-stdin",
            "--json",
        ],
        cwd=ROOT,
        input="中文问题",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["data"]["question"] == "中文问题"


@pytest.mark.integration
def test_ziwei_bridge_is_utf8_under_legacy_locale() -> None:
    env = {
        **os.environ,
        "PYTHONIOENCODING": "ascii",
        "PYTHONUTF8": "0",
        "LC_ALL": "C",
    }
    process = subprocess.run(
        [sys.executable, str(CLI), "ziwei", "2000", "8", "16", "23", "1", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["data"]["input"]["gender"] == "男"


def test_question_stdin_size_limit_is_enforced_before_unbounded_read() -> None:
    process = run_cli(
        "iching",
        "manual",
        "789978",
        "--question-stdin",
        "--json",
        input_text="问" * 20_001,
    )
    assert process.returncode == 2
    assert "20,000" in process.stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("calendar_engine.py", ["2026", "8", "26"]),
        ("bazi_engine.py", ["1990", "1", "15", "14", "1"]),
        ("iching_engine.py", ["manual", "789978"]),
        ("ziwei_engine.py", ["2000", "8", "16", "23", "1"]),
    ],
)
def test_standalone_engines_force_utf8_under_legacy_locale(script: str, args: list[str]) -> None:
    env = {
        **os.environ,
        "PYTHONIOENCODING": "ascii",
        "PYTHONUTF8": "0",
        "LC_ALL": "C",
    }
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    json.loads(process.stdout)


def test_standalone_iching_stdin_is_bounded() -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "iching_engine.py"),
            "manual",
            "789978",
            "--question-stdin",
        ],
        cwd=ROOT,
        input="问" * 20_001,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert process.returncode == 2
    assert "20,000" in process.stderr
