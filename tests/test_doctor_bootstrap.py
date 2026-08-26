from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import bootstrap
import cli_support
import destiny_analyzer
import output_support
import pytest


def _engine_versions(
    *, skyfield: str | None, numpy_version: str | None = "expected"
) -> dict[str, str | None]:
    return {
        "destiny_schema": output_support.SCHEMA_VERSION,
        "destiny_package": "2.2.0",
        "lunar_python": "1.4.8",
        "tzdata": "2026.3",
        "httpx": None,
        "skyfield": skyfield,
        "numpy": (
            output_support._expected_numpy_version()
            if numpy_version == "expected"
            else numpy_version
        ),
        "iztro": None,
    }


@pytest.mark.parametrize("mode", ["core", "research", "all"])
def test_doctor_mode_parser_accepts_exactly_one_mode(mode: str) -> None:
    flags, args = cli_support._parse_global_flags([f"--{mode}", "--json"])

    assert flags["doctor_mode"] == mode
    assert flags["json"] is True
    assert args == []


def test_doctor_mode_parser_rejects_conflicts() -> None:
    with pytest.raises(cli_support.CliError, match="只能选择一个"):
        cli_support._parse_global_flags(["--core", "--research"])


def test_doctor_report_separates_core_research_and_all_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(output_support, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(output_support.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        output_support,
        "engine_versions",
        lambda **_kwargs: _engine_versions(skyfield="1.55"),
    )
    monkeypatch.setattr(
        output_support.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __version__=(output_support._expected_numpy_version() if name == "numpy" else "1.55")
        ),
    )

    report = output_support.doctor_report("research")

    assert report["selected_mode"] == "research"
    assert report["selected_mode_ready"] is True
    assert report["ready_core"] is True
    assert report["ready_research"] is True
    assert report["ready_all_engines"] is False
    assert report["readiness"] == {"core": True, "research": True, "all": False}
    assert report["checks"]["skyfield"] == {
        "checked": True,
        "ok": True,
        "status": "ready",
        "installed_version": "1.55",
        "loaded_version": "1.55",
        "required_version": "1.55",
        "version": "1.55",
        "import_error_type": None,
        "needed_for": "optional historical astronomy research runtime",
        "kernel_required_for_this_check": False,
    }
    expected_numpy = output_support._expected_numpy_version()
    assert report["checks"]["numpy"] == {
        "checked": True,
        "ok": True,
        "status": "ready",
        "installed_version": expected_numpy,
        "loaded_version": expected_numpy,
        "required_version": expected_numpy,
        "version": expected_numpy,
        "import_error_type": None,
    }
    assert report["research_data"]["checked"] is False
    assert report["research_data"]["ready"] is None
    assert report["all_engines_checked"] is False
    assert report["research_runtime_checked"] is True
    assert report["checks"]["node"]["checked"] is False
    assert report["checks"]["node"]["status"] == "not_checked"
    assert report["checks"]["npm"]["checked"] is False
    assert report["checks"]["iztro"]["checked"] is False
    assert report["checks"]["iztro"]["status"] == "not_checked"


