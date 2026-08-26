#!/usr/bin/env python3
"""Compatible facade for auditable historical astronomy and market research.

The implementation is split across focused ``research_*`` modules. This facade
keeps every existing import path stable for the CLI, tests, and downstream users.
"""

from __future__ import annotations

# Preserve the original module's public import surface, including names exposed
# incidentally by its standard-library imports. Downstream code should prefer the
# documented research functions and constants below.
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

if __package__:  # package import
    from .research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_BUILD_CELLS,
        MAX_CONFIG_BYTES,
        MAX_KERNEL_BYTES,
        MAX_MATRIX_CELLS,
        MAX_PLACEBO_OPERATIONS,
        MAX_RESEARCH_FILE_BYTES,
        MAX_RESEARCH_ROWS,
        RESEARCH_SCHEMA_VERSION,
        STRICT_UTC_START,
        ResearchError,
        _atomic_write_text,
        _commit_temp_file,
        ensure_distinct_paths,
        input_file_path,
        iso_utc,
        minimum_angle_deg,
        parse_utc,
        safe_output_path,
        sha256_file,
        signed_angle_deg,
        snapshot_input_files,
    )
    from .research_contracts import (
        CATALOG_REQUIRED,
        TARGET_REQUIRED,
        _asof_join,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        target_intervals_overlap,
        validate_catalog,
        validate_feature_manifest,
        validate_hypothesis,
    )
    from .research_ephemeris import (
        BODY_ORDER,
        BODY_TARGETS,
        DEFAULT_BODIES,
        SkyfieldEphemeris,
    )
    from .research_features import (
        ASPECTS,
        DEFAULT_PAIRS,
        aspect_score,
        canonical_pair,
        features_from_state,
        write_feature_csv,
    )
    from .research_registry import (
        _git_command,
        _git_is_ancestor,
        _git_state,
        append_trial_registry,
        code_source_sha256,
    )
    from .research_runner import (
        _run_point_in_time_research_impl,
        run_point_in_time_research,
    )
    from .research_statistics import (
        _ic,
        _rank,
        _strategy_metrics,
        bh_adjust,
        pearson,
        spearman,
    )
else:  # direct scripts import
    from research_common import (
        ASTRO_SCHEMA_VERSION,
        MAX_BUILD_CELLS,
        MAX_CONFIG_BYTES,
        MAX_KERNEL_BYTES,
        MAX_MATRIX_CELLS,
        MAX_PLACEBO_OPERATIONS,
        MAX_RESEARCH_FILE_BYTES,
        MAX_RESEARCH_ROWS,
        RESEARCH_SCHEMA_VERSION,
        STRICT_UTC_START,
        ResearchError,
        _atomic_write_text,
        _commit_temp_file,
        ensure_distinct_paths,
        input_file_path,
        iso_utc,
        minimum_angle_deg,
        parse_utc,
        safe_output_path,
        sha256_file,
        signed_angle_deg,
        snapshot_input_files,
    )
    from research_contracts import (
        CATALOG_REQUIRED,
        TARGET_REQUIRED,
        _asof_join,
        _load_feature_rows,
        _load_json_object,
        _load_target_rows,
        _split_rows,
        target_intervals_overlap,
        validate_catalog,
        validate_feature_manifest,
        validate_hypothesis,
    )
    from research_ephemeris import (
        BODY_ORDER,
        BODY_TARGETS,
        DEFAULT_BODIES,
        SkyfieldEphemeris,
    )
    from research_features import (
        ASPECTS,
        DEFAULT_PAIRS,
        aspect_score,
        canonical_pair,
        features_from_state,
        write_feature_csv,
    )
    from research_registry import (
        _git_command,
        _git_is_ancestor,
        _git_state,
        append_trial_registry,
        code_source_sha256,
    )
    from research_runner import (
        _run_point_in_time_research_impl,
        run_point_in_time_research,
    )
    from research_statistics import (
        _ic,
        _rank,
        _strategy_metrics,
        bh_adjust,
        pearson,
        spearman,
    )


# Match the original ``from historical_research import *`` surface exactly.
__all__ = [
    "ASPECTS",
    "ASTRO_SCHEMA_VERSION",
    "BODY_ORDER",
    "BODY_TARGETS",
    "CATALOG_REQUIRED",
    "DEFAULT_BODIES",
    "DEFAULT_PAIRS",
    "MAX_BUILD_CELLS",
    "MAX_CONFIG_BYTES",
    "MAX_KERNEL_BYTES",
    "MAX_MATRIX_CELLS",
    "MAX_PLACEBO_OPERATIONS",
    "MAX_RESEARCH_FILE_BYTES",
    "MAX_RESEARCH_ROWS",
    "RESEARCH_SCHEMA_VERSION",
    "STRICT_UTC_START",
    "TARGET_REQUIRED",
    "Any",
    "Iterable",
    "Path",
    "ResearchError",
    "SkyfieldEphemeris",
    "annotations",
    "append_trial_registry",
    "aspect_score",
    "bh_adjust",
    "bisect_right",
    "canonical_pair",
    "code_source_sha256",
    "csv",
    "datetime",
    "ensure_distinct_paths",
    "errno",
    "features_from_state",
    "hashlib",
    "importlib",
    "input_file_path",
    "iso_utc",
    "json",
    "math",
    "minimum_angle_deg",
    "os",
    "pairwise",
    "parse_utc",
    "pearson",
    "platform",
    "random",
    "re",
    "run_point_in_time_research",
    "safe_output_path",
    "sha256_file",
    "shutil",
    "signed_angle_deg",
    "snapshot_input_files",
    "spearman",
    "stat",
    "statistics",
    "subprocess",
    "suppress",
    "target_intervals_overlap",
    "tempfile",
    "timedelta",
    "timezone",
    "uuid",
    "validate_catalog",
    "validate_feature_manifest",
    "validate_hypothesis",
    "write_feature_csv",
]

# Private names were importable explicitly before the split and remain so. This
# tuple also makes the compatibility intent visible to static analysis without
# exposing private names through ``import *``.
_COMPAT_PRIVATE_EXPORTS = (
    _asof_join,
    _atomic_write_text,
    _commit_temp_file,
    _git_command,
    _git_is_ancestor,
    _git_state,
    _ic,
    _load_feature_rows,
    _load_json_object,
    _load_target_rows,
    _rank,
    _run_point_in_time_research_impl,
    _split_rows,
    _strategy_metrics,
)
