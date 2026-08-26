"""Git provenance and append-only research trial registry support."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__:  # package import
    from .research_common import ResearchError, safe_output_path
else:  # direct scripts import
    from research_common import ResearchError, safe_output_path


def _git_command(arguments: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        git_path = shutil.which("git", path=os.environ.get("PATH", ""))
        if not git_path:
            return None
        return subprocess.run(
            [git_path, *arguments],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": os.environ.get("PATH", "")},
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git_state() -> dict[str, Any]:
    head = _git_command(["rev-parse", "HEAD"])
    status = _git_command(["status", "--porcelain", "--untracked-files=all"])
    return {
        "commit": head.stdout.strip() if head and head.returncode == 0 else None,
        "dirty": None if status is None or status.returncode != 0 else bool(status.stdout.strip()),
    }


def _git_is_ancestor(commit: str) -> bool:
    process = _git_command(["merge-base", "--is-ancestor", commit, "HEAD"])
    return process is not None and process.returncode == 0


def code_source_sha256() -> str:
    digest = hashlib.sha256()
    source_root = Path(__file__).resolve().parent
    for path in sorted([*source_root.glob("*.py"), *source_root.glob("*.cjs")]):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def append_trial_registry(
    path: str | Path,
    entry: dict[str, Any],
    *,
    protected_paths: Iterable[str | Path] = (),
) -> None:
    registry = safe_output_path(path, "trial registry")
    registry.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(registry, flags, 0o600)
    except OSError as exc:
        raise ResearchError(f"无法安全打开 trial registry {registry}: {exc}") from exc
    try:
        registry_stat = os.fstat(descriptor)
        if not stat.S_ISREG(registry_stat.st_mode):
            raise ResearchError(f"trial registry 必须是普通文件: {registry}")
        for protected in protected_paths:
            try:
                protected_stat = os.stat(protected, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if (registry_stat.st_dev, registry_stat.st_ino) == (
                protected_stat.st_dev,
                protected_stat.st_ino,
            ):
                raise ResearchError(f"trial registry 与受保护输入是同一 file identity: {protected}")
        view = memoryview(line)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
