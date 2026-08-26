from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import cli_support
import destiny_analyzer
import llm_provider
import output_support
import pytest


def test_analyzer_facade_reexports_extracted_interfaces() -> None:
    assert destiny_analyzer.call_llm is llm_provider.call_llm
    assert destiny_analyzer._provider_configs is llm_provider._provider_configs
    assert destiny_analyzer._parse_global_flags is cli_support._parse_global_flags
    assert destiny_analyzer.load_env_file is cli_support.load_env_file
    assert destiny_analyzer._print_result is output_support._print_result
    assert destiny_analyzer.doctor_report is output_support.doctor_report
    assert destiny_analyzer.CliError is cli_support.CliError


def test_provider_module_rejects_named_provider_host_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_API_URL", "https://attacker.invalid/v1/chat/completions")
    with pytest.raises(ValueError, match="host 不受信任"):
        llm_provider._provider_configs("system", "private-input")


def test_provider_fallback_occurs_only_when_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    if not llm_provider.HAS_HTTPX:
        pytest.skip("optional httpx adapter is not installed")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
    calls: list[str] = []

    class SyntheticResponse:
        def __init__(self, url: str) -> None:
            self.url = url

        def raise_for_status(self) -> None:
            if "minimax" in self.url:
                raise RuntimeError("synthetic failure")

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "fallback-ok"}}]}

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url: str, **_kwargs) -> SyntheticResponse:
            calls.append(url)
            return SyntheticResponse(url)

    monkeypatch.setattr(llm_provider.httpx, "AsyncClient", FakeClient)

    without_fallback = asyncio.run(llm_provider.call_llm("system", "data", provider="minimax"))
    assert without_fallback["status"] == "error"
    assert calls == ["https://api.minimax.io/anthropic/v1/messages"]

    calls.clear()
    with_fallback = asyncio.run(
        llm_provider.call_llm("system", "data", provider="minimax", allow_fallback=True)
    )
    assert with_fallback == {
        "status": "ok",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "text": "fallback-ok",
    }
    assert calls == [
        "https://api.minimax.io/anthropic/v1/messages",
        "https://api.deepseek.com/v1/chat/completions",
    ]


def test_flag_parser_separates_global_options_from_positionals() -> None:
    flags, clean = cli_support._parse_global_flags(
        ["1990", "--minute", "34", "1", "--json", "--sect", "1"]
    )
    assert clean == ["1990", "1"]
    assert flags["minute"] == 34
    assert flags["json"] is True
    assert flags["sect"] == 1


def test_flag_parser_requires_explicit_llm_provider_and_fallback() -> None:
    with pytest.raises(cli_support.CliError, match="显式指定"):
        cli_support._parse_global_flags(["--llm"])
    with pytest.raises(cli_support.CliError, match="必须与 --llm"):
        cli_support._parse_global_flags(["--llm-fallback"])


def test_env_file_ignores_unknown_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("UNRELATED_SECRET", raising=False)
    env_file = tmp_path / "destiny.env"
    env_file.write_text("MINIMAX_API_KEY=allowed\nUNRELATED_SECRET=do-not-load\n", encoding="utf-8")

    loaded = cli_support.load_env_file(env_file)

    assert loaded == ["MINIMAX_API_KEY"]
    assert os.environ["MINIMAX_API_KEY"] == "allowed"
    assert "UNRELATED_SECRET" not in os.environ


def test_json_renderer_writes_one_document_without_diagnostics(capsys) -> None:
    result = {**output_support.base_result("bazi"), "text": "chart"}

    output_support._print_result(result, json_mode=True)

    captured = capsys.readouterr()
    assert json.loads(captured.out) == result
    assert captured.out.count("\n{") == 0
    assert captured.err == ""


def test_doctor_keeps_optional_adapters_out_of_core_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(output_support, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(output_support.shutil, "which", lambda _name: None)
    monkeypatch.setattr(output_support.llm_provider, "HAS_HTTPX", False)
    monkeypatch.setattr(
        output_support,
        "engine_versions",
        lambda **_kwargs: {
            "destiny_schema": output_support.SCHEMA_VERSION,
            "destiny_package": "2.2.0",
            "lunar_python": "1.4.8",
            "tzdata": "2026.3",
            "httpx": None,
            "skyfield": None,
            "numpy": None,
            "iztro": None,
        },
    )

    report = output_support.doctor_report()

    assert report["ready_core"] is True
    assert report["ready_all_engines"] is False
    assert report["checks"]["httpx"]["ok"] is False
    assert report["checks"]["node"]["ok"] is False
    assert report["checks"]["iztro"]["ok"] is False