@pytest.mark.parametrize("mode", ["core", "research"])
def test_narrow_doctor_profiles_never_probe_node_or_iztro(
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(output_support, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        output_support,
        "engine_versions",
        lambda **_kwargs: _engine_versions(skyfield="1.55"),
    )

    def forbidden_probe(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("narrow doctor profile attempted a Node probe")

    monkeypatch.setattr(output_support.shutil, "which", forbidden_probe)
    monkeypatch.setattr(output_support.subprocess, "run", forbidden_probe)

    report = output_support.doctor_report(mode)

    assert report["selected_mode_ready"] is True
    assert report["all_engines_checked"] is False
    assert report["ready_all_engines"] is False
    for check_name in ("node", "npm", "iztro"):
        assert report["checks"][check_name]["checked"] is False
        assert report["checks"][check_name]["status"] == "not_checked"


def test_core_doctor_never_probes_optional_research_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_queries: list[str] = []

    def fake_version(name: str) -> str:
        metadata_queries.append(name)
        if name in {"numpy", "skyfield"}:
            raise AssertionError("core doctor probed an optional research distribution")
        return {
            "destiny-agent-skill": "2.2.0",
            "lunar_python": "1.4.8",
            "tzdata": "2026.3",
            "httpx": "0.28.1",
        }[name]

    def forbidden_probe(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("core doctor imported or spawned an optional runtime")

    output_support.engine_versions.cache_clear()
    monkeypatch.setattr(output_support.importlib.metadata, "version", fake_version)
    monkeypatch.setattr(output_support.importlib, "import_module", forbidden_probe)
    monkeypatch.setattr(output_support.shutil, "which", forbidden_probe)
    monkeypatch.setattr(output_support.subprocess, "run", forbidden_probe)
    try:
        report = output_support.doctor_report("core")
    finally:
        output_support.engine_versions.cache_clear()

    assert report["selected_mode_ready"] is True
    assert report["research_runtime_checked"] is False
    assert report["checks"]["numpy"]["status"] == "not_checked"
    assert report["checks"]["skyfield"]["status"] == "not_checked"
    assert "numpy" not in metadata_queries and "skyfield" not in metadata_queries


@pytest.mark.parametrize(
    ("python_version", "expected"),
    [
        ((3, 10), "2.2.6"),
        ((3, 11), "2.4.6"),
        ((3, 12), "2.5.2"),
        ((3, 14), "2.5.2"),
    ],
)
def test_numpy_marker_expectations(python_version: tuple[int, int], expected: str) -> None:
    assert output_support._expected_numpy_version(python_version) == expected


@pytest.mark.parametrize(
    ("installed", "import_failure", "expected_status"),
    [
        (None, False, "missing"),
        ("0.0.0", False, "version_mismatch"),
        ("expected", True, "import_failed"),
    ],
)
def test_research_doctor_fails_cleanly_for_numpy_runtime_problems(
    installed: str | None,
    import_failure: bool,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = output_support._expected_numpy_version()
    installed_version = expected if installed == "expected" else installed
    monkeypatch.setattr(
        output_support,
        "engine_versions",
        lambda **_kwargs: _engine_versions(skyfield="1.55", numpy_version=installed_version),
    )

    def fake_import(name: str) -> SimpleNamespace:
        if name == "skyfield":
            return SimpleNamespace(__version__="1.55")
        if import_failure:
            raise OSError("synthetic binary loader failure")
        raise AssertionError("NumPy should not be imported when metadata is missing/mismatched")

    monkeypatch.setattr(output_support.importlib, "import_module", fake_import)

    report = output_support.doctor_report("research")

    check = report["checks"]["numpy"]
    assert report["selected_mode_ready"] is False
    assert report["ready_core"] is True
    assert report["ready_research"] is False
    assert check["ok"] is False
    assert check["status"] == expected_status
    assert check["installed_version"] == installed_version
    assert check["required_version"] == expected
    if import_failure:
        assert check["import_error_type"] == "OSError"


def _write_node_runtime_fixture(
    root: Path,
    *,
    installed_name: str = "iztro",
    installed_version: str = "2.5.8",
    package_text: str | None = None,
) -> None:
    (root / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/iztro": {"version": "2.5.8"},
                }
            }
        ),
        encoding="utf-8",
    )
    if package_text is None:
        package_text = json.dumps({"name": installed_name, "version": installed_version})
    package_path = root / "node_modules" / "iztro" / "package.json"
    package_path.parent.mkdir(parents=True)
    package_path.write_text(package_text, encoding="utf-8")


def _patch_healthy_core_and_node(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    require_returncode: int = 0,
) -> list[dict[str, str]]:
    node_envs: list[dict[str, str]] = []

    def fake_which(name: str) -> str | None:
        return f"/tools/{name}" if name in {"node", "npm"} else None

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        node_envs.append(dict(kwargs["env"]))
        if command[1:] == ["--version"]:
            return SimpleNamespace(returncode=0, stdout="v22.1.0\n", stderr="")
        assert command[1:] == ["-e", "require('iztro')"]
        return SimpleNamespace(returncode=require_returncode, stdout="", stderr="")

    monkeypatch.setattr(output_support, "ROOT_DIR", root)
    monkeypatch.setattr(output_support.shutil, "which", fake_which)
    monkeypatch.setattr(output_support.subprocess, "run", fake_run)
    monkeypatch.setattr(
        output_support,
        "engine_versions",
        lambda **_kwargs: _engine_versions(skyfield="1.55"),
    )
    return node_envs


def test_doctor_requires_pinned_iztro_metadata_and_load_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_node_runtime_fixture(tmp_path)
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-node")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-node")
    node_envs = _patch_healthy_core_and_node(tmp_path, monkeypatch)

    report = output_support.doctor_report("all")

    assert report["selected_mode_ready"] is True
    assert report["ready_all_engines"] is True
    assert report["checks"]["iztro"] == {
        "checked": True,
        "ok": True,
        "status": "ready",
        "expected_name": "iztro",
        "expected_version": "2.5.8",
        "installed_name": "iztro",
        "installed_version": "2.5.8",
        "version": "2.5.8",
        "metadata_ok": True,
        "load_ok": True,
        "path": str(tmp_path / "node_modules" / "iztro" / "package.json"),
    }
    assert len(node_envs) == 2
    assert all("DESTINY_SENTINEL_SECRET" not in env for env in node_envs)
    assert all("MINIMAX_API_KEY" not in env for env in node_envs)


