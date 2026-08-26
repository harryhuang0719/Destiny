from __future__ import annotations

import asyncio
from pathlib import Path

import destiny_analyzer
import pytest


def test_named_provider_rejects_key_exfiltration_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_API_URL", "https://attacker.invalid/messages")
    with pytest.raises(ValueError, match="host 不受信任"):
        destiny_analyzer._provider_configs("system", "birth-data")


def test_custom_provider_requires_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("CUSTOM_API_KEY", "test-key")
    monkeypatch.setenv("CUSTOM_API_BASE", "http://localhost:8000/v1")
    monkeypatch.setenv("CUSTOM_MODEL", "test-model")
    with pytest.raises(ValueError, match="HTTPS"):
        destiny_analyzer._provider_configs("system", "birth-data")


def test_provider_failure_does_not_hop_without_explicit_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not destiny_analyzer.HAS_HTTPX:
        pytest.skip("optional httpx adapter is not installed")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
    calls: list[str] = []

    class FailedResponse:
        def raise_for_status(self) -> None:
            raise RuntimeError("synthetic failure")

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, **_kwargs):
            calls.append(url)
            return FailedResponse()

    monkeypatch.setattr(destiny_analyzer.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(destiny_analyzer.call_llm("system", "birth-data", provider="minimax"))
    assert result["status"] == "error"
    assert calls == ["https://api.minimax.io/anthropic/v1/messages"]


@pytest.mark.parametrize("timeout", ["nan", "inf", "-1", "1000000000"])
def test_llm_timeout_is_finite_and_bounded(monkeypatch: pytest.MonkeyPatch, timeout: str) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("DESTINY_LLM_TIMEOUT", timeout)
    with pytest.raises(ValueError, match="1-600"):
        asyncio.run(destiny_analyzer.call_llm("system", "data", provider="minimax"))


def test_explicit_env_file_has_size_bound(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("#" * (destiny_analyzer.MAX_ENV_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(destiny_analyzer.CliError, match="安全上限"):
        destiny_analyzer.load_env_file(env_file)
