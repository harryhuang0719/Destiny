#!/usr/bin/env python3
"""CLI for Destiny's optional historical astronomy research module."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

if __package__:  # package install
    from .historical_research import (
        ASPECTS,
        ASTRO_SCHEMA_VERSION,
        BODY_TARGETS,
        DEFAULT_BODIES,
        DEFAULT_PAIRS,
        MAX_BUILD_CELLS,
        ResearchError,
        SkyfieldEphemeris,
        _atomic_write_text,
        canonical_pair,
        ensure_distinct_paths,
        features_from_state,
        iso_utc,
        parse_utc,
        run_point_in_time_research,
        safe_output_path,
        sha256_file,
        write_feature_csv,
    )
    from .research_contracts import _load_json_object, incremental_model_enabled
else:  # direct scripts/history_cli.py execution
    from historical_research import (
        ASPECTS,
        ASTRO_SCHEMA_VERSION,
        BODY_TARGETS,
        DEFAULT_BODIES,
        DEFAULT_PAIRS,
        MAX_BUILD_CELLS,
        ResearchError,
        SkyfieldEphemeris,
        _atomic_write_text,
        canonical_pair,
        ensure_distinct_paths,
        features_from_state,
        iso_utc,
        parse_utc,
        run_point_in_time_research,
        safe_output_path,
        sha256_file,
        write_feature_csv,
    )
    from research_contracts import _load_json_object, incremental_model_enabled


def _csv_items(value: str) -> tuple[str, ...]:
    items = tuple(item.strip().lower() for item in value.split(",") if item.strip())
    if not items:
        raise argparse.ArgumentTypeError("列表不能为空")
    unknown = sorted(set(items) - set(BODY_TARGETS))
    if unknown:
        raise argparse.ArgumentTypeError(f"未知天体: {', '.join(unknown)}")
    return items


def _pairs(value: str) -> tuple[tuple[str, str], ...]:
    if value.strip().lower() == "default":
        return DEFAULT_PAIRS
    result = []
    for raw_pair in value.split(","):
        parts = [part.strip().lower() for part in raw_pair.split(":")]
        if len(parts) != 2 or parts[0] == parts[1]:
            raise argparse.ArgumentTypeError(
                "pair 格式应为 body1:body2,body3:body4，且两端不能相同"
            )
        if any(part not in BODY_TARGETS for part in parts):
            raise argparse.ArgumentTypeError(f"未知 pair: {raw_pair}")
        try:
            result.append(canonical_pair(parts[0], parts[1]))
        except ResearchError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc
    if len(set(result)) != len(result):
        raise argparse.ArgumentTypeError("pair 列表含重复或反向重复")
    return tuple(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="destiny history",
        description=(
            "历史天文查询与 point-in-time 金融研究。默认不下载 kernel 或市场数据，"
            "也不把回溯结果称为已证明的预测力。"
        ),
    )
    subparsers = parser.add_subparsers(dest="history_command", required=True)

    kernel = subparsers.add_parser("kernel-info", help="验证并哈希本地 JPL SPK kernel")
    kernel.add_argument("--kernel", required=True)

    astro = subparsers.add_parser("astro", help="查询单个 UTC 时刻的天文状态与连续特征")
    astro.add_argument("--kernel", required=True)
    astro.add_argument("--at", required=True, help="带 offset 的 ISO-8601 时间")
    astro.add_argument("--bodies", type=_csv_items, default=DEFAULT_BODIES)
    astro.add_argument(
        "--pairs",
        type=_pairs,
        default=None,
        help="body1:body2,...; omitted = default pairs filtered to selected bodies",
    )
    astro.add_argument("--harmonics", type=int, default=2)
    astro.add_argument("--aspect-sigma", type=float, default=3.0)
    astro.add_argument("--allow-pre-utc", action="store_true")

    build = subparsers.add_parser("build", help="生成可追溯的历史天文 feature CSV")
    build.add_argument("--kernel", required=True)
    build.add_argument("--start", required=True, help="带 offset 的 ISO-8601 时间")
    build.add_argument("--end", required=True, help="带 offset 的 ISO-8601 时间")
    build.add_argument("--step-hours", type=int, default=24)
    build.add_argument("--bodies", type=_csv_items, default=DEFAULT_BODIES)
    build.add_argument(
        "--pairs",
        type=_pairs,
        default=None,
        help="body1:body2,...; omitted = default pairs filtered to selected bodies",
    )
    build.add_argument("--harmonics", type=int, default=2)
    build.add_argument("--aspect-sigma", type=float, default=3.0)
    build.add_argument("--out", required=True)
    build.add_argument("--max-rows", type=int, default=100_000)
    build.add_argument("--allow-pre-utc", action="store_true")
    build.add_argument("--overwrite", action="store_true")
    build.add_argument("--dry-run", action="store_true")

    research = subparsers.add_parser(
        "research", help="运行预注册、point-in-time、带 placebo 的历史关联/回测"
    )
    research.add_argument("--features", required=True, help="历史 feature CSV")
    research.add_argument(
        "--feature-manifest",
        help="feature manifest JSON; default is <features>.manifest.json",
    )
    research.add_argument("--targets", required=True, help="point-in-time target CSV")
    research.add_argument("--catalog", required=True, help="series catalog JSON")
    research.add_argument("--hypothesis", required=True, help="预注册 hypothesis JSON")
    research.add_argument(
        "--controls",
        help="long-form point-in-time controls CSV；incremental 模式必填",
    )
    research.add_argument(
        "--controls-catalog",
        help="controls catalog JSON；incremental 模式必填",
    )
    research.add_argument("--trial-registry", required=True, help="append-only NDJSON registry")
    research.add_argument("--out", required=True)
    research.add_argument("--overwrite", action="store_true")
    return parser


def _validate_control_option_pair(controls: str | None, controls_catalog: str | None) -> bool:
    if (controls is None) != (controls_catalog is None):
        raise ResearchError("--controls 与 --controls-catalog 必须同时提供")
    return controls is not None


def _write_result(path: str, data: dict, overwrite: bool) -> None:
    target = safe_output_path(path, "result output")
    if target.exists() and not overwrite:
        raise ResearchError(f"输出已存在；如确认覆盖请加 --overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Result files are not secrets, but a partial JSON file is still dangerous to
    # downstream automation. Use the same-directory temp-and-replace pattern.
    _atomic_write_text(
        target,
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        overwrite=overwrite,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if hasattr(args, "harmonics") and not 1 <= args.harmonics <= 6:
            raise ResearchError("harmonics 必须在 1-6 之间")
        if hasattr(args, "aspect_sigma") and not (
            math.isfinite(args.aspect_sigma) and 0 < args.aspect_sigma <= 180
        ):
            raise ResearchError("aspect-sigma 必须是 0-180 之间的有限数值")
        if hasattr(args, "max_rows") and not 1 <= args.max_rows <= 1_000_000:
            raise ResearchError("max-rows 必须在 1-1,000,000 之间")
        if args.history_command == "kernel-info":
            backend = SkyfieldEphemeris(args.kernel)
            result = {
                "schema_version": ASTRO_SCHEMA_VERSION,
                "kernel_path": str(backend.kernel_path),
                "kernel_sha256": backend.kernel_sha256,
                "segments": len(backend.ephemeris.segments),
                "supported_body_names": sorted(BODY_TARGETS),
                "note": "Kernel is external data; this command does not imply NASA/JPL endorsement.",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0

        if args.history_command == "astro":
            at = parse_utc(args.at, allow_pre_utc=args.allow_pre_utc)
            backend = SkyfieldEphemeris(args.kernel)
            state = backend.state(at, args.bodies, allow_pre_utc=args.allow_pre_utc)
            pairs = (
                tuple(pair for pair in DEFAULT_PAIRS if set(pair) <= set(args.bodies))
                if args.pairs is None
                else args.pairs
            )
            result = {
                "schema_version": ASTRO_SCHEMA_VERSION,
                "state": state,
                "features": features_from_state(
                    state,
                    pairs,
                    harmonics=args.harmonics,
                    aspect_sigma_deg=args.aspect_sigma,
                ),
                "claim_boundary": "Deterministic astronomical reconstruction, not a market forecast.",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0

        if args.history_command == "build":
            start = parse_utc(args.start, allow_pre_utc=args.allow_pre_utc)
            end = parse_utc(args.end, allow_pre_utc=args.allow_pre_utc)
            if args.step_hours <= 0 or end < start:
                raise ResearchError("step-hours 必须大于 0，且 end 不得早于 start")
            estimated_rows = int((end - start).total_seconds() // (args.step_hours * 3600)) + 1
            pairs = (
                tuple(pair for pair in DEFAULT_PAIRS if set(pair) <= set(args.bodies))
                if args.pairs is None
                else args.pairs
            )
            if args.dry_run:
                estimated_columns = (
                    1
                    + 7 * len(args.bodies)
                    + (5 if "moon" in args.bodies and "sun" in args.bodies else 0)
                    + len(pairs) * (3 + 2 * args.harmonics + len(ASPECTS))
                )
                result = {
                    "dry_run": True,
                    "start_utc": iso_utc(start),
                    "end_utc": iso_utc(end),
                    "step_hours": args.step_hours,
                    "estimated_rows": estimated_rows,
                    "estimated_feature_columns": estimated_columns,
                    "estimated_cells": estimated_rows * estimated_columns,
                    "within_memory_safety_limit": estimated_rows * estimated_columns
                    <= MAX_BUILD_CELLS,
                    "kernel_path": str(Path(args.kernel).expanduser().resolve()),
                    "kernel_sha256": (
                        sha256_file(args.kernel)
                        if Path(args.kernel).expanduser().is_file()
                        else None
                    ),
                }
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
                return 0
            backend = SkyfieldEphemeris(args.kernel)
            manifest = write_feature_csv(
                backend,
                start,
                end,
                args.out,
                step_hours=args.step_hours,
                bodies=args.bodies,
                pairs=pairs,
                harmonics=args.harmonics,
                aspect_sigma_deg=args.aspect_sigma,
                allow_pre_utc=args.allow_pre_utc,
                overwrite=args.overwrite,
                max_rows=args.max_rows,
            )
            print(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
            return 0

        if args.history_command == "research":
            feature_manifest = args.feature_manifest or f"{args.features}.manifest.json"
            result_output = safe_output_path(args.out, "result output")
            registry_output = safe_output_path(args.trial_registry, "trial registry")
            controls_supplied = _validate_control_option_pair(args.controls, args.controls_catalog)
            hypothesis = _load_json_object(args.hypothesis, "hypothesis manifest")
            incremental_enabled = incremental_model_enabled(hypothesis)
            if incremental_enabled and not controls_supplied:
                raise ResearchError(
                    "incremental_model 启用时必须提供 --controls 与 --controls-catalog"
                )
            if controls_supplied and not incremental_enabled:
                raise ResearchError(
                    "incremental_model 未启用时禁止提供 --controls/--controls-catalog"
                )
            distinct_paths = {
                "features": args.features,
                "feature_manifest": feature_manifest,
                "targets": args.targets,
                "catalog": args.catalog,
                "hypothesis": args.hypothesis,
                "trial_registry": registry_output,
                "result_output": result_output,
            }
            if controls_supplied:
                distinct_paths["controls"] = args.controls
                distinct_paths["controls_catalog"] = args.controls_catalog
            ensure_distinct_paths(distinct_paths)
            incremental_kwargs = (
                {
                    "controls_csv": args.controls,
                    "controls_catalog_json": args.controls_catalog,
                }
                if controls_supplied
                else {}
            )
            result = run_point_in_time_research(
                args.features,
                args.targets,
                args.catalog,
                args.hypothesis,
                registry_output,
                feature_manifest,
                **incremental_kwargs,
            )
            _write_result(str(result_output), result, args.overwrite)
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
    except ResearchError as exc:
        print(f"研究输入错误: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    for _stream_name in ("stdin", "stdout", "stderr"):
        _stream = getattr(sys, _stream_name)
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="strict")
    raise SystemExit(main())