@pytest.mark.parametrize(
    ("fixture", "require_returncode", "expected_status"),
    [
        ("missing", 0, "missing"),
        ("corrupt", 0, "invalid_package_json"),
        ("name", 0, "name_mismatch"),
        ("version", 0, "version_mismatch"),
        ("load", 7, "require_failed"),
    ],
)
def test_doctor_rejects_unusable_iztro_without_raising(
    fixture: str,
    require_returncode: int,
    expected_status: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if fixture == "corrupt":
        _write_node_runtime_fixture(tmp_path, package_text="{")
    elif fixture == "name":
        _write_node_runtime_fixture(tmp_path, installed_name="not-iztro")
    elif fixture == "version":
        _write_node_runtime_fixture(tmp_path, installed_version="0.0.0")
    elif fixture == "load":
        _write_node_runtime_fixture(tmp_path)
    else:
        (tmp_path / "package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/iztro": {"version": "2.5.8"}}}),
            encoding="utf-8",
        )
    _patch_healthy_core_and_node(
        tmp_path,
        monkeypatch,
        require_returncode=require_returncode,
    )

    report = output_support.doctor_report("all")

    assert report["selected_mode_ready"] is False
    assert report["ready_all_engines"] is False
    assert report["checks"]["iztro"]["ok"] is False
    assert report["checks"]["iztro"]["status"] == expected_status
    assert report["checks"]["iztro"]["expected_version"] == "2.5.8"


def test_corrupt_iztro_cli_is_json_and_nonzero_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_node_runtime_fixture(tmp_path, package_text="not-json")
    _patch_healthy_core_and_node(tmp_path, monkeypatch)

    code = asyncio.run(destiny_analyzer.main(["doctor", "--all", "--json"]))
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out)["checks"]["iztro"]["status"] == "invalid_package_json"
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("argv", "expected_mode", "expected_code"),
    [
        (["doctor", "--json"], "all", 1),
        (["doctor", "--core", "--json"], "core", 0),
        (["doctor", "--research", "--json"], "research", 0),
        (["doctor", "--all", "--json"], "all", 1),
    ],
)
def test_doctor_exit_code_uses_selected_readiness(
    argv: list[str],
    expected_mode: str,
    expected_code: int,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    readiness = {"core": True, "research": True, "all": False}

    def fake_report(mode: str = "all") -> dict[str, object]:
        return {
            **output_support.base_result("doctor"),
            "selected_mode": mode,
            "selected_mode_ready": readiness[mode],
            "ready_core": readiness["core"],
            "ready_research": readiness["research"],
            "ready_all_engines": readiness["all"],
            "readiness": readiness,
            "checks": {},
        }

    monkeypatch.setattr(destiny_analyzer, "doctor_report", fake_report)

    code = asyncio.run(destiny_analyzer.main(argv))
    result = json.loads(capsys.readouterr().out)

    assert code == expected_code
    assert result["selected_mode"] == expected_mode


def test_doctor_modes_are_rejected_for_other_commands() -> None:
    with pytest.raises(cli_support.CliError, match="仅适用于 doctor"):
        asyncio.run(destiny_analyzer.main(["calendar", "2026", "8", "26", "--core"]))


def test_installer_selection_requires_current_lock_for_uv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/opt/uv" if name == "uv" else None)
    monkeypatch.setattr(bootstrap, "_uv_lock_is_current", lambda _path, **_kwargs: (True, None))

    assert bootstrap._select_installer("auto") == ("uv", "/opt/uv", None)
    assert bootstrap._select_installer("uv") == ("uv", "/opt/uv", None)

    monkeypatch.setattr(
        bootstrap, "_uv_lock_is_current", lambda _path, **_kwargs: (False, "changed")
    )
    selected, uv_path, reason = bootstrap._select_installer("auto")
    assert selected == "pip"
    assert uv_path is None
    assert reason is not None and "stale" in reason and "changed" in reason
    with pytest.raises(ValueError, match="stale"):
        bootstrap._select_installer("uv")


def test_auto_installer_falls_back_when_uv_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _name: None)

    assert bootstrap._select_installer("auto") == (
        "pip",
        None,
        "uv executable was not found",
    )
    with pytest.raises(ValueError, match="not found"):
        bootstrap._select_installer("uv")


