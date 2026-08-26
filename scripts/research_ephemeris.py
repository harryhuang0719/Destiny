"""JPL/Skyfield-backed astronomical state loading."""

from __future__ import annotations

import math
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__:  # package import
    from .research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_KERNEL_BYTES,
        STRICT_UTC_START,
        ResearchError,
        input_file_path,
        iso_utc,
        parse_utc,
        signed_angle_deg,
        snapshot_input_files,
    )
else:  # direct scripts import
    from research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_KERNEL_BYTES,
        STRICT_UTC_START,
        ResearchError,
        input_file_path,
        iso_utc,
        parse_utc,
        signed_angle_deg,
        snapshot_input_files,
    )

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
