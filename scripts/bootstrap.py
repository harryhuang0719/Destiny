#!/usr/bin/env python3
"""Create an isolated Destiny environment and verify every requested layer."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


Installer = Literal["uv", "pip"]

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
_INSTALLER_ENV_KEYS = _NODE_ENV_KEYS | frozenset(
    {
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "PIP_CACHE_DIR",
        "PIP_CERT",
        "PIP_DEFAULT_TIMEOUT",
        "PIP_DISABLE_PIP_VERSION_CHECK",
        "PIP_NO_CACHE_DIR",
        "PIP_NO_INPUT",
        "PIP_PROGRESS_BAR",
        "PIP_PROXY",
        "PIP_RETRIES",
        "PIP_TIMEOUT",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TZ",
        "USER",
        "USERNAME",
        "UV_CACHE_DIR",
        "UV_CONCURRENT_BUILDS",
        "UV_CONCURRENT_DOWNLOADS",
        "UV_CONCURRENT_INSTALLS",
        "UV_HTTP_RETRIES",
        "UV_HTTP_TIMEOUT",
        "UV_LINK_MODE",
        "UV_NATIVE_TLS",
        "UV_NO_CACHE",
        "UV_NO_PROGRESS",
        "UV_OFFLINE",
        "UV_PYTHON_DOWNLOADS",
        "UV_SYSTEM_CERTS",
    }
)
_PRIVATE_INDEX_ENV_KEYS = frozenset(
    {
        "PIP_CLIENT_CERT",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_INDEX_URL",
        "PIP_KEYRING_PROVIDER",
        "PIP_NO_INDEX",
        "PIP_TRUSTED_HOST",
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_FIND_LINKS",
        "UV_INDEX",
        "UV_INDEX_STRATEGY",
        "UV_INDEX_URL",
        "UV_KEYRING_PROVIDER",
        "UV_NO_INDEX",
    }
)
_UV_NAMED_INDEX_CREDENTIAL = re.compile(r"^UV_INDEX_[A-Z0-9][A-Z0-9_]*_(?:USERNAME|PASSWORD)$")


def _node_child_env() -> dict[str, str]:
    """Return the small OS-only environment permitted for Node/npm children."""
    return {key: value for key, value in os.environ.items() if key.upper() in _NODE_ENV_KEYS}


def _installer_env(allow_private_index_env: bool = False, **overrides: str) -> dict[str, str]:
    """Build an exact installer allowlist, with private indexes opt-in only."""
    allowed = set(_INSTALLER_ENV_KEYS)
    if allow_private_index_env:
        allowed.update(_PRIVATE_INDEX_ENV_KEYS)
    clean = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
        or (
            allow_private_index_env
            and _UV_NAMED_INDEX_CREDENTIAL.fullmatch(key.upper()) is not None
        )
    }
    clean.update(overrides)
    return clean


def _display_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
) -> None:
    child_env = _installer_env() if env is None else env
    if sys.platform == "win32" and Path(command[0]).suffix.lower() in (".cmd", ".bat"):
        command = [
            child_env.get("COMSPEC", os.environ.get("COMSPEC", "cmd.exe")),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    try:
        process = subprocess.run(
            command,
            cwd=cwd,
            env=child_env,
            timeout=timeout,
            stdout=sys.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        limit = f" after {timeout:g}s" if timeout is not None else ""
        raise SystemExit(f"Command timed out{limit}: {command[0]}") from exc
    if process.returncode != 0:
        raise SystemExit(process.returncode)


def _node_major(node_path: str, *, env: dict[str, str] | None = None) -> int:
    process = subprocess.run(
        [node_path, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env=_node_child_env() if env is None else env,
    )
    if process.returncode != 0:
        raise SystemExit("Unable to query Node.js version")
    try:
        return int(process.stdout.strip().lstrip("v").split(".", 1)[0])
    except ValueError as exc:
        raise SystemExit(f"Unexpected Node.js version: {process.stdout.strip()}") from exc


def _uv_lock_is_current(
    uv_path: str, *, allow_private_index_env: bool = False
) -> tuple[bool, str | None]:
    lock_path = ROOT / "uv.lock"
    if not lock_path.is_file():
        return False, f"lockfile not found: {lock_path}"
    try:
        process = subprocess.run(
            [uv_path, "lock", "--check", "--project", str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=_installer_env(allow_private_index_env),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if process.returncode == 0:
        return True, None
    detail = process.stderr.strip() or process.stdout.strip() or f"exit code {process.returncode}"
    return False, detail


def _select_installer(
    requested: str, *, allow_private_index_env: bool = False
) -> tuple[Installer, str | None, str | None]:
    if requested == "pip":
        return "pip", None, None

    uv_path = shutil.which("uv")
    if not uv_path:
        message = "uv executable was not found"
        if requested == "uv":
            raise ValueError(message)
        return "pip", None, message

    lock_current, detail = _uv_lock_is_current(
        uv_path, allow_private_index_env=allow_private_index_env
    )
    if not lock_current:
        message = f"uv.lock is missing or stale: {detail}"
        if requested == "uv":
            raise ValueError(message)
        return "pip", None, message
    return "uv", uv_path, None


def _uv_sync_command(uv_path: str, extras: list[str]) -> list[str]:
    command = [
        uv_path,
        "sync",
        "--frozen",
        "--active",
        "--project",
        str(ROOT),
        "--no-default-groups",
    ]
    for extra in extras:
        command.extend(["--extra", extra])
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Destiny in an isolated virtualenv")
    parser.add_argument("--venv", default=str(ROOT / ".venv"), help="virtualenv path")
    parser.add_argument("--llm", action="store_true", help="install optional httpx LLM adapter")
    parser.add_argument("--research", action="store_true", help="install Skyfield research extra")
    parser.add_argument("--dev", action="store_true", help="install pytest")
    parser.add_argument(
        "--installer",
        choices=("auto", "uv", "pip"),
        default="auto",
        help="Python installer (default: auto; uv requires a current uv.lock)",
    )
    parser.add_argument(
        "--allow-private-index-env",
        action="store_true",
        help="forward only recognized pip/uv private-index environment variables",
    )
    parser.add_argument(
        "--skip-node",
        action="store_true",
        help="skip npm install and Node runtime verification; existing node_modules is left untouched",
    )
    args = parser.parse_args(argv)

    if sys.version_info < (3, 10):
        parser.error("Python 3.10 or newer is required")
    venv_dir = Path(args.venv).expanduser().resolve()
    if not _venv_python(venv_dir).exists():
        venv.EnvBuilder(
            with_pip=False,
            symlinks=sys.platform != "win32",
        ).create(venv_dir)
        _run(
            [
                str(_venv_python(venv_dir)),
                "-m",
                "ensurepip",
                "--upgrade",
                "--default-pip",
            ],
            env=_installer_env(args.allow_private_index_env),
        )
    python = _venv_python(venv_dir)

    extras = []
    if args.llm:
        extras.append("llm")
    if args.research:
        extras.append("research")
    if args.dev:
        extras.append("dev")
    try:
        installer, uv_path, fallback_reason = _select_installer(
            args.installer,
            allow_private_index_env=args.allow_private_index_env,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if fallback_reason:
        print(f"bootstrap: {fallback_reason}; falling back to pip", file=sys.stderr)

    if installer == "uv":
        assert uv_path is not None
        uv_env = _installer_env(
            args.allow_private_index_env,
            VIRTUAL_ENV=str(venv_dir),
        )
        _run(_uv_sync_command(uv_path, extras), env=uv_env)
    else:
        # venv bundles whatever pip shipped with the host Python; pin a version that
        # includes the current 2026 installer security fixes before installing code.
        pip_env = _installer_env(args.allow_private_index_env)
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--upgrade",
                "pip==26.2",
            ],
            env=pip_env,
        )
        project_spec = str(ROOT) + (f"[{','.join(extras)}]" if extras else "")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-e",
                project_spec,
            ],
            env=pip_env,
        )

    node_installed = False
    if not args.skip_node:
        npm = shutil.which("npm")
        node = shutil.which("node")
        if not npm or not node:
            parser.error("node/npm not found; install Node.js >=18 or use --skip-node")
        node_env = _node_child_env()
        if _node_major(node, env=node_env) < 18:
            parser.error("Node.js 18 or newer is required for Zi Wei")
        _run([npm, "ci", "--ignore-scripts"], env=node_env)
        _run([node, "-e", "require('iztro')"], env=node_env, timeout=10)
        node_installed = True

    _run([str(python), "-m", "py_compile", *map(str, sorted((ROOT / "scripts").glob("*.py")))])
    if args.dev:
        _run([str(python), "-m", "ruff", "check", "scripts", "tests"])
        _run([str(python), "-m", "ruff", "format", "--check", "scripts", "tests"])
        _run([str(python), "-m", "pytest", "-q"])
    if args.research:
        _run([str(python), "-c", "import skyfield; print('Skyfield', skyfield.__version__)"])

    doctor_profile = "all" if node_installed else "research" if args.research else "core"
    next_argv = [
        str(python),
        str(ROOT / "scripts/destiny_analyzer.py"),
        "doctor",
        f"--{doctor_profile}",
        "--json",
    ]
    summary = {
        "status": "ok",
        "root": str(ROOT),
        "venv": str(venv_dir),
        "python": str(python),
        "installer": installer,
        "installer_requested": args.installer,
        "allow_private_index_env": args.allow_private_index_env,
        "extras": extras,
        "node_runtime_installed": node_installed,
        "next_argv": next_argv,
        "next": _display_command(next_argv),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
