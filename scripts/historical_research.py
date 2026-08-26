#!/usr/bin/env python3
"""Auditable historical astronomy queries and point-in-time market research.

This module intentionally separates deterministic ephemeris features from the
financial target supplied by the researcher. It does not download market data,
does not select a winning feature, and never labels retrospective results as a
sealed out-of-sample discovery.
"""

from __future__ import annotations

import csv
import errno
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import random
import re
import shutil
import stat
import statistics
import subprocess
import tempfile
import uuid
from bisect import bisect_right
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

ASTRO_SCHEMA_VERSION = "1.0.0"
RESEARCH_SCHEMA_VERSION = "1.0.0"
STRICT_UTC_START = datetime(1972, 1, 1, tzinfo=timezone.utc)
DEFAULT_BODIES = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
)
BODY_ORDER = {body: index for index, body in enumerate(DEFAULT_BODIES)}
DEFAULT_PAIRS = (
    ("jupiter", "saturn"),
    ("mars", "saturn"),
    ("mars", "jupiter"),
    ("sun", "jupiter"),
    ("sun", "saturn"),
    ("venus", "jupiter"),
    ("mercury", "jupiter"),
)
BODY_TARGETS = {
    "sun": ("sun",),
    "moon": ("moon",),
    "mercury": ("mercury", "mercury barycenter"),
    "venus": ("venus", "venus barycenter"),
    "mars": ("mars", "mars barycenter"),
    "jupiter": ("jupiter barycenter", "jupiter"),
    "saturn": ("saturn barycenter", "saturn"),
    "uranus": ("uranus barycenter", "uranus"),
    "neptune": ("neptune barycenter", "neptune"),
    "pluto": ("pluto barycenter", "pluto"),
}
ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}
CATALOG_REQUIRED = {
    "series_id",
    "vendor",
    "source",
    "source_vintage",
    "instrument_type",
    "currency",
    "venue",
    "exchange_timezone",
    "calendar",
    "price_type",
    "target_kind",
    "tradable",
    "methodology_version",
    "periods_per_year",
    "overlapping_targets",
}
TARGET_REQUIRED = {
    "observation_time_utc",
    "available_at_utc",
    "decision_at_utc",
    "execution_at_utc",
    "target_start_utc",
    "target_end_utc",
}
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


def input_file_path(path: str | Path, label: str, max_bytes: int = MAX_RESEARCH_FILE_BYTES) -> Path:
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


def canonical_pair(first: str, second: str) -> tuple[str, str]:
    first, second = first.lower(), second.lower()
    if first == second:
        raise ResearchError("pair 两端不能是同一天体")
    if first not in BODY_ORDER or second not in BODY_ORDER:
        raise ResearchError(f"未知 pair: {first}-{second}")
    return (first, second) if BODY_ORDER[first] < BODY_ORDER[second] else (second, first)


def aspect_score(separation_deg: float, exact_deg: float, sigma_deg: float = 3.0) -> float:
    if not math.isfinite(separation_deg) or not math.isfinite(exact_deg):
        raise ResearchError("aspect angles 必须是有限数值")
    if not math.isfinite(sigma_deg) or not 0 < sigma_deg <= 180:
        raise ResearchError("aspect sigma 必须是 0-180 之间的有限数值")
    distance = separation_deg - exact_deg
    return math.exp(-(distance * distance) / (2.0 * sigma_deg * sigma_deg))


