"""Argument parsing and user-input normalization for the Destiny CLI."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # package install
    from .llm_provider import ALLOWED_ENV_KEYS
    from .timezone_util import (
        get_longitude,
        get_timezone_name,
        has_city,
        resolve_utc_offset,
        true_solar_time,
        tzdata_version,
        validate_datetime,
    )
except ImportError:  # direct scripts/cli_support.py import
    from llm_provider import ALLOWED_ENV_KEYS
    from timezone_util import (
        get_longitude,
        get_timezone_name,
        has_city,
        resolve_utc_offset,
        true_solar_time,
        tzdata_version,
        validate_datetime,
    )


MAX_ENV_FILE_BYTES = 1024 * 1024
MAX_QUESTION_CHARS = 20_000


class CliError(ValueError):
    """A user-facing CLI error that should not produce a traceback."""


def configure_utf8_stdio() -> None:
    """Make JSON and stdin text portable across Windows and redirected pipes."""
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")


def load_env_file(path: str | Path) -> list[str]:
    """Load only known Destiny keys from an explicitly requested dotenv file."""
    env_path = Path(path).expanduser()
    try:
        if not env_path.is_file():
            raise CliError(f"环境变量文件不存在: {env_path}")
        if env_path.stat().st_size > MAX_ENV_FILE_BYTES:
            raise CliError(f"环境变量文件超过 {MAX_ENV_FILE_BYTES:,} bytes 安全上限")
        env_text = env_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CliError(f"无法读取环境变量文件 {env_path}: {exc}") from exc

    loaded: list[str] = []
    for number, raw_line in enumerate(env_text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise CliError(f"{env_path}:{number} 不是 KEY=VALUE 格式")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_ENV_KEYS:
            continue
        os.environ.setdefault(key, value.strip().strip("'\""))
        loaded.append(key)
    return loaded


def _default_flags() -> dict[str, Any]:
    return {
        "json": False,
        "llm": False,
        "no_llm": False,
        "provider": None,
        "llm_fallback": False,
        "env_file": None,
        "solar": False,
        "city": "default",
        "tz": None,
        "longitude": None,
        "minute": 0,
        "second": 0,
        "sect": 2,
        "city1": None,
        "city2": None,
        "tz1": None,
        "tz2": None,
        "longitude1": None,
        "longitude2": None,
        "minute1": 0,
        "minute2": 0,
        "second1": 0,
        "second2": 0,
        "sect1": 2,
        "sect2": 2,
        "target_year": None,
        "month": None,
        "bazi_args": None,
        "leap": False,
        "seed": None,
        "question_stdin": False,
        "question_file": None,
        "cities": False,
    }


def _parse_global_flags(argv: list[str]) -> tuple[dict[str, Any], list[str]]:
    flags = _default_flags()
    clean: list[str] = []
    i = 0
    value_flags: dict[str, tuple[str, Any]] = {
        "--provider": ("provider", str),
        "--env-file": ("env_file", str),
        "--city": ("city", str),
        "--tz": ("tz", float),
        "--longitude": ("longitude", float),
        "--minute": ("minute", int),
        "--second": ("second", int),
        "--sect": ("sect", int),
        "--city1": ("city1", str),
        "--city2": ("city2", str),
        "--tz1": ("tz1", float),
        "--tz2": ("tz2", float),
        "--longitude1": ("longitude1", float),
        "--longitude2": ("longitude2", float),
        "--minute1": ("minute1", int),
        "--minute2": ("minute2", int),
        "--second1": ("second1", int),
        "--second2": ("second2", int),
        "--sect1": ("sect1", int),
        "--sect2": ("sect2", int),
        "--year": ("target_year", int),
        "--month": ("month", str),
        "--seed": ("seed", int),
        "--question-file": ("question_file", str),
    }
    bool_flags = {
        "--json": "json",
        "--llm": "llm",
        "--no-llm": "no_llm",
        "--llm-fallback": "llm_fallback",
        "--solar": "solar",
        "--leap": "leap",
        "--question-stdin": "question_stdin",
        "--cities": "cities",
    }
    while i < len(argv):
        token = argv[i]
        if token == "--":
            clean.extend(argv[i + 1 :])
            break
        if token in bool_flags:
            flags[bool_flags[token]] = True
        elif token == "--bazi":
            if i + 5 >= len(argv):
                raise CliError("--bazi 需要 Y M D H G 五个值")
            try:
                flags["bazi_args"] = tuple(int(value) for value in argv[i + 1 : i + 6])
            except ValueError as exc:
                raise CliError("--bazi 的五个值必须是整数") from exc
            i += 5
        elif token in value_flags:
            if i + 1 >= len(argv):
                raise CliError(f"{token} 缺少值")
            field, converter = value_flags[token]
            try:
                flags[field] = converter(argv[i + 1])
            except ValueError as exc:
                raise CliError(f"{token} 的值无效: {argv[i + 1]}") from exc
            i += 1
        elif token.startswith("--"):
            raise CliError(f"未知选项: {token}")
        else:
            clean.append(token)
        i += 1

    if flags["llm"] and flags["no_llm"]:
        raise CliError("--llm 与 --no-llm 不能同时使用")
    if flags["llm"] and not flags["provider"]:
        raise CliError("使用 --llm 时必须显式指定 --provider")
    if flags["llm_fallback"] and not flags["llm"]:
        raise CliError("--llm-fallback 必须与 --llm 一起使用")
    if flags["sect"] not in (1, 2) or flags["sect1"] not in (1, 2) or flags["sect2"] not in (1, 2):
        raise CliError("--sect/--sect1/--sect2 必须是 1 或 2")
    return flags, clean


def _gender_int(value: str | int | None, default: int = 1) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CliError("性别必须是 1（男）或 0（女）") from exc
    if parsed not in (0, 1):
        raise CliError("性别必须是 1（男）或 0（女）")
    return parsed


def _gender_text(value: str | None, default: str = "男") -> str:
    parsed = value or default
    aliases = {"1": "男", "0": "女", "male": "男", "female": "女"}
    parsed = aliases.get(parsed.lower(), parsed) if isinstance(parsed, str) else parsed
    if parsed not in ("男", "女"):
        raise CliError("性别必须是 男/女（也可用 1/0）")
    return parsed


def _validate_birth(
    year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0
) -> None:
    error = validate_datetime(year, month, day, hour, minute, second)
    if error:
        raise CliError(error)


def _location_flags(flags: dict[str, Any], suffix: str = "") -> dict[str, Any]:
    if suffix:
        return {
            "solar": flags["solar"]
            or any(
                flags[key] is not None
                for key in (f"city{suffix}", f"tz{suffix}", f"longitude{suffix}")
            ),
            "city": flags[f"city{suffix}"] or "default",
            "tz": flags[f"tz{suffix}"],
            "longitude": flags[f"longitude{suffix}"],
        }
    return {
        "solar": flags["solar"],
        "city": flags["city"],
        "tz": flags["tz"],
        "longitude": flags["longitude"],
    }


def _apply_solar(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    location: dict[str, Any],
) -> tuple[tuple[int, int, int, int, int, int], dict[str, Any] | None]:
    original = datetime(year, month, day, hour, minute, second)
    if not (
        location["solar"] or location["city"] != "default" or location["longitude"] is not None
    ):
        return (year, month, day, hour, minute, second), None

    city = location["city"]
    longitude = location["longitude"]
    if city != "default" and not has_city(city) and longitude is None:
        raise CliError(f"未知城市: {city}；请使用 --longitude 与 --tz 明确指定")
    if longitude is None:
        longitude = get_longitude(city)
    if not -180 <= longitude <= 180:
        raise CliError("经度必须在 -180 到 180 之间")
    if city == "default" and location["tz"] is None and location["longitude"] is not None:
        raise CliError("自定义 --longitude 时必须同时提供 --tz")

    try:
        offset = resolve_utc_offset(original, city, location["tz"])
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    corrected = true_solar_time(original, longitude, offset)
    metadata = {
        "convention_version": "true-solar-time-v2",
        "original_civil_datetime": original.isoformat(timespec="seconds"),
        "city": None if city == "default" else city,
        "timezone": get_timezone_name(city) if city != "default" else None,
        "utc_offset_hours": offset,
        "longitude": longitude,
        "tzdata_version": tzdata_version(),
        "corrected_true_solar_datetime": corrected.isoformat(timespec="seconds"),
    }
    return (
        corrected.year,
        corrected.month,
        corrected.day,
        corrected.hour,
        corrected.minute,
        corrected.second,
    ), metadata


def _read_question(positional: str, flags: dict[str, Any]) -> str:
    source_count = (
        int(bool(positional)) + int(flags["question_stdin"]) + int(bool(flags["question_file"]))
    )
    if source_count > 1:
        raise CliError("问题只能来自位置参数、--question-stdin 或 --question-file 其中一种")
    if flags["question_stdin"]:
        question = sys.stdin.read(MAX_QUESTION_CHARS + 1)
    elif flags["question_file"]:
        path = Path(flags["question_file"]).expanduser()
        try:
            if not path.is_file():
                raise CliError(f"问题文件不存在: {path}")
            if path.stat().st_size > 4 * (MAX_QUESTION_CHARS + 1):
                raise CliError(f"问题文件超过 {MAX_QUESTION_CHARS:,} 字符安全上限")
            with path.open(encoding="utf-8") as handle:
                question = handle.read(MAX_QUESTION_CHARS + 1)
        except (OSError, UnicodeError) as exc:
            raise CliError(f"无法读取问题文件 {path}: {exc}") from exc
    else:
        question = positional
    question = question.rstrip("\r\n")
    if len(question) > MAX_QUESTION_CHARS:
        raise CliError(f"问题文本超过 {MAX_QUESTION_CHARS:,} 字符限制")
    return question


def _ints(values: list[str], count: int, usage: str) -> list[int]:
    if len(values) < count:
        raise CliError(f"参数不足。用法: {usage}")
    try:
        return [int(value) for value in values[:count]]
    except ValueError as exc:
        raise CliError(f"日期和时间参数必须是整数。用法: {usage}") from exc
