#!/usr/bin/env python3
"""Create an isolated Destiny environment and verify every requested layer."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _run(command: list[str], *, cwd: Path = ROOT) -> None:
    if sys.platform == "win32" and Path(command[0]).suffix.lower() in (".cmd", ".bat"):
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    process = subprocess.run(command, cwd=cwd)
    if process.returncode != 0:
        raise SystemExit(process.returncode)


def _node_major(node_path: str) -> int:
    process = subprocess.run(
        [node_path, "--version"], capture_output=True, text=True, check=False, timeout=10
    )
    if process.returncode != 0:
        raise SystemExit("Unable to query Node.js version")
    try:
        return int(process.stdout.strip().lstrip("v").split(".", 1)[0])
    except ValueError as exc:
        raise SystemExit(f"Unexpected Node.js version: {process.stdout.strip()}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Destiny in an isolated virtualenv")
    parser.add_argument("--venv", default=str(ROOT / ".venv"), help="virtualenv path")
    parser.add_argument("--llm", action="store_true", help="install optional httpx LLM adapter")
    parser.add_argument("--research", action="store_true", help="install Skyfield research extra")
    parser.add_argument("--dev", action="store_true", help="install pytest")
    parser.add_argument(
        "--skip-node", action="store_true", help="skip npm ci (Ziwei will remain unavailable)"
    )
    args = parser.parse_args(argv)

    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    venv_dir = Path(args.venv).expanduser().resolve()
    if not _venv_python(venv_dir).exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = _venv_python(venv_dir)
    # venv bundles whatever pip shipped with the host Python; pin a version that
    # includes the current 2026 installer security fixes before installing code.
    _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--upgrade",
            "pip==26.2",
        ]
    )

    extras = []
    if args.llm:
        extras.append("llm")
    if args.research:
        extras.append("research")
    if args.dev:
        extras.append("dev")
    project_spec = str(ROOT) + (f"[{','.join(extras)}]" if extras else "")
    _run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", project_spec])

    node_installed = False
    if not args.skip_node:
        npm = shutil.which("npm")
        node = shutil.which("node")
        if not npm or not node:
            parser.error("node/npm not found; install Node.js >=18 or use --skip-node")
        if _node_major(node) < 18:
            parser.error("Node.js 18 or newer is required for Zi Wei")
        _run([npm, "ci", "--ignore-scripts"])
        _run([npm, "test"])
        node_installed = True

    _run([str(python), "-m", "py_compile", *map(str, sorted((ROOT / "scripts").glob("*.py")))])
    if args.dev:
        _run([str(python), "-m", "ruff", "check", "scripts", "tests"])
        _run([str(python), "-m", "ruff", "format", "--check", "scripts", "tests"])
        _run([str(python), "-m", "pytest", "-q"])
    if args.research:
        _run([str(python), "-c", "import skyfield; print('Skyfield', skyfield.__version__)"])

    summary = {
        "status": "ok",
        "root": str(ROOT),
        "venv": str(venv_dir),
        "python": str(python),
        "extras": extras,
        "node_runtime_installed": node_installed,
        "next": f"{python} {ROOT / 'scripts/destiny_analyzer.py'} doctor --json",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
