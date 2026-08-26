from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import historical_research
import research_common
import research_contracts
import research_ephemeris
import research_features
import research_registry
import research_runner
import research_statistics

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

EXPECTED_PUBLIC_NAMES = {
    "ASPECTS",
    "ASTRO_SCHEMA_VERSION",
    "Any",
    "BODY_ORDER",
    "BODY_TARGETS",
    "CATALOG_REQUIRED",
    "DEFAULT_BODIES",
    "DEFAULT_PAIRS",
    "Iterable",
    "MAX_BUILD_CELLS",
    "MAX_CONFIG_BYTES",
    "MAX_KERNEL_BYTES",
    "MAX_MATRIX_CELLS",
    "MAX_PLACEBO_OPERATIONS",
    "MAX_RESEARCH_FILE_BYTES",
    "MAX_RESEARCH_ROWS",
    "Path",
    "RESEARCH_SCHEMA_VERSION",
    "ResearchError",
    "STRICT_UTC_START",
    "SkyfieldEphemeris",
    "TARGET_REQUIRED",
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
}


def test_historical_facade_preserves_public_surface_and_exact_implementations() -> None:
    assert {
        name for name in dir(historical_research) if not name.startswith("_")
    } == EXPECTED_PUBLIC_NAMES
    assert historical_research.ResearchError is research_common.ResearchError
    assert historical_research.SkyfieldEphemeris is research_ephemeris.SkyfieldEphemeris
    assert historical_research.features_from_state is research_features.features_from_state
    assert historical_research.validate_hypothesis is research_contracts.validate_hypothesis
    assert historical_research.pearson is research_statistics.pearson
    assert historical_research.append_trial_registry is research_registry.append_trial_registry
    assert (
        historical_research.run_point_in_time_research is research_runner.run_point_in_time_research
    )


def test_research_modules_share_one_error_type_and_keep_flat_dependency_direction() -> None:
    modules = (
        research_common,
        research_contracts,
        research_ephemeris,
        research_features,
        research_registry,
        research_runner,
        research_statistics,
    )
    assert all(module.ResearchError is research_common.ResearchError for module in modules)

    assert not any(name.startswith("research_") for name in vars(research_common))
    assert "research_features" not in vars(research_ephemeris)
    assert "research_runner" not in vars(research_features)
    assert "research_runner" not in vars(research_contracts)
    assert "research_runner" not in vars(research_statistics)
    assert "research_runner" not in vars(research_registry)


def _import_probe(cwd: Path, module_names: tuple[str, str]) -> dict:
    research_module, cli_module = module_names
    probe = f"""
import json
from datetime import datetime, timezone
import {research_module} as research
import {cli_module} as history_cli
state = {{
    'timestamp_utc': '2020-01-01T00:00:00Z',
    'bodies': {{
        'sun': {{
            'longitude_deg': 10.0,
            'latitude_deg': 0.0,
            'distance_au': 1.0,
            'longitude_velocity_deg_day': 1.0,
            'retrograde': False,
        }},
        'moon': {{
            'longitude_deg': 70.0,
            'latitude_deg': 1.0,
            'distance_au': 0.0025,
            'longitude_velocity_deg_day': 13.0,
            'retrograde': False,
            'illuminated_fraction': 0.25,
        }},
    }},
}}
print(json.dumps({{
    'schema': research.ASTRO_SCHEMA_VERSION,
    'error_type': research.ResearchError.__name__,
    'cli_prog': history_cli.build_parser().prog,
    'timestamp': research.iso_utc(datetime(2020, 1, 1, tzinfo=timezone.utc)),
    'features': research.features_from_state(state, (('sun', 'moon'),), harmonics=1),
}}, sort_keys=True, allow_nan=False))
"""
    process = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stderr == ""
    return json.loads(process.stdout)


def test_direct_script_and_package_import_paths_are_behaviorally_identical() -> None:
    direct = _import_probe(SCRIPTS_DIR, ("historical_research", "history_cli"))
    package = _import_probe(
        REPO_ROOT,
        ("scripts.historical_research", "scripts.history_cli"),
    )
    assert direct == package


def _package_import_failure_probe(*, prelude: str, operation: str) -> dict:
    probe = f"""
import importlib
import importlib.abc
import importlib.util
import json
import sys

sys.path[:0] = [{str(REPO_ROOT)!r}, {str(SCRIPTS_DIR)!r}]
{prelude}

class BrokenLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        raise ImportError('synthetic package-relative research failure')

class BrokenFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'scripts.research_common':
            return importlib.util.spec_from_loader(fullname, BrokenLoader())
        return None

sys.meta_path.insert(0, BrokenFinder())
caught = None
try:
{textwrap.indent(operation, "    ")}
except ImportError as exc:
    caught = exc

if caught is None:
    raise AssertionError('package import silently fell back to flat modules')
flat_modules = sorted(
    name
    for name in sys.modules
    if name in {{'historical_research', 'history_cli'}} or name.startswith('research_')
)
print(json.dumps({{'error': str(caught), 'flat_modules': flat_modules}}))
"""
    process = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stderr == ""
    return json.loads(process.stdout)


def test_package_submodule_import_error_never_falls_back_to_flat_modules() -> None:
    payload = _package_import_failure_probe(
        prelude="",
        operation="importlib.import_module('scripts.historical_research')",
    )
    assert payload == {
        "error": "synthetic package-relative research failure",
        "flat_modules": [],
    }


def test_package_history_cli_import_error_never_falls_back_to_flat_modules() -> None:
    payload = _package_import_failure_probe(
        prelude="",
        operation="importlib.import_module('scripts.history_cli')",
    )
    assert payload == {
        "error": "synthetic package-relative research failure",
        "flat_modules": [],
    }


def test_package_analyzer_history_dispatch_never_falls_back_to_flat_modules() -> None:
    payload = _package_import_failure_probe(
        prelude=("import asyncio\nanalyzer = importlib.import_module('scripts.destiny_analyzer')"),
        operation="asyncio.run(analyzer.main(['history', '--help']))",
    )
    assert payload == {
        "error": "synthetic package-relative research failure",
        "flat_modules": [],
    }
