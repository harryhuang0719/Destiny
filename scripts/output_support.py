"""Stable output contracts, help text, and environment diagnostics for Destiny."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # package install
    from . import llm_provider
except ImportError:  # direct scripts/output_support.py import
    import llm_provider


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SCHEMA_VERSION = "2.0.0"
DISCLAIMER = "传统文化与娱乐参考；不构成医疗、法律、投资或重大人生决策建议。"


@lru_cache(maxsize=1)
def engine_versions() -> dict[str, str | None]:
    def version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    iztro_version = None
    try:
        lock = json.loads((ROOT_DIR / "package-lock.json").read_text(encoding="utf-8"))
        iztro_version = lock["packages"]["node_modules/iztro"]["version"]
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    return {
        "destiny_schema": SCHEMA_VERSION,
        "lunar_python": version("lunar_python"),
        "tzdata": version("tzdata"),
        "httpx": version("httpx"),
        "iztro": iztro_version,
    }


def base_result(kind: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": kind,
        "engine_versions": engine_versions(),
        "disclaimer": DISCLAIMER,
    }


def print_help() -> None:
    print(
        """Destiny 2 — 本地排盘，解读可选

用法:
  destiny bazi Y M D H [G] [--minute N] [--second N] [--json]
  destiny ziwei Y M D H [男|女] [--minute N] [--json]
  destiny comprehensive Y M D H [G] [--minute N] [--json]
  destiny calendar Y M D [H] [--minute N] [--json]
  destiny lunar Y M D [--leap] [--json]
  destiny iching dayan [问题] [--seed N] [--question-stdin] [--json]
  destiny iching time Y M D H [问题] [--minute N] [--question-stdin] [--json]
  destiny iching manual 789978 [问题] [--question-stdin] [--json]
  destiny hepan Y1 M1 D1 H1 G1 Y2 M2 D2 H2 G2 [--json]
  destiny liunian Y M D H [G] --year YYYY [--json]
  destiny zeji 活动 --month YYYY-MM [--bazi Y M D H G] [--json]
  destiny history --help
  destiny doctor [--json]
  destiny --cities

核心默认离线。启用外部解读时必须显式提供:
  --llm --provider minimax|deepseek|custom
  --llm-fallback 仅在你同意把同一份数据发给备用供应商时使用。

真太阳时:
  --solar --city 上海
  --solar --longitude 77.21 --tz 5.5
  合盘请分别使用 --city1/--city2（或 longitude1/tz1 与 longitude2/tz2）。

安全传递用户问题:
  使用 --question-stdin，并通过进程 stdin 写入原文；不要把用户文本拼进 shell。
"""
    )


def _print_result(result: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return

    correction = result.get("time_correction")
    if correction and "corrected_true_solar_datetime" in correction:
        print(
            "真太阳时校正: "
            f"{correction['original_civil_datetime']} → "
            f"{correction['corrected_true_solar_datetime']}",
            file=sys.stderr,
        )

    kind = result["type"]
    if kind in ("calendar", "lunar_to_solar", "doctor"):
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return
    if kind in ("bazi", "ziwei", "iching"):
        print(result["text"])
    elif kind == "comprehensive":
        print(result["bazi"]["text"])
        print("\n" + "-" * 48 + "\n")
        print(result["ziwei"]["text"])
    elif kind == "hepan":
        print("【甲方八字】")
        print(result["person1"]["text"])
        print("\n【乙方八字】")
        print(result["person2"]["text"])
    elif kind == "liunian":
        print(f"【{result['target_year']}年 · {result['year_ganzhi']}】\n")
        print(result["bazi"]["text"])
    elif kind == "zeji":
        print(f"【{result['activity']}择日 · {result['month']}】")
        print(f"匹配 {result['good_days']} / {result['total_days']} 天")
        for item in result["candidates"][:10]:
            print(f"  {item['date']} {item['weekday']} · {item['lunar']} · {item['ganzhi']}")
            print(f"    宜: {', '.join(item['yi'][:8])}")
    if result.get("interpretation"):
        print("\n" + "=" * 60 + "\n")
        print(result["interpretation"])
    print(f"\n⚠️ {DISCLAIMER}")


def doctor_report() -> dict[str, Any]:
    python_ok = sys.version_info >= (3, 10)
    node_path = shutil.which("node")
    npm_path = shutil.which("npm")
    iztro_path = ROOT_DIR / "node_modules" / "iztro" / "package.json"
    node_version = None
    node_ok = False
    if node_path:
        child_env = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
            if key in os.environ
        }
        try:
            process = subprocess.run(
                [node_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env=child_env,
            )
            node_version = process.stdout.strip().lstrip("v")
            node_ok = process.returncode == 0 and int(node_version.split(".", 1)[0]) >= 18
        except (OSError, ValueError, subprocess.TimeoutExpired):
            node_ok = False
    checks = {
        "python": {
            "ok": python_ok,
            "version": ".".join(map(str, sys.version_info[:3])),
            "required": ">=3.10",
        },
        "lunar_python": {
            "ok": engine_versions()["lunar_python"] is not None,
            "version": engine_versions()["lunar_python"],
        },
        "tzdata": {
            "ok": engine_versions()["tzdata"] == "2026.3",
            "version": engine_versions()["tzdata"],
            "required": "2026.3",
        },
        "httpx": {
            "ok": llm_provider.HAS_HTTPX,
            "version": engine_versions()["httpx"],
            "needed_for": "optional --llm only",
        },
        "node": {"ok": node_ok, "path": node_path, "version": node_version, "required": ">=18"},
        "npm": {"ok": bool(npm_path), "path": npm_path},
        "iztro": {
            "ok": iztro_path.is_file(),
            "version": engine_versions()["iztro"],
            "path": str(iztro_path),
        },
    }
    ready_core = checks["python"]["ok"] and checks["lunar_python"]["ok"] and checks["tzdata"]["ok"]
    ready_all = ready_core and checks["node"]["ok"] and checks["iztro"]["ok"]
    return {
        **base_result("doctor"),
        "ready_core": ready_core,
        "ready_all_engines": ready_all,
        "checks": checks,
    }