def test_uv_lock_check_uses_read_only_check_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command: list[str], **kwargs: object) -> Result:
        calls.append((command, kwargs))
        return Result()

    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-uv")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-reach-uv")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("PIP_INDEX_URL", "https://packages.invalid/simple")
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("UV_SENTINEL_SECRET", "must-not-reach-uv")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "required-index-password")

    assert bootstrap._uv_lock_is_current("/opt/uv") == (True, None)
    assert calls[0][0] == ["/opt/uv", "lock", "--check", "--project", str(tmp_path)]
    assert calls[0][1]["cwd"] == tmp_path
    env = calls[0][1]["env"]
    assert "DESTINY_SENTINEL_SECRET" not in env
    assert "AWS_ACCESS_KEY_ID" not in env
    assert "UV_SENTINEL_SECRET" not in env
    assert env["HTTPS_PROXY"] == "http://proxy.invalid"
    assert "PIP_INDEX_URL" not in env
    assert env["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert env["PIP_NO_CACHE_DIR"] == "1"
    assert "UV_INDEX_PRIVATE_PASSWORD" not in env
    assert all(key.upper() in bootstrap._INSTALLER_ENV_KEYS for key in env)

    assert bootstrap._uv_lock_is_current("/opt/uv", allow_private_index_env=True) == (True, None)
    private_env = calls[1][1]["env"]
    assert private_env["PIP_INDEX_URL"] == "https://packages.invalid/simple"
    assert private_env["UV_INDEX_PRIVATE_PASSWORD"] == "required-index-password"


def test_default_installer_env_is_an_exact_operational_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(_command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-pip")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-pip")
    monkeypatch.setenv("GH_TOKEN", "must-not-reach-pip")
    monkeypatch.setenv("DATABASE_URL", "postgres://must-not-reach-pip")
    monkeypatch.setenv("SENTRY_DSN", "https://must-not-reach-pip")
    monkeypatch.setenv("KUBECONFIG", "/tmp/must-not-reach-pip")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/must-not-reach-pip.sock")
    monkeypatch.setenv("UNRELATED_BENIGN_SETTING", "must-not-reach-pip")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ca.pem"))
    monkeypatch.setenv("PIP_CERT", str(tmp_path / "pip-ca.pem"))
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.setenv("PIP_INDEX_URL", "https://packages.invalid/simple")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    monkeypatch.setenv("PIP_PROVIDER_TOKEN", "must-not-reach-pip")
    monkeypatch.setenv("UV_SENTINEL_SECRET", "must-not-reach-pip")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "required-index-password")

    bootstrap._run(["python", "-m", "pip", "--version"])

    env = calls[0]["env"]
    assert "DESTINY_SENTINEL_SECRET" not in env
    assert "MINIMAX_API_KEY" not in env
    assert "GH_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert "SENTRY_DSN" not in env
    assert "KUBECONFIG" not in env
    assert "SSH_AUTH_SOCK" not in env
    assert "UNRELATED_BENIGN_SETTING" not in env
    assert "PIP_PROVIDER_TOKEN" not in env
    assert "UV_SENTINEL_SECRET" not in env
    assert env["HTTPS_PROXY"] == "http://proxy.invalid"
    assert env["SSL_CERT_FILE"] == str(tmp_path / "ca.pem")
    assert env["PIP_CERT"] == str(tmp_path / "pip-ca.pem")
    assert env["PIP_NO_CACHE_DIR"] == "1"
    assert "PIP_INDEX_URL" not in env
    assert env["UV_CACHE_DIR"] == str(tmp_path / "uv-cache")
    assert "UV_INDEX_PRIVATE_PASSWORD" not in env
    assert all(key.upper() in bootstrap._INSTALLER_ENV_KEYS for key in env)