class SkyfieldEphemeris:
    """JPL SPK-backed geocentric apparent positions using Skyfield.

    The kernel must already exist on disk. Refusing implicit downloads makes the
    exact file hash part of every result and keeps CI/network behavior explicit.
    """

    def __init__(self, kernel_path: str | Path):
        self.kernel_path = input_file_path(kernel_path, "JPL kernel", MAX_KERNEL_BYTES)
        try:
            from skyfield.api import load, load_file
        except ImportError as exc:
            raise ResearchError(
                "历史天文查询需要可选依赖 skyfield；运行 bootstrap --research"
            ) from exc
        self._load = load
        self._snapshot_dir = None
        try:
            snapshot_dir, snapshots, hashes = snapshot_input_files({"kernel": self.kernel_path})
            self._snapshot_dir = snapshot_dir
            self.kernel_sha256 = hashes["kernel"]
            self.ephemeris = load_file(str(snapshots["kernel"]))
            self.timescale = load.timescale(builtin=True)
            self.earth = self.ephemeris["earth"]
        except Exception as exc:
            if self._snapshot_dir is not None:
                self._snapshot_dir.cleanup()
            raise ResearchError(f"无法载入 JPL kernel: {exc}") from exc

    def close(self) -> None:
        ephemeris = getattr(self, "ephemeris", None)
        if ephemeris is not None:
            ephemeris.close()
            self.ephemeris = None
        snapshot_dir = getattr(self, "_snapshot_dir", None)
        if snapshot_dir is not None:
            snapshot_dir.cleanup()
            self._snapshot_dir = None

    def __del__(self):
        with suppress(Exception):
            self.close()

    def _target(self, body: str):
        normalized = body.lower()
        if normalized not in BODY_TARGETS:
            raise ResearchError(f"不支持的天体: {body}")
        errors = []
        for candidate in BODY_TARGETS[normalized]:
            try:
                return self.ephemeris[candidate], candidate
            except Exception as exc:
                errors.append(str(exc))
        raise ResearchError(f"kernel 不含 {body}: {'; '.join(errors)}")

    def _time(self, at_utc: datetime):
        if at_utc.tzinfo is None or at_utc.utcoffset() is None:
            raise ResearchError("JPL 查询 datetime 必须带 UTC offset")
        return self.timescale.from_datetime(at_utc.astimezone(timezone.utc))

    def _longitude(self, target, at_utc: datetime) -> float:
        apparent = self.earth.at(self._time(at_utc)).observe(target).apparent()
        _lat, lon, _distance = apparent.ecliptic_latlon(epoch="date")
        return float(lon.degrees) % 360.0

    def body_state(self, body: str, at_utc: datetime) -> dict[str, Any]:
        target, target_label = self._target(body)
        time = self._time(at_utc)
        apparent = self.earth.at(time).observe(target).apparent()
        lat, lon, distance = apparent.ecliptic_latlon(epoch="date")
        ra, dec, _ = apparent.radec(epoch="date")
        half_window = timedelta(minutes=30)
        lon_before = self._longitude(target, at_utc - half_window)
        lon_after = self._longitude(target, at_utc + half_window)
        velocity = signed_angle_deg(lon_after, lon_before) * 24.0
        state: dict[str, Any] = {
            "target_label": target_label,
            "target_naif_id": int(getattr(target, "target", -1)),
            "observer_naif_id": int(getattr(self.earth, "target", 399)),
            "longitude_deg": float(lon.degrees) % 360.0,
            "latitude_deg": float(lat.degrees),
            "distance_au": float(distance.au),
            "longitude_velocity_deg_day": velocity,
            "retrograde": velocity < 0,
            "right_ascension_hours": float(ra.hours),
            "declination_deg": float(dec.degrees),
        }
        if body.lower() == "moon":
            state["illuminated_fraction"] = float(
                apparent.fraction_illuminated(self.ephemeris["sun"])
            )
        for key, value in state.items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ResearchError(f"JPL state {body}.{key} 不是有限数值")
        return state

    def state(
        self,
        at_utc: datetime,
        bodies: Iterable[str] = DEFAULT_BODIES,
        *,
        allow_pre_utc: bool = False,
    ) -> dict[str, Any]:
        at_utc = parse_utc(iso_utc(at_utc), allow_pre_utc=allow_pre_utc)
        time = self._time(at_utc)
        body_names = tuple(dict.fromkeys(body.lower() for body in bodies))
        body_states = {body: self.body_state(body, at_utc) for body in body_names}
        return {
            "schema_version": ASTRO_SCHEMA_VERSION,
            "timestamp_utc": iso_utc(at_utc),
            "time_scales": {
                "jd_tt": float(time.tt),
                "jd_tdb": float(time.tdb),
                "jd_ut1": float(time.ut1),
                "pre_utc_policy": (
                    "proleptic UTC label; astronomy computed on TT/TDB/UT1"
                    if at_utc < STRICT_UTC_START
                    else "strict UTC join label"
                ),
            },
            "frame": {
                "origin": "geocentric",
                "position": "apparent",
                "ecliptic": "of-date",
                "radec_epoch": "of-date",
            },
            "kernel": {
                "path": str(self.kernel_path),
                "sha256": self.kernel_sha256,
            },
            "bodies": body_states,
        }


def features_from_state(
    state: dict[str, Any],
    pairs: Iterable[tuple[str, str]] = DEFAULT_PAIRS,
    *,
    harmonics: int = 2,
    aspect_sigma_deg: float = 3.0,
) -> dict[str, float | int | str]:
    if harmonics < 1 or harmonics > 6:
        raise ResearchError("harmonics 必须在 1-6 之间，并应在查看 OOS 前预注册")
    output: dict[str, float | int | str] = {"timestamp_utc": state["timestamp_utc"]}
    bodies = state["bodies"]
    for body, values in bodies.items():
        lon = float(values["longitude_deg"])
        if not math.isfinite(lon):
            raise ResearchError(f"{body} longitude 不是有限数值")
        output[f"{body}_longitude_deg"] = lon
        output[f"{body}_longitude_sin"] = math.sin(math.radians(lon))
        output[f"{body}_longitude_cos"] = math.cos(math.radians(lon))
        output[f"{body}_latitude_deg"] = float(values["latitude_deg"])
        output[f"{body}_distance_au"] = float(values["distance_au"])
        output[f"{body}_longitude_velocity_deg_day"] = float(values["longitude_velocity_deg_day"])
        output[f"{body}_retrograde"] = int(bool(values["retrograde"]))

    if "moon" in bodies and "sun" in bodies:
        phase = (bodies["moon"]["longitude_deg"] - bodies["sun"]["longitude_deg"]) % 360
        output["moon_phase_deg"] = float(phase)
        output["moon_phase_sin"] = math.sin(math.radians(phase))
        output["moon_phase_cos"] = math.cos(math.radians(phase))
        output["moon_phase_illumination_proxy"] = (1.0 - math.cos(math.radians(phase))) / 2.0
        if "illuminated_fraction" in bodies["moon"]:
            output["moon_illuminated_fraction"] = float(bodies["moon"]["illuminated_fraction"])

    seen_pairs: set[tuple[str, str]] = set()
    for first, second in pairs:
        first, second = canonical_pair(first, second)
        if (first, second) in seen_pairs:
            raise ResearchError(f"重复 pair: {first}-{second}")
        seen_pairs.add((first, second))
        if first not in bodies or second not in bodies:
            raise ResearchError(f"pair {first}-{second} 的天体未包含在 state 中")
        prefix = f"{first}_{second}"
        signed = signed_angle_deg(
            float(bodies[first]["longitude_deg"]),
            float(bodies[second]["longitude_deg"]),
        )
        separation = abs(signed)
        output[f"{prefix}_signed_angle_deg"] = signed
        output[f"{prefix}_separation_deg"] = separation
        output[f"{prefix}_relative_velocity_deg_day"] = float(
            bodies[first]["longitude_velocity_deg_day"]
        ) - float(bodies[second]["longitude_velocity_deg_day"])
        for harmonic in range(1, harmonics + 1):
            angle = math.radians(harmonic * signed)
            output[f"{prefix}_h{harmonic}_sin"] = math.sin(angle)
            output[f"{prefix}_h{harmonic}_cos"] = math.cos(angle)
        for aspect_name, exact in ASPECTS.items():
            output[f"{prefix}_{aspect_name}_score"] = aspect_score(
                separation, exact, aspect_sigma_deg
            )
    return output


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


