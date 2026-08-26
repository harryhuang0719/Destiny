"""Stable output contracts, help text, and environment diagnostics for Destiny."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

if __package__:  # package install
    from . import llm_provider
else:  # direct scripts/output_support.py import
    import llm_provider


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SCHEMA_VERSION = "2.0.0"
DISCLAIMER = "传统文化与娱乐参考；不构成医疗、法律、投资或重大人生决策建议。"
MAX_NODE_PACKAGE_JSON_BYTES = 128 * 1024

_NODE_ENV_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    }
)


def _node_child_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.upper() in _NODE_ENV_KEYS}


def _read_small_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if not path.is_file():
            return None, "missing"
        with path.open("rb") as stream:
            raw = stream.read(MAX_NODE_PACKAGE_JSON_BYTES + 1)
        if len(raw) > MAX_NODE_PACKAGE_JSON_BYTES:
            return None, "package_json_too_large"
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid_package_json"
    if not isinstance(value, dict):
        return None, "invalid_package_json"
    return value, None


def _expected_iztro_version() -> str | None:
    lock, _error = _read_small_json_object(ROOT_DIR / "package-lock.json")
    if lock is None:
        return None
    try:
        version = lock["packages"]["node_modules/iztro"]["version"]
    except (KeyError, TypeError):
        return None
    return version if isinstance(version, str) and version else None


def _expected_numpy_version(python_version: tuple[int, int] | None = None) -> str:
    version = python_version or tuple(sys.version_info[:2])
    if version < (3, 11):
        return "2.2.6"
    if version == (3, 11):
        return "2.4.6"
    return "2.5.2"


@lru_cache(maxsize=2)
def engine_versions(*, include_research: bool = True) -> dict[str, str | None]:
    def version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    iztro_version = _expected_iztro_version()
    return {
        "destiny_schema": SCHEMA_VERSION,
        "destiny_package": version("destiny-agent-skill"),
        "lunar_python": version("lunar_python"),
        "tzdata": version("tzdata"),
        "httpx": version("httpx"),
        "skyfield": version("skyfield") if include_research else None,
        "numpy": version("numpy") if include_research else None,
        "iztro": iztro_version,
    }


def _module_runtime_check(
    module_name: str,
    installed_version: str | None,
    required_version: str,
) -> dict[str, Any]:
    status = "missing"
    loaded_version = None
    import_error = None
    if installed_version is not None and installed_version != required_version:
        status = "version_mismatch"
    elif installed_version == required_version:
        try:
            module = importlib.import_module(module_name)
            candidate = getattr(module, "__version__", None)
            loaded_version = candidate if isinstance(candidate, str) else None
            status = "ready" if loaded_version == required_version else "version_mismatch"
        except Exception as exc:  # import failures include binary-loader OSError/RuntimeError
            status = "import_failed"
            import_error = type(exc).__name__
    return {
        "checked": True,
        "ok": status == "ready",
        "status": status,
        "installed_version": installed_version,
        "loaded_version": loaded_version,
        "required_version": required_version,
        "version": installed_version,
        "import_error_type": import_error,
    }


def _iztro_runtime_check(
    node_path: str | None, node_ok: bool, expected_version: str | None
) -> dict[str, Any]:
    package_json = ROOT_DIR / "node_modules" / "iztro" / "package.json"
    metadata, metadata_error = _read_small_json_object(package_json)
    installed_name = metadata.get("name") if metadata else None
    installed_version = metadata.get("version") if metadata else None
    metadata_ok = (
        installed_name == "iztro"
        and isinstance(installed_version, str)
        and expected_version is not None
        and installed_version == expected_version
    )

    if metadata_error:
        status = metadata_error
    elif installed_name != "iztro":
        status = "name_mismatch"
    elif expected_version is None:
        status = "pinned_version_unavailable"
    elif installed_version != expected_version:
        status = "version_mismatch"
    elif not node_ok or node_path is None:
        status = "node_unavailable"
    else:
        status = "require_failed"

    load_ok = False
    if metadata_ok and node_ok and node_path:
        try:
            process = subprocess.run(
                [node_path, "-e", "require('iztro')"],
                cwd=ROOT_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                env=_node_child_env(),
            )
            load_ok = process.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            load_ok = False
        if load_ok:
            status = "ready"

    return {
        "checked": True,
        "ok": metadata_ok and load_ok,
        "status": status,
        "expected_name": "iztro",
        "expected_version": expected_version,
        "installed_name": installed_name if isinstance(installed_name, str) else None,
        "installed_version": installed_version if isinstance(installed_version, str) else None,
        "version": installed_version if isinstance(installed_version, str) else None,
        "metadata_ok": metadata_ok,
        "load_ok": load_ok,
        "path": str(package_json),
    }


def base_result(
    kind: str, *, version_snapshot: dict[str, str | None] | None = None
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "type": kind,
        "engine_versions": version_snapshot or engine_versions(),
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
  destiny doctor [--core|--research|--all] [--json]
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


def doctor_report(mode: str = "all") -> dict[str, Any]:
    if mode not in {"core", "research", "all"}:
        raise ValueError(f"unsupported doctor mode: {mode}")

    research_runtime_checked = mode == "research"
    versions = engine_versions(include_research=research_runtime_checked)
    python_ok = sys.version_info >= (3, 10)
    all_engines_checked = mode == "all"
    node_path = shutil.which("node") if all_engines_checked else None
    npm_path = shutil.which("npm") if all_engines_checked else None
    node_version = None
    node_ok = False
    if all_engines_checked and node_path:
        try:
            process = subprocess.run(
                [node_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env=_node_child_env(),
            )
            node_version = process.stdout.strip().lstrip("v")
            node_ok = process.returncode == 0 and int(node_version.split(".", 1)[0]) >= 18
        except (OSError, ValueError, subprocess.TimeoutExpired):
            node_ok = False
    if all_engines_checked:
        iztro_check = _iztro_runtime_check(node_path, node_ok, _expected_iztro_version())
        node_check = {
            "checked": True,
            "ok": node_ok,
            "status": "ready" if node_ok else "unavailable",
            "path": node_path,
            "version": node_version,
            "required": ">=18",
        }
        npm_check = {
            "checked": True,
            "ok": bool(npm_path),
            "status": "available" if npm_path else "unavailable",
            "path": npm_path,
        }
    else:
        node_check = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "path": None,
            "version": None,
            "required": ">=18",
        }
        npm_check = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "path": None,
        }
        iztro_check = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "expected_name": "iztro",
            "expected_version": versions.get("iztro"),
            "installed_name": None,
            "installed_version": None,
            "version": None,
            "metadata_ok": None,
            "load_ok": None,
            "path": None,
        }
    if research_runtime_checked:
        numpy_check = _module_runtime_check(
            "numpy",
            versions.get("numpy"),
            _expected_numpy_version(),
        )
        skyfield_check = _module_runtime_check(
            "skyfield",
            versions.get("skyfield"),
            "1.55",
        )
        skyfield_check.update(
            {
                "needed_for": "optional historical astronomy research runtime",
                "kernel_required_for_this_check": False,
            }
        )
    else:
        numpy_check = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "installed_version": None,
            "loaded_version": None,
            "required_version": _expected_numpy_version(),
            "version": None,
            "import_error_type": None,
        }
        skyfield_check = {
            "checked": False,
            "ok": None,
            "status": "not_checked",
            "installed_version": None,
            "loaded_version": None,
            "required_version": "1.55",
            "version": None,
            "import_error_type": None,
            "needed_for": "optional historical astronomy research runtime",
            "kernel_required_for_this_check": False,
        }
    checks = {
        "python": {
            "ok": python_ok,
            "version": ".".join(map(str, sys.version_info[:3])),
            "required": ">=3.10",
        },
        "lunar_python": {
            "ok": versions["lunar_python"] is not None,
            "version": versions["lunar_python"],
        },
        "tzdata": {
            "ok": versions["tzdata"] == "2026.3",
            "version": versions["tzdata"],
            "required": "2026.3",
        },
        "httpx": {
            "ok": llm_provider.HAS_HTTPX,
            "version": versions["httpx"],
            "needed_for": "optional --llm only",
        },
        "skyfield": skyfield_check,
        "numpy": numpy_check,
        "node": node_check,
        "npm": npm_check,
        "iztro": iztro_check,
    }
    ready_core = checks["python"]["ok"] and checks["lunar_python"]["ok"] and checks["tzdata"]["ok"]
    ready_research = bool(
        research_runtime_checked
        and ready_core
        and checks["skyfield"]["ok"]
        and checks["numpy"]["ok"]
    )
    ready_all = bool(
        all_engines_checked and ready_core and checks["node"]["ok"] and checks["iztro"]["ok"]
    )
    readiness = {
        "core": ready_core,
        "research": ready_research,
        "all": ready_all,
    }
    return {
        **base_result("doctor", version_snapshot=versions),
        "selected_mode": mode,
        "selected_mode_ready": readiness[mode],
        "ready_core": ready_core,
        "ready_research": ready_research,
        "ready_all_engines": ready_all,
        "all_engines_checked": all_engines_checked,
        "research_runtime_checked": research_runtime_checked,
        "readiness": readiness,
        "research_data": {
            "checked": False,
            "ready": None,
            "reason": "JPL kernel availability is command-specific and is not checked by doctor.",
        },
        "checks": checks,
    }