def test_run_routes_real_child_stdout_to_parent_stderr(
    capfd: pytest.CaptureFixture[str],
) -> None:
    bootstrap._run(
        [
            sys.executable,
            "-c",
            "import sys; print('child-stdout'); print('child-stderr', file=sys.stderr)",
        ]
    )

    captured = capfd.readouterr()
    assert captured.out == ""
    assert "child-stdout" in captured.err
    assert "child-stderr" in captured.err


def test_private_index_environment_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIP_INDEX_URL", "https://private.invalid/simple")
    monkeypatch.setenv("PIP_EXTRA_INDEX_URL", "https://extra.invalid/simple")
    monkeypatch.setenv("PIP_TRUSTED_HOST", "private.invalid")
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://uv-private.invalid/simple")
    monkeypatch.setenv("UV_INDEX_PRIVATE_USERNAME", "index-user")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "index-password")
    monkeypatch.setenv("UV_INDEX_PRIVATE_TOKEN", "must-never-pass")
    monkeypatch.setenv("UV_INDEX_PRIVATE_URL", "must-never-pass")
    monkeypatch.setenv("UV_PUBLISH_TOKEN", "must-never-pass")
    monkeypatch.setenv("NPM_TOKEN", "must-never-pass")
    monkeypatch.setenv("DATABASE_URL", "must-never-pass")

    default_env = bootstrap._installer_env()
    opted_in_env = bootstrap._installer_env(True)

    for key in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "UV_DEFAULT_INDEX",
        "UV_INDEX_PRIVATE_USERNAME",
        "UV_INDEX_PRIVATE_PASSWORD",
    ):
        assert key not in default_env
        assert key in opted_in_env
    for key in (
        "UV_INDEX_PRIVATE_TOKEN",
        "UV_INDEX_PRIVATE_URL",
        "UV_PUBLISH_TOKEN",
        "NPM_TOKEN",
        "DATABASE_URL",
    ):
        assert key not in default_env
        assert key not in opted_in_env
    assert all(
        key.upper() in bootstrap._INSTALLER_ENV_KEYS
        or key.upper() in bootstrap._PRIVATE_INDEX_ENV_KEYS
        or bootstrap._UV_NAMED_INDEX_CREDENTIAL.fullmatch(key.upper()) is not None
        for key in opted_in_env
    )


def test_node_version_probe_uses_minimal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(_command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="v22.0.0\n")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/tools")
    monkeypatch.setenv("TMPDIR", "/tmp/safe")
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-node")
    monkeypatch.setenv("MINIMAX_API_KEY", "must-not-reach-node")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted.cjs")

    assert bootstrap._node_major("/tools/node") == 22

    env = calls[0]["env"]
    assert env["PATH"] == "/tools"
    assert env["TMPDIR"] == "/tmp/safe"
    assert "DESTINY_SENTINEL_SECRET" not in env
    assert "MINIMAX_API_KEY" not in env
    assert "NODE_OPTIONS" not in env
    assert all(key.upper() in bootstrap._NODE_ENV_KEYS for key in env)


def _prepare_bootstrap_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[list[str], dict[str, object]]]]:
    root = tmp_path / "project"
    venv_dir = tmp_path / "custom venv with spaces"
    python = bootstrap._venv_python(venv_dir)
    python.parent.mkdir(parents=True)
    python.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(bootstrap, "ROOT", root)
    monkeypatch.setattr(bootstrap, "_run", fake_run)
    return venv_dir, calls