def write_feature_csv(
    backend: SkyfieldEphemeris,
    start_utc: datetime,
    end_utc: datetime,
    output_path: str | Path,
    *,
    step_hours: int = 24,
    bodies: Iterable[str] = DEFAULT_BODIES,
    pairs: Iterable[tuple[str, str]] = DEFAULT_PAIRS,
    harmonics: int = 2,
    aspect_sigma_deg: float = 3.0,
    allow_pre_utc: bool = False,
    overwrite: bool = False,
    max_rows: int = 100_000,
) -> dict[str, Any]:
    if step_hours <= 0:
        raise ResearchError("step_hours 必须大于 0")
    if not 1 <= max_rows <= 1_000_000:
        raise ResearchError("max_rows 必须在 1-1,000,000 之间")
    if end_utc < start_utc:
        raise ResearchError("end 必须不早于 start")
    start_utc = parse_utc(iso_utc(start_utc), allow_pre_utc=allow_pre_utc)
    end_utc = parse_utc(iso_utc(end_utc), allow_pre_utc=allow_pre_utc)
    row_count = int((end_utc - start_utc).total_seconds() // (step_hours * 3600)) + 1
    if row_count > max_rows:
        raise ResearchError(f"请求 {row_count:,} 行，超过安全上限 {max_rows:,}")
    output = safe_output_path(output_path, "feature output")
    manifest_path = safe_output_path(
        output.with_suffix(output.suffix + ".manifest.json"), "manifest output"
    )
    ensure_distinct_paths(
        {
            "JPL kernel": backend.kernel_path,
            "feature output": output,
            "manifest output": manifest_path,
        }
    )
    if not overwrite:
        for candidate in (output, manifest_path):
            if candidate.exists():
                raise ResearchError(f"输出已存在；如确认覆盖请加 --overwrite: {candidate}")

    rows: list[dict[str, Any]] = []
    target_metadata: dict[str, dict[str, Any]] = {}
    current = start_utc
    body_names = tuple(dict.fromkeys(body.lower() for body in bodies))
    pair_names = tuple(canonical_pair(a, b) for a, b in pairs)
    estimated_columns = (
        1
        + 7 * len(body_names)
        + (5 if "moon" in body_names and "sun" in body_names else 0)
        + len(pair_names) * (3 + 2 * harmonics + len(ASPECTS))
    )
    if row_count * estimated_columns > MAX_BUILD_CELLS:
        raise ResearchError(
            f"feature build 超过 {MAX_BUILD_CELLS:,} cells 内存安全上限；缩小范围/天体/pair"
        )
    while current <= end_utc:
        state = backend.state(current, body_names, allow_pre_utc=allow_pre_utc)
        if not target_metadata:
            target_metadata = {
                body: {
                    "target_label": values["target_label"],
                    "target_naif_id": values["target_naif_id"],
                    "observer_naif_id": values["observer_naif_id"],
                }
                for body, values in state["bodies"].items()
            }
        rows.append(
            features_from_state(
                state,
                pair_names,
                harmonics=harmonics,
                aspect_sigma_deg=aspect_sigma_deg,
            )
        )
        current += timedelta(hours=step_hours)

    fieldnames = list(rows[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", newline="", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    feature_hash = sha256_file(temp_path)

    manifest = {
        "schema_version": ASTRO_SCHEMA_VERSION,
        "source_type": "jpl_spk",
        "created_at_utc": iso_utc(datetime.now(timezone.utc)),
        "feature_file": str(output),
        "feature_file_sha256": feature_hash,
        "kernel_path": str(backend.kernel_path),
        "kernel_sha256": backend.kernel_sha256,
        "coordinate_profile": "tropical_geocentric_apparent_of_date_v1",
        "frame": {
            "origin": "geocentric",
            "position": "apparent",
            "ecliptic": "of-date",
            "radec_epoch": "of-date",
        },
        "runtime": {
            "python": platform.python_version(),
            "skyfield": importlib.metadata.version("skyfield"),
            "timescale": "skyfield load.timescale(builtin=True)",
        },
        "start_utc": iso_utc(start_utc),
        "end_utc": iso_utc(end_utc),
        "step_hours": step_hours,
        "rows": len(rows),
        "bodies": list(body_names),
        "body_targets": target_metadata,
        "pairs": [list(pair) for pair in pair_names],
        "harmonics": harmonics,
        "aspect_sigma_deg": aspect_sigma_deg,
        "pre_utc_policy": "explicit-proleptic" if start_utc < STRICT_UTC_START else "strict",
    }
    committed_output = False
    try:
        _commit_temp_file(temp_path, output, overwrite=overwrite)
        committed_output = True
        _atomic_write_text(
            manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            overwrite=overwrite,
        )
    except Exception:
        if (
            committed_output
            and not overwrite
            and output.is_file()
            and sha256_file(output) == feature_hash
        ):
            output.unlink()
        raise
    return manifest


def _load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    source = input_file_path(path, label, MAX_CONFIG_BYTES)
    try:
        data = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ResearchError(f"无法读取 {label}: {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ResearchError(f"{label} 顶层必须是 JSON object")
    return data


def validate_catalog(catalog: dict[str, Any]) -> None:
    missing = sorted(CATALOG_REQUIRED - set(catalog))
    if missing:
        raise ResearchError(f"series catalog 缺少字段: {', '.join(missing)}")
    if not isinstance(catalog["tradable"], bool) or not isinstance(
        catalog["overlapping_targets"], bool
    ):
        raise ResearchError("catalog 的 tradable/overlapping_targets 必须是 boolean")
    try:
        periods_per_year = float(catalog["periods_per_year"])
    except (TypeError, ValueError) as exc:
        raise ResearchError("periods_per_year 必须是数值") from exc
    if not math.isfinite(periods_per_year) or not 0 < periods_per_year <= 1_000_000:
        raise ResearchError("periods_per_year 必须在 0-1,000,000 之间")
    target_column = catalog.get("target_column", "target")
    if not isinstance(target_column, str) or not target_column.strip():
        raise ResearchError("target_column 必须是非空字符串")


def validate_feature_manifest(manifest: dict[str, Any], feature_hash: str) -> None:
    required = {
        "schema_version",
        "source_type",
        "feature_file_sha256",
        "coordinate_profile",
        "frame",
        "pre_utc_policy",
        "body_targets",
    }
    missing = sorted(required - set(manifest))
    if missing:
        raise ResearchError(f"feature manifest 缺少字段: {', '.join(missing)}")
    if manifest["feature_file_sha256"] != feature_hash:
        raise ResearchError("feature manifest 的 SHA-256 与实际 feature CSV 不一致")
    if manifest["source_type"] == "jpl_spk":
        kernel_hash = manifest.get("kernel_sha256")
        if not isinstance(kernel_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", kernel_hash):
            raise ResearchError("JPL feature manifest 必须包含合法 kernel_sha256")
    elif manifest["source_type"] != "synthetic_fixture":
        raise ResearchError("feature manifest source_type 必须是 jpl_spk 或 synthetic_fixture")
    if manifest["pre_utc_policy"] not in ("strict", "explicit-proleptic"):
        raise ResearchError("feature manifest pre_utc_policy 无效")
    if not isinstance(manifest["frame"], dict) or not isinstance(manifest["body_targets"], dict):
        raise ResearchError("feature manifest frame/body_targets 必须是 objects")


def validate_hypothesis(hypothesis: dict[str, Any]) -> None:
    required = {
        "hypothesis_id",
        "registered_at_utc",
        "registered_commit",
        "mode",
        "features",
        "train_end_utc",
        "validation_end_utc",
        "embargo_hours",
        "max_feature_staleness_hours",
        "placebo_runs",
        "seed",
    }
    missing = sorted(required - set(hypothesis))
    if missing:
        raise ResearchError(f"hypothesis manifest 缺少字段: {', '.join(missing)}")
    if hypothesis["mode"] not in ("exploratory", "pseudo_oos", "prospective"):
        raise ResearchError("mode 必须是 exploratory、pseudo_oos 或 prospective")
    if not isinstance(hypothesis["hypothesis_id"], str) or not hypothesis["hypothesis_id"].strip():
        raise ResearchError("hypothesis_id 必须是非空字符串")
    parse_utc(hypothesis["registered_at_utc"], allow_pre_utc=True)
    if (
        not isinstance(hypothesis["registered_commit"], str)
        or not hypothesis["registered_commit"].strip()
    ):
        raise ResearchError("registered_commit 必须是非空字符串")
    if not isinstance(hypothesis["features"], list) or not hypothesis["features"]:
        raise ResearchError("features 必须是非空数组")
    if len(hypothesis["features"]) > 300:
        raise ResearchError("单次预注册 feature family 最多 300 项")
    seen = set()
    for feature in hypothesis["features"]:
        if not isinstance(feature, dict) or "name" not in feature:
            raise ResearchError("每个 feature 必须至少包含 name")
        if not isinstance(feature["name"], str) or not 0 < len(feature["name"]) <= 200:
            raise ResearchError("feature name 必须是 1-200 字符的字符串")
        if feature["name"] in seen:
            raise ResearchError(f"重复 feature: {feature['name']}")
        seen.add(feature["name"])
        direction = feature.get("direction", "two-sided")
        if direction not in ("positive", "negative", "two-sided"):
            raise ResearchError(f"feature {feature['name']} 的 direction 无效")
        period = feature.get("effective_period_days")
        if period is not None:
            try:
                period_value = float(period)
            except (TypeError, ValueError) as exc:
                raise ResearchError("effective_period_days 必须是数值") from exc
            if not math.isfinite(period_value) or period_value <= 0:
                raise ResearchError("effective_period_days 必须大于 0")
    try:
        placebo_runs = int(hypothesis["placebo_runs"])
        int(hypothesis["seed"])
        embargo_hours = float(hypothesis["embargo_hours"])
        staleness_hours = float(hypothesis["max_feature_staleness_hours"])
        cost_bps = float(hypothesis.get("cost_bps", 0.0))
    except (TypeError, ValueError) as exc:
        raise ResearchError("placebo/seed/embargo/staleness/cost 参数类型无效") from exc
    if placebo_runs < 99 or placebo_runs > 10_000:
        raise ResearchError("placebo_runs 必须在 99-10,000 之间；确认性研究建议 1000+")
    if not math.isfinite(embargo_hours) or not 0 <= embargo_hours <= 24 * 365 * 10:
        raise ResearchError("embargo_hours 必须在 0 到 10 年之间")
    if not math.isfinite(staleness_hours) or not 0 <= staleness_hours <= 24 * 365:
        raise ResearchError("max_feature_staleness_hours 必须在 0 到 1 年之间")
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 10_000:
        raise ResearchError("cost_bps 必须在 0-10,000 之间")


def _load_feature_rows(
    path: str | Path, requested_features: list[str]
) -> tuple[list[datetime], list[dict[str, float]]]:
    source = input_file_path(path, "feature CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "timestamp_utc" not in reader.fieldnames:
            raise ResearchError("feature CSV 必须包含 timestamp_utc")
        if len(reader.fieldnames) > 5_001:
            raise ResearchError("feature CSV 超过 5,000 个 feature 列安全上限")
        missing_features = sorted(set(requested_features) - set(reader.fieldnames))
        if missing_features:
            raise ResearchError(f"feature CSV 不含预注册字段: {', '.join(missing_features)}")
        feature_names = requested_features
        times, rows = [], []
        for line_number, row in enumerate(reader, 2):
            if line_number > MAX_RESEARCH_ROWS + 1:
                raise ResearchError(f"feature CSV 超过 {MAX_RESEARCH_ROWS:,} 行安全上限")
            if (line_number - 1) * len(feature_names) > MAX_MATRIX_CELLS:
                raise ResearchError(
                    f"feature matrix 超过 {MAX_MATRIX_CELLS:,} cells 安全上限；缩小日期或预注册 family"
                )
            timestamp = parse_utc(row["timestamp_utc"], allow_pre_utc=True)
            values: dict[str, float] = {}
            for name in feature_names:
                try:
                    value = float(row[name])
                except (TypeError, ValueError) as exc:
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 不是数值") from exc
                if not math.isfinite(value):
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 非有限值")
                if abs(value) > 1e100:
                    raise ResearchError(f"feature CSV 第 {line_number} 行 {name} 绝对值过大")
                values[name] = value
            times.append(timestamp)
            rows.append(values)
    if not times:
        raise ResearchError("feature CSV 没有数据")
    if any(a >= b for a, b in pairwise(times)):
        raise ResearchError("feature timestamp_utc 必须严格递增且无重复")
    return times, rows


def _load_target_rows(path: str | Path, target_column: str) -> list[dict[str, Any]]:
    source = input_file_path(path, "target CSV")
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted((TARGET_REQUIRED | {target_column}) - fields)
        if missing:
            raise ResearchError(f"target CSV 缺少字段: {', '.join(missing)}")
        rows = []
        for line_number, raw in enumerate(reader, 2):
            if line_number > MAX_RESEARCH_ROWS + 1:
                raise ResearchError(f"target CSV 超过 {MAX_RESEARCH_ROWS:,} 行安全上限")
            parsed = {field: parse_utc(raw[field], allow_pre_utc=True) for field in TARGET_REQUIRED}
            if not (
                parsed["observation_time_utc"]
                <= parsed["available_at_utc"]
                <= parsed["decision_at_utc"]
                < parsed["execution_at_utc"]
                <= parsed["target_start_utc"]
                < parsed["target_end_utc"]
            ):
                raise ResearchError(
                    f"target CSV 第 {line_number} 行违反 point-in-time 顺序: "
                    "observation <= available <= decision < execution <= target_start < target_end"
                )
            try:
                target = float(raw[target_column])
            except (TypeError, ValueError) as exc:
                raise ResearchError(f"target CSV 第 {line_number} 行 target 不是数值") from exc
            if not math.isfinite(target):
                raise ResearchError(f"target CSV 第 {line_number} 行 target 非有限值")
            if abs(target) > 1e100:
                raise ResearchError(f"target CSV 第 {line_number} 行 target 绝对值过大")
            parsed["target"] = target
            rows.append(parsed)
    if not rows:
        raise ResearchError("target CSV 没有数据")
    decisions = [row["decision_at_utc"] for row in rows]
    if any(a >= b for a, b in pairwise(decisions)):
        raise ResearchError("decision_at_utc 必须严格递增且无重复")
    for field in ("execution_at_utc", "target_start_utc", "target_end_utc"):
        timeline = [row[field] for row in rows]
        if any(a >= b for a, b in pairwise(timeline)):
            raise ResearchError(f"{field} 必须按 decision 行顺序严格递增")
    return rows


def target_intervals_overlap(rows: list[dict[str, Any]]) -> bool:
    intervals = sorted((row["target_start_utc"], row["target_end_utc"]) for row in rows)
    latest_end: datetime | None = None
    for start, end in intervals:
        if latest_end is not None and start < latest_end:
            return True
        latest_end = end if latest_end is None else max(latest_end, end)
    return False


def _asof_join(
    feature_times: list[datetime],
    feature_rows: list[dict[str, float]],
    targets: list[dict[str, Any]],
    feature_names: list[str],
    max_staleness_hours: float,
) -> list[dict[str, Any]]:
    joined = []
    for target in targets:
        index = bisect_right(feature_times, target["decision_at_utc"]) - 1
        if index < 0:
            continue
        feature_time = feature_times[index]
        staleness = (target["decision_at_utc"] - feature_time).total_seconds() / 3600
        if staleness < 0:
            raise AssertionError("as-of join selected a future feature")
        if staleness > max_staleness_hours:
            continue
        values = feature_rows[index]
        missing = [name for name in feature_names if name not in values]
        if missing:
            raise ResearchError(f"feature CSV 不含预注册字段: {', '.join(missing)}")
        joined.append(
            {
                **target,
                "feature_timestamp_utc": feature_time,
                "feature_staleness_hours": staleness,
                "features": {name: values[name] for name in feature_names},
            }
        )
    return joined


def _split_rows(
    rows: list[dict[str, Any]],
    train_end: datetime,
    validation_end: datetime,
    embargo_hours: float,
) -> dict[str, list[dict[str, Any]]]:
    if validation_end <= train_end:
        raise ResearchError("validation_end 必须晚于 train_end")
    embargo = timedelta(hours=embargo_hours)
    splits = {"train": [], "validation": [], "test": []}
    for row in rows:
        decision, target_end = row["decision_at_utc"], row["target_end_utc"]
        if decision <= train_end and target_end <= train_end:
            splits["train"].append(row)
        elif train_end + embargo < decision <= validation_end and target_end <= validation_end:
            splits["validation"].append(row)
        elif decision > validation_end + embargo:
            splits["test"].append(row)
    for name, split in splits.items():
        if len(split) < 8:
            raise ResearchError(f"{name} 有效样本仅 {len(split)}，至少需要 8")
    return splits


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) != len(y) or len(x) < 3:
        raise ResearchError("相关系数至少需要 3 个成对样本")
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    numerator = math.fsum(a * b for a, b in zip(centered_x, centered_y, strict=True))
    denominator = math.sqrt(
        math.fsum(value * value for value in centered_x)
        * math.fsum(value * value for value in centered_y)
    )
    return numerator / denominator if denominator else 0.0


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2.0
        for index in order[start:end]:
            ranks[index] = average
        start = end
    return ranks


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(_rank(x), _rank(y))


def bh_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=p_values.__getitem__)
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[original_index] * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def _ic(rows: list[dict[str, Any]], feature: str) -> dict[str, float | int]:
    x = [row["features"][feature] for row in rows]
    y = [row["target"] for row in rows]
    return {"n": len(rows), "pearson": pearson(x, y), "spearman": spearman(x, y)}


def _strategy_metrics(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    feature: str,
    direction: str,
    catalog: dict[str, Any],
    cost_bps: float,
) -> dict[str, Any] | None:
    if not catalog["tradable"] or catalog["overlapping_targets"]:
        return None
    if catalog["target_kind"] not in ("simple_return", "log_return"):
        return None
    target_values = [row["target"] for row in [*train, *test]]
    if catalog["target_kind"] == "simple_return" and any(
        value <= -1 or abs(value) > 100 for value in target_values
    ):
        return None
    if catalog["target_kind"] == "log_return" and any(abs(value) > 100 for value in target_values):
        return None
    train_x = [row["features"][feature] for row in train]
    if len(set(train_x)) < 2:
        return None
    threshold = statistics.median(train_x)
    train_ic = pearson(train_x, [row["target"] for row in train])
    sign = (
        1.0
        if direction == "positive"
        else -1.0
        if direction == "negative"
        else (1.0 if train_ic >= 0 else -1.0)
    )
    positions = [sign if row["features"][feature] > threshold else -sign for row in test]
    net_returns = []
    previous = 0.0
    cost_rate = cost_bps / 10_000.0
    for position, row in zip(positions, test, strict=True):
        one_way_notional = abs(position - previous)
        cost_fraction = one_way_notional * cost_rate
        if catalog["target_kind"] == "log_return":
            if cost_fraction >= 1:
                return None
            net_returns.append(position * row["target"] + math.log1p(-cost_fraction))
        else:
            net_returns.append(position * row["target"] - cost_fraction)
        previous = position
    mean_return = statistics.fmean(net_returns)
    stdev = statistics.stdev(net_returns) if len(net_returns) > 1 else 0.0
    periods = float(catalog["periods_per_year"])
    sharpe = mean_return / stdev * math.sqrt(periods) if stdev else 0.0
    if catalog["target_kind"] == "log_return":
        equity = [
            math.exp(math.fsum(net_returns[: index + 1])) for index in range(len(net_returns))
        ]
        baseline_equity = [
            math.exp(math.fsum(row["target"] for row in test[: index + 1]))
            for index in range(len(test))
        ]
    else:
        equity, baseline_equity = [], []
        current_strategy = current_baseline = 1.0
        for value, row in zip(net_returns, test, strict=True):
            if value <= -1 or row["target"] <= -1:
                return None
            current_strategy *= 1 + value
            current_baseline *= 1 + row["target"]
            equity.append(current_strategy)
            baseline_equity.append(current_baseline)

    def max_drawdown(curve: list[float]) -> float:
        peak, worst = curve[0], 0.0
        for value in curve:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        return worst

    baseline_returns = [row["target"] for row in test]
    baseline_std = statistics.stdev(baseline_returns) if len(baseline_returns) > 1 else 0.0
    baseline_sharpe = (
        statistics.fmean(baseline_returns) / baseline_std * math.sqrt(periods)
        if baseline_std
        else 0.0
    )
    return {
        "rule": "train-median threshold; direction fixed from manifest or learned once in train",
        "threshold_fit_on_train": threshold,
        "direction": sign,
        "cost_bps_per_one_way_notional": cost_bps,
        "oos_periods": len(test),
        "annualized_sharpe": sharpe,
        "baseline_definition": "always-long target return (not financial-control model M0)",
        "baseline_annualized_sharpe": baseline_sharpe,
        "delta_sharpe": sharpe - baseline_sharpe,
        "ending_equity": equity[-1],
        "baseline_ending_equity": baseline_equity[-1],
        "max_drawdown": max_drawdown(equity),
    }


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


def _run_point_in_time_research_impl(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path | None = None,
    trial_id: str | None = None,
) -> dict[str, Any]:
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    paths = {
        "feature_csv": input_file_path(feature_csv, "feature CSV"),
        "target_csv": input_file_path(target_csv, "target CSV"),
        "catalog_json": input_file_path(catalog_json, "series catalog", MAX_CONFIG_BYTES),
        "hypothesis_json": input_file_path(
            hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES
        ),
        "feature_manifest_json": input_file_path(
            feature_manifest_json, "feature manifest", MAX_CONFIG_BYTES
        ),
    }
    registry_path = safe_output_path(trial_registry, "trial registry")
    ensure_distinct_paths({**paths, "trial_registry": registry_path})
    snapshot_dir, snapshots, hashes = snapshot_input_files(paths)
    try:
        catalog = _load_json_object(snapshots["catalog_json"], "series catalog")
        hypothesis = _load_json_object(snapshots["hypothesis_json"], "hypothesis manifest")
        feature_manifest = _load_json_object(snapshots["feature_manifest_json"], "feature manifest")
        validate_catalog(catalog)
        validate_hypothesis(hypothesis)
        validate_feature_manifest(feature_manifest, hashes["feature_csv"])
        feature_names = [item["name"] for item in hypothesis["features"]]
        try:
            feature_times, feature_rows = _load_feature_rows(
                snapshots["feature_csv"], feature_names
            )
            target_column = catalog.get("target_column", "target")
            targets = _load_target_rows(snapshots["target_csv"], target_column)
        except (csv.Error, UnicodeError, OSError) as exc:
            raise ResearchError(f"无法安全解析 research CSV: {type(exc).__name__}: {exc}") from exc
    finally:
        snapshot_dir.cleanup()

    actual_overlap = target_intervals_overlap(targets)
    if actual_overlap and not catalog["overlapping_targets"]:
        raise ResearchError(
            "target intervals 实际重叠，但 series catalog 声明 overlapping_targets=false"
        )

    pre_utc_policy = hypothesis.get("pre_utc_policy", "reject")
    if pre_utc_policy not in ("reject", "proleptic_utc_label"):
        raise ResearchError("pre_utc_policy 必须是 reject 或 proleptic_utc_label")
    all_target_times = [row[field] for row in targets for field in TARGET_REQUIRED]
    uses_pre_utc = feature_times[0] < STRICT_UTC_START or any(
        timestamp < STRICT_UTC_START for timestamp in all_target_times
    )
    if uses_pre_utc and pre_utc_policy == "reject":
        raise ResearchError("研究包含 1972 年前时间；必须预注册 pre_utc_policy=proleptic_utc_label")
    if uses_pre_utc and feature_manifest["pre_utc_policy"] != "explicit-proleptic":
        raise ResearchError("1972 年前 feature manifest 未声明 explicit-proleptic")

    joined = _asof_join(
        feature_times,
        feature_rows,
        targets,
        feature_names,
        float(hypothesis["max_feature_staleness_hours"]),
    )
    train_end = parse_utc(hypothesis["train_end_utc"], allow_pre_utc=True)
    validation_end = parse_utc(hypothesis["validation_end_utc"], allow_pre_utc=True)
    splits = _split_rows(joined, train_end, validation_end, float(hypothesis["embargo_hours"]))

    git_state = _git_state()
    registration_time = parse_utc(hypothesis["registered_at_utc"], allow_pre_utc=True)
    if hypothesis["mode"] == "prospective":
        registered_commit = hypothesis["registered_commit"]
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", registered_commit):
            raise ResearchError("prospective registered_commit 必须是完整 Git object ID")
        if registration_time > datetime.now(timezone.utc):
            raise ResearchError("prospective registered_at_utc 不能在未来")
        if any(
            row["observation_time_utc"] < registration_time
            or row["decision_at_utc"] < registration_time
            for row in splits["test"]
        ):
            raise ResearchError("prospective test observation/decision 必须发生在注册之后")
        if any(row["target_end_utc"] > datetime.now(timezone.utc) for row in splits["test"]):
            raise ResearchError("prospective test target 必须在评估前完整结束")
        if git_state["commit"] is None or git_state["dirty"] is not False:
            raise ResearchError("prospective 模式要求可验证且干净的 Git 工作树")
        if not _git_is_ancestor(registered_commit):
            raise ResearchError("registered_commit 不是当前 HEAD 的可验证 ancestor")

    registry_entry = {
        "trial_id": trial_id,
        "accessed_at_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis["hypothesis_id"],
        "mode": hypothesis["mode"],
        "input_sha256": hashes,
        "code": {**git_state, "source_sha256": code_source_sha256()},
    }

    statistics_by_feature: list[dict[str, Any]] = []
    for definition in hypothesis["features"]:
        name = definition["name"]
        statistics_by_feature.append(
            {
                "name": name,
                "direction": definition.get("direction", "two-sided"),
                "effective_period_days": definition.get("effective_period_days"),
                "train": _ic(splits["train"], name),
                "validation": _ic(splits["validation"], name),
                "test": _ic(splits["test"], name),
            }
        )

    # Time-shift placebo preserves the complete multivariate feature row and its
    # autocorrelation. maxT corrects selection across this preregistered family.
    requested_runs = int(hypothesis["placebo_runs"])
    rng = random.Random(int(hypothesis["seed"]))
    test = splits["test"]
    target_values = [row["target"] for row in test]
    if len(test) < 3:
        raise ResearchError("test 样本太少，无法运行 placebo")

    def transform_statistic(correlation: float, direction: str) -> float:
        if direction == "positive":
            return correlation
        if direction == "negative":
            return -correlation
        return abs(correlation)

    observed_statistics = [
        transform_statistic(item["test"]["pearson"], item["direction"])
        for item in statistics_by_feature
    ]
    exceed_individual = [0] * len(feature_names)
    exceed_max = [0] * len(feature_names)
    effective_runs = min(requested_runs, len(test))
    if effective_runs * len(test) * len(feature_names) > MAX_PLACEBO_OPERATIONS:
        raise ResearchError(f"placebo workload 超过 {MAX_PLACEBO_OPERATIONS:,} operations 安全上限")
    shifts = (
        list(range(len(test)))
        if effective_runs == len(test)
        else [0, *rng.sample(range(1, len(test)), effective_runs - 1)]
    )
    original_features = {name: [row["features"][name] for row in test] for name in feature_names}
    for shift in shifts:
        null_values = []
        for feature_index, (name, item) in enumerate(
            zip(feature_names, statistics_by_feature, strict=True)
        ):
            original = original_features[name]
            shifted = original if shift == 0 else original[-shift:] + original[:-shift]
            statistic = transform_statistic(pearson(shifted, target_values), item["direction"])
            null_values.append(statistic)
            if statistic >= observed_statistics[feature_index]:
                exceed_individual[feature_index] += 1
        null_max = max(null_values)
        for feature_index, observed in enumerate(observed_statistics):
            if null_max >= observed:
                exceed_max[feature_index] += 1

    p_individual = [value / effective_runs for value in exceed_individual]
    p_max = [value / effective_runs for value in exceed_max]
    q_values = bh_adjust(p_individual)

    train_span_days = (
        splits["train"][-1]["decision_at_utc"] - splits["train"][0]["decision_at_utc"]
    ).total_seconds() / 86400
    test_span_days = (
        splits["test"][-1]["decision_at_utc"] - splits["test"][0]["decision_at_utc"]
    ).total_seconds() / 86400
    cost_bps = float(hypothesis.get("cost_bps", 0.0))
    for index, item in enumerate(statistics_by_feature):
        item["placebo"] = {
            "method": "joint circular time-shift of preregistered feature rows",
            "requested_runs": requested_runs,
            "effective_unique_shifts": effective_runs,
            "finite_group_size": len(test),
            "alternative": item["direction"],
            "empirical_p": p_individual[index],
            "familywise_maxT_p": p_max[index],
            "bh_q": q_values[index],
        }
        period = item["effective_period_days"]
        identifiable = False
        if period is not None:
            item["train_cycles"] = train_span_days / float(period)
            item["test_cycles"] = test_span_days / float(period)
            identifiable = item["train_cycles"] >= 3 and item["test_cycles"] >= 1
        signs = [
            math.copysign(1, item[split]["pearson"]) if item[split]["pearson"] != 0 else 0
            for split in ("train", "validation", "test")
        ]
        expected_sign = (
            1
            if item["direction"] == "positive"
            else -1
            if item["direction"] == "negative"
            else None
        )
        item["direction_matches_manifest"] = (
            signs[2] != 0 if expected_sign is None else signs[2] == expected_sign
        )
        item["direction_stable"] = (
            signs[0] != 0
            and signs[0] == signs[1] == signs[2]
            and item["direction_matches_manifest"]
        )
        item["evidence_status"] = "EXPLORATORY_TESTED" if identifiable else "DESCRIPTIVE"
        item["strategy"] = _strategy_metrics(
            splits["train"],
            splits["test"],
            item["name"],
            item["direction"],
            catalog,
            cost_bps,
        )

    if hypothesis["mode"] == "prospective":
        overall_status = "PROSPECTIVE_DECLARED_UNVERIFIED"
    elif hypothesis["mode"] == "pseudo_oos":
        overall_status = "PSEUDO_OOS_ONLY"
    else:
        overall_status = "EXPLORATORY"

    return {
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "evidence_status": overall_status,
        "claim_boundary": (
            "Univariate association MVP only; no causal or incremental-information claim, no proof of astrology, and no investment advice."
        ),
        "hypothesis": hypothesis,
        "series_catalog": catalog,
        "feature_manifest": feature_manifest,
        "provenance": {
            "input_paths": {name: str(path) for name, path in paths.items()},
            "input_sha256": hashes,
            "trial_registry": str(registry_path),
            "trial": registry_entry,
            "pre_utc_policy": pre_utc_policy,
        },
        "point_in_time_invariant": (
            "observation <= available <= decision < execution <= target_start < target_end"
        ),
        "alignment": {
            "method": "backward as-of only",
            "joined_rows": len(joined),
            "dropped_rows": len(targets) - len(joined),
            "max_feature_staleness_hours": hypothesis["max_feature_staleness_hours"],
            "actual_overlapping_targets": actual_overlap,
        },
        "splits": {name: len(rows) for name, rows in splits.items()},
        "features": statistics_by_feature,
        "limitations": [
            "Retrospective data already inspected cannot become a sealed OOS sample.",
            "Time-shift placebo is one null family, not a full phase-randomized pipeline universe.",
            "No strategy metric is emitted for indicators, non-return targets, or overlapping targets.",
            "Market data and target construction are BYOD and must be independently audited.",
            "This MVP tests marginal univariate association; financial controls and paired M0-vs-M2 incremental tests are not implemented.",
        ],
    }


def run_point_in_time_research(
    feature_csv: str | Path,
    target_csv: str | Path,
    catalog_json: str | Path,
    hypothesis_json: str | Path,
    trial_registry: str | Path,
    feature_manifest_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one audited trial, recording STARTED plus COMPLETED or FAILED."""
    feature_manifest_json = feature_manifest_json or f"{feature_csv}.manifest.json"
    protected = {
        "feature_csv": input_file_path(feature_csv, "feature CSV"),
        "target_csv": input_file_path(target_csv, "target CSV"),
        "catalog_json": input_file_path(catalog_json, "series catalog", MAX_CONFIG_BYTES),
        "hypothesis_json": input_file_path(
            hypothesis_json, "hypothesis manifest", MAX_CONFIG_BYTES
        ),
        "feature_manifest_json": input_file_path(
            feature_manifest_json, "feature manifest", MAX_CONFIG_BYTES
        ),
    }
    registry_path = safe_output_path(trial_registry, "trial registry")
    ensure_distinct_paths({**protected, "trial_registry": registry_path})
    hypothesis_bytes = protected["hypothesis_json"].read_bytes()
    hypothesis_hash = hashlib.sha256(hypothesis_bytes).hexdigest()
    hypothesis_id = None
    try:
        parsed_hypothesis = json.loads(hypothesis_bytes)
        if isinstance(parsed_hypothesis, dict):
            hypothesis_id = parsed_hypothesis.get("hypothesis_id")
    except (UnicodeError, ValueError, json.JSONDecodeError):
        pass
    trial_id = uuid.uuid4().hex
    started = {
        "event": "STARTED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis_id,
        "provided_hypothesis_sha256": hypothesis_hash,
        "code_source_sha256": code_source_sha256(),
    }
    append_trial_registry(registry_path, started, protected_paths=protected.values())
    try:
        result = _run_point_in_time_research_impl(
            feature_csv,
            target_csv,
            catalog_json,
            hypothesis_json,
            registry_path,
            feature_manifest_json,
            trial_id,
        )
    except Exception as exc:
        failed = {
            "event": "FAILED",
            "trial_id": trial_id,
            "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
            "hypothesis_id": hypothesis_id,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        append_trial_registry(registry_path, failed, protected_paths=protected.values())
        raise
    completed = {
        "event": "COMPLETED",
        "trial_id": trial_id,
        "timestamp_utc": iso_utc(datetime.now(timezone.utc)),
        "hypothesis_id": hypothesis_id,
        "evidence_status": result["evidence_status"],
        "input_sha256": result["provenance"]["input_sha256"],
    }
    append_trial_registry(registry_path, completed, protected_paths=protected.values())
    result["provenance"]["trial_events"] = ["STARTED", "COMPLETED"]
    return result
