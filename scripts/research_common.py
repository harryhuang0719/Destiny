"""Shared validation, time, path, hashing, and atomic-I/O primitives."""

from __future__ import annotations

import errno
import hashlib
import math
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ASTRO_SCHEMA_VERSION = "1.0.0"
RESEARCH_SCHEMA_VERSION = "1.0.0"
STRICT_UTC_START = datetime(1972, 1, 1, tzinfo=timezone.utc)
MAX_RESEARCH_ROWS = 250_000
MAX_CONFIG_BYTES = 2 * 1024 * 1024
MAX_RESEARCH_FILE_BYTES = 512 * 1024 * 1024
MAX_KERNEL_BYTES = 4 * 1024 * 1024 * 1024
MAX_MATRIX_CELLS = 5_000_000
MAX_BUILD_CELLS = 5_000_000
MAX_PLACEBO_OPERATIONS = 50_000_000


class ResearchError(ValueError):
    """Stable, user-facing validation failure."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_output_path(path: str | Path, label: str = "output") -> Path:
    """Return an absolute leaf path without following a pre-existing symlink."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.absolute()
    if candidate.is_symlink():
        raise ResearchError(f"{label} 不能是符号链接: {candidate}")
    return candidate.parent.resolve(strict=False) / candidate.name


def ensure_distinct_paths(paths: dict[str, str | Path]) -> None:
    seen: dict[Path, str] = {}
    existing: list[tuple[Path, str]] = []
    for label, raw_path in paths.items():
        candidate = Path(raw_path).expanduser().resolve(strict=False)
        previous = seen.get(candidate)
        if previous is not None:
            raise ResearchError(f"路径冲突: {label} 与 {previous} 指向同一文件 {candidate}")
        if candidate.exists():
            for prior_path, prior_label in existing:
                try:
                    if os.path.samefile(candidate, prior_path):
                        raise ResearchError(
                            f"路径冲突: {label} 与 {prior_label} 是同一 inode/file identity"
                        )
                except OSError as exc:
                    raise ResearchError(f"无法比较路径 identity: {candidate}: {exc}") from exc
            existing.append((candidate, label))
        seen[candidate] = label


def input_file_path(
    path: str | Path,
    label: str,
    max_bytes: int = MAX_RESEARCH_FILE_BYTES,
) -> Path:
    candidate = Path(path).expanduser().resolve()
    try:
        if not candidate.is_file():
            raise ResearchError(f"{label} 不存在或不是文件: {candidate}")
        if candidate.stat().st_size > max_bytes:
            raise ResearchError(f"{label} 超过 {max_bytes:,} bytes 安全上限")
    except OSError as exc:
        raise ResearchError(f"无法检查 {label}: {candidate}: {exc}") from exc
    return candidate


def snapshot_input_files(
    paths: dict[str, Path],
) -> tuple[tempfile.TemporaryDirectory[str], dict[str, Path], dict[str, str]]:
    """Copy and hash each input from one stable file descriptor before parsing."""
    snapshot_dir = tempfile.TemporaryDirectory(prefix="destiny-research-inputs-")
    snapshots: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    try:
        for label, source_path in paths.items():
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(source_path, flags)
            digest = hashlib.sha256()
            snapshot = Path(snapshot_dir.name) / f"{label}{source_path.suffix}"
            with os.fdopen(descriptor, "rb") as source, snapshot.open("wb") as destination:
                source_stat = os.fstat(source.fileno())
                if not stat.S_ISREG(source_stat.st_mode):
                    raise ResearchError(f"{label} 必须是普通文件: {source_path}")
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            snapshots[label] = snapshot
            hashes[label] = digest.hexdigest()
    except ResearchError:
        snapshot_dir.cleanup()
        raise
    except OSError as exc:
        snapshot_dir.cleanup()
        raise ResearchError(f"无法创建稳定输入快照: {exc}") from exc
    return snapshot_dir, snapshots, hashes


def parse_utc(value: str, *, allow_pre_utc: bool = False) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to aware UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ResearchError("时间必须是非空 ISO-8601 字符串")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ResearchError(f"无效 ISO-8601 时间: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchError(f"时间必须带 UTC offset，不能是 naive datetime: {value}")
    normalized = parsed.astimezone(timezone.utc)
    if normalized < STRICT_UTC_START and not allow_pre_utc:
        raise ResearchError(
            "1972 年前不能默认声称严格 UTC；如仅做回溯描述，请显式启用 allow_pre_utc 并保留政策标记"
        )
    return normalized


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchError("datetime 必须带 UTC offset，不能依赖主机本地时区")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def signed_angle_deg(a: float, b: float) -> float:
    """Shortest signed circular difference ``a-b`` in [-180, 180)."""
    if not math.isfinite(a) or not math.isfinite(b):
        raise ResearchError("circular angles 必须是有限数值")
    angle = math.degrees(
        math.atan2(
            math.sin(math.radians(a - b)),
            math.cos(math.radians(a - b)),
        )
    )
    return -180.0 if math.isclose(angle, 180.0, abs_tol=1e-12) else angle


def minimum_angle_deg(a: float, b: float) -> float:
    return abs(signed_angle_deg(a, b))


def _commit_temp_file(temp_path: Path, path: Path, *, overwrite: bool) -> None:
    """Commit a same-directory temp file without a check-then-replace race."""
    try:
        if overwrite:
            os.replace(temp_path, path)
            return
        try:
            os.link(temp_path, path)
        except FileExistsError as exc:
            raise ResearchError(f"输出已存在；如确认覆盖请加 --overwrite: {path}") from exc
        except OSError as exc:
            if exc.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP}:
                raise ResearchError(f"无法原子创建输出 {path}: {exc}") from exc
            try:
                with temp_path.open("rb") as source, path.open("xb") as destination:
                    shutil.copyfileobj(source, destination)
            except FileExistsError as collision:
                raise ResearchError(
                    f"输出已存在；如确认覆盖请加 --overwrite: {path}"
                ) from collision
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write_text(path: Path, text: str, *, overwrite: bool = False) -> None:
    path = safe_output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    _commit_temp_file(temp_path, path, overwrite=overwrite)