@pytest.mark.parametrize(
    ("installer", "selection"),
    [
        ("uv", ("uv", "/opt/uv", None)),
        ("pip", ("pip", None, None)),
    ],
)
def test_full_bootstrap_stdout_is_one_json_document_for_every_installer(
    installer: str,
    selection: tuple[str, str | None, None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, _calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: selection,
    )

    def noisy_child(command: list[str], **_kwargs: object) -> None:
        print(f"child-log:{command[0]}", file=sys.stderr)

    monkeypatch.setattr(bootstrap, "_run", noisy_child)

    assert bootstrap.main(["--installer", installer, "--venv", str(venv_dir), "--skip-node"]) == 0

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["installer"] == installer
    assert summary["next_argv"][-3:] == ["doctor", "--core", "--json"]
    assert "child-log:" in captured.err


@pytest.mark.parametrize(
    ("platform", "expected_symlinks", "python_parts"),
    [
        ("linux", True, ("bin", "python")),
        ("win32", False, ("Scripts", "python.exe")),
    ],
)
def test_fresh_venv_uses_platform_safe_links_and_sanitized_ensurepip(
    platform: str,
    expected_symlinks: bool,
    python_parts: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "project"
    venv_dir = tmp_path / "fresh environment with spaces"
    builder_calls: list[dict[str, object]] = []
    created: list[Path] = []
    run_calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeEnvBuilder:
        def __init__(self, **kwargs: object) -> None:
            builder_calls.append(kwargs)

        def create(self, path: Path) -> None:
            created.append(path)

    def fake_run(command: list[str], **kwargs: object) -> None:
        run_calls.append((command, kwargs))

    monkeypatch.setattr(bootstrap, "ROOT", root)
    monkeypatch.setattr(bootstrap.sys, "platform", platform)
    monkeypatch.setattr(bootstrap.venv, "EnvBuilder", FakeEnvBuilder)
    monkeypatch.setattr(bootstrap, "_run", fake_run)
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: ("pip", None, None),
    )
    monkeypatch.setenv("PATH", "/tools")
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("PIP_NO_CACHE_DIR", "1")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private.invalid/simple")
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-ensurepip")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-ensurepip")
    monkeypatch.setenv("KUBECONFIG", "/tmp/must-not-reach-ensurepip")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/must-not-reach-ensurepip.sock")

    assert bootstrap.main(["--installer", "pip", "--venv", str(venv_dir), "--skip-node"]) == 0

    assert builder_calls == [{"with_pip": False, "symlinks": expected_symlinks}]
    assert created == [venv_dir.resolve()]
    expected_python = str(venv_dir.resolve().joinpath(*python_parts))
    assert run_calls[0][0] == [
        expected_python,
        "-m",
        "ensurepip",
        "--upgrade",
        "--default-pip",
    ]
    ensurepip_env = run_calls[0][1]["env"]
    assert ensurepip_env["PATH"] == "/tools"
    assert ensurepip_env["TEMP"] == str(tmp_path / "temp")
    assert ensurepip_env["HTTPS_PROXY"] == "http://proxy.invalid"
    assert ensurepip_env["PIP_NO_CACHE_DIR"] == "1"
    for forbidden in (
        "PIP_INDEX_URL",
        "DESTINY_SENTINEL_SECRET",
        "DATABASE_URL",
        "KUBECONFIG",
        "SSH_AUTH_SOCK",
    ):
        assert forbidden not in ensurepip_env
    assert all(key.upper() in bootstrap._INSTALLER_ENV_KEYS for key in ensurepip_env)
    summary = json.loads(capsys.readouterr().out)
    assert summary["allow_private_index_env"] is False


def test_bootstrap_uv_sync_honors_custom_venv_and_extras(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-uv")
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: ("uv", "/opt/uv", None),
    )

    assert (
        bootstrap.main(
            [
                "--installer",
                "uv",
                "--venv",
                str(venv_dir),
                "--llm",
                "--research",
                "--dev",
                "--skip-node",
            ]
        )
        == 0
    )

    assert calls[0][0] == [
        "/opt/uv",
        "sync",
        "--frozen",
        "--active",
        "--project",
        str(bootstrap.ROOT),
        "--no-default-groups",
        "--extra",
        "llm",
        "--extra",
        "research",
        "--extra",
        "dev",
    ]
    assert calls[0][1]["env"]["VIRTUAL_ENV"] == str(venv_dir)
    assert "DESTINY_SENTINEL_SECRET" not in calls[0][1]["env"]
    assert "PIP_INDEX_URL" not in calls[0][1]["env"]
    summary = json.loads(capsys.readouterr().out)
    assert summary["installer"] == "uv"
    assert summary["installer_requested"] == "uv"
    assert summary["allow_private_index_env"] is False
    assert summary["next_argv"][-3:] == ["doctor", "--research", "--json"]
    assert summary["next"] == bootstrap._display_command(summary["next_argv"])


