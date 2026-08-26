"""Astronomical feature derivation and auditable feature-file construction."""

from __future__ import annotations

import csv
import importlib.metadata
import json
import math
import os
import platform
import tempfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__:  # package import
    from .research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_BUILD_CELLS,
        STRICT_UTC_START,
        ResearchError,
        _atomic_write_text,
        _commit_temp_file,
        ensure_distinct_paths,
        iso_utc,
        parse_utc,
        safe_output_path,
        sha256_file,
        signed_angle_deg,
    )
    from .research_ephemeris import BODY_ORDER, DEFAULT_BODIES, SkyfieldEphemeris
else:  # direct scripts import
    from research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_BUILD_CELLS,
        STRICT_UTC_START,
        ResearchError,
        _atomic_write_text,
        _commit_temp_file,
        ensure_distinct_paths,
        iso_utc,
        parse_utc,
        safe_output_path,
        sha256_file,
        signed_angle_deg,
    )
    from research_ephemeris import BODY_ORDER, DEFAULT_BODIES, SkyfieldEphemeris

DEFAULT_PAIRS = (
    ("jupiter", "saturn"),
    ("mars", "saturn"),
    ("mars", "jupiter"),
    ("sun", "jupiter"),
    ("sun", "saturn"),
    ("venus", "jupiter"),
    ("mercury", "jupiter"),
)
ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}


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