def test_bootstrap_pip_path_remains_independent_of_uv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: ("pip", None, None),
    )

    assert (
        bootstrap.main(["--installer", "pip", "--venv", str(venv_dir), "--research", "--skip-node"])
        == 0
    )

    python = str(bootstrap._venv_python(venv_dir))
    assert calls[0][0][:4] == [python, "-m", "pip", "install"]
    assert "pip==26.2" in calls[0][0]
    assert "PIP_INDEX_URL" not in calls[0][1]["env"]
    assert calls[1][0] == [
        python,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-e",
        f"{bootstrap.ROOT}[research]",
    ]
    summary = json.loads(capsys.readouterr().out)
    assert summary["installer"] == "pip"
    assert summary["extras"] == ["research"]
    assert summary["allow_private_index_env"] is False
    assert summary["next_argv"][-3:] == ["doctor", "--research", "--json"]
    assert summary["next"] == bootstrap._display_command(summary["next_argv"])


def test_bootstrap_private_index_opt_in_is_narrow_and_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    selections: list[tuple[str, bool]] = []

    def fake_select(requested: str, *, allow_private_index_env: bool) -> tuple[str, None, None]:
        selections.append((requested, allow_private_index_env))
        return "pip", None, None

    monkeypatch.setattr(bootstrap, "_select_installer", fake_select)
    monkeypatch.setenv("PIP_INDEX_URL", "https://private.invalid/simple")
    monkeypatch.setenv("UV_INDEX_PRIVATE_USERNAME", "index-user")
    monkeypatch.setenv("UV_INDEX_PRIVATE_PASSWORD", "index-password")
    monkeypatch.setenv("DATABASE_URL", "must-never-pass")
    monkeypatch.setenv("SENTRY_DSN", "must-never-pass")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/must-never-pass.sock")

    assert (
        bootstrap.main(
            [
                "--installer",
                "pip",
                "--allow-private-index-env",
                "--venv",
                str(venv_dir),
                "--skip-node",
            ]
        )
        == 0
    )

    assert selections == [("pip", True)]
    for _command, kwargs in calls[:2]:
        env = kwargs["env"]
        assert env["PIP_INDEX_URL"] == "https://private.invalid/simple"
        assert env["UV_INDEX_PRIVATE_USERNAME"] == "index-user"
        assert env["UV_INDEX_PRIVATE_PASSWORD"] == "index-password"
        assert "DATABASE_URL" not in env
        assert "SENTRY_DSN" not in env
        assert "SSH_AUTH_SOCK" not in env
    summary = json.loads(capsys.readouterr().out)
    assert summary["allow_private_index_env"] is True
    assert summary["next_argv"][-3:] == ["doctor", "--core", "--json"]


def test_bootstrap_node_commands_never_receive_parent_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: ("pip", None, None),
    )
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda name: f"/tools/{name}" if name in {"node", "npm"} else None,
    )
    major_envs: list[dict[str, str]] = []

    def fake_node_major(_node: str, *, env: dict[str, str]) -> int:
        major_envs.append(env)
        return 22

    monkeypatch.setattr(bootstrap, "_node_major", fake_node_major)
    monkeypatch.setenv("PATH", "/tools")
    monkeypatch.setenv("TMPDIR", "/tmp/safe")
    monkeypatch.setenv("DESTINY_SENTINEL_SECRET", "must-not-reach-node")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-reach-node")
    monkeypatch.setenv("NODE_OPTIONS", "--require=/tmp/untrusted.cjs")

    assert bootstrap.main(["--installer", "pip", "--venv", str(venv_dir)]) == 0

    assert len(major_envs) == 1
    assert major_envs[0]["PATH"] == "/tools"
    assert major_envs[0]["TMPDIR"] == "/tmp/safe"
    assert "DESTINY_SENTINEL_SECRET" not in major_envs[0]
    assert "DEEPSEEK_API_KEY" not in major_envs[0]
    assert "NODE_OPTIONS" not in major_envs[0]
    assert all(key.upper() in bootstrap._NODE_ENV_KEYS for key in major_envs[0])
    npm_calls = [item for item in calls if item[0][0] == "/tools/npm"]
    assert [item[0][1:] for item in npm_calls] == [["ci", "--ignore-scripts"]]
    for _command, kwargs in npm_calls:
        env = kwargs["env"]
        assert env["PATH"] == "/tools"
        assert env["TMPDIR"] == "/tmp/safe"
        assert "DESTINY_SENTINEL_SECRET" not in env
        assert "DEEPSEEK_API_KEY" not in env
        assert "NODE_OPTIONS" not in env
        assert all(key.upper() in bootstrap._NODE_ENV_KEYS for key in env)
    node_smoke_calls = [
        item for item in calls if item[0] == ["/tools/node", "-e", "require('iztro')"]
    ]
    assert len(node_smoke_calls) == 1
    assert node_smoke_calls[0][1]["timeout"] == 10
    smoke_env = node_smoke_calls[0][1]["env"]
    assert "DESTINY_SENTINEL_SECRET" not in smoke_env
    assert "DEEPSEEK_API_KEY" not in smoke_env
    assert "NODE_OPTIONS" not in smoke_env
    assert all(key.upper() in bootstrap._NODE_ENV_KEYS for key in smoke_env)
    summary = json.loads(capsys.readouterr().out)
    assert summary["next_argv"][-3:] == ["doctor", "--all", "--json"]


def test_direct_node_smoke_cannot_receive_npmrc_lifecycle_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    venv_dir, calls = _prepare_bootstrap_main(tmp_path, monkeypatch)
    home = tmp_path / "home with npmrc"
    home.mkdir()
    (home / ".npmrc").write_text(
        "registry=https://private.invalid/\n"
        "proxy=https://user:credential@proxy.invalid/\n"
        "//private.invalid/:_authToken=credential-token\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        bootstrap,
        "_select_installer",
        lambda _requested, **_kwargs: ("pip", None, None),
    )
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda name: f"/tools/{name}" if name in {"node", "npm"} else None,
    )
    monkeypatch.setattr(bootstrap, "_node_major", lambda _node, **_kwargs: 22)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/tools")
    monkeypatch.setenv("npm_config_registry", "https://parent-private.invalid/")
    monkeypatch.setenv("npm_config_proxy", "https://parent:credential@proxy.invalid/")
    monkeypatch.setenv("NPM_TOKEN", "parent-token")
    monkeypatch.setenv("PIP_INDEX_URL", "https://python-private.invalid/simple")

    assert bootstrap.main(["--installer", "pip", "--venv", str(venv_dir)]) == 0

    smoke_call = next(
        item for item in calls if item[0] == ["/tools/node", "-e", "require('iztro')"]
    )
    smoke_env = smoke_call[1]["env"]
    assert smoke_call[1]["timeout"] == 10
    assert smoke_env["HOME"] == str(home)
    assert not any(key.lower().startswith("npm_config_") for key in smoke_env)
    assert "NPM_TOKEN" not in smoke_env
    assert "PIP_INDEX_URL" not in smoke_env
    assert not any(
        "credential" in value or "private.invalid" in value for value in smoke_env.values()
    )
    assert all(key.upper() in bootstrap._NODE_ENV_KEYS for key in smoke_env)
    summary = json.loads(capsys.readouterr().out)
    assert summary["node_runtime_installed"] is True


def test_bounded_run_propagates_node_smoke_failure_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7),
    )
    with pytest.raises(SystemExit) as failed:
        bootstrap._run(["/tools/node", "-e", "require('iztro')"], env={}, timeout=10)
    assert failed.value.code == 7

    def time_out(command: list[str], **_kwargs: object) -> None:
        raise bootstrap.subprocess.TimeoutExpired(command, 10)

    monkeypatch.setattr(bootstrap.subprocess, "run", time_out)
    with pytest.raises(SystemExit, match="timed out after 10s"):
        bootstrap._run(["/tools/node", "-e", "require('iztro')"], env={}, timeout=10)


def test_skip_node_help_promises_not_to_remove_existing_modules(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        bootstrap.main(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "existing node_modules is left untouched" in help_text
    assert "Node runtime verification" in help_text
    assert "--allow-private-index-env" in help_text
    assert "recognized pip/uv private-index" in help_text


def test_engine_metadata_separates_distribution_from_schema() -> None:
    versions = output_support.engine_versions()

    assert versions["destiny_schema"] == output_support.SCHEMA_VERSION
    assert "destiny_package" in versions
