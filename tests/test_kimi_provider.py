from __future__ import annotations

import json
from pathlib import Path

import pytest

from automm.llm import get_provider
from automm.llm.base import ProviderConfigError, ProviderError


def make_profile(tmp_path: Path, **overrides) -> dict:
    main_js = tmp_path / "main.mjs"
    main_js.write_text("", encoding="utf-8")
    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps({"apiKey": "secret"}), encoding="utf-8")
    value = {
        "name": "kimi",
        "harness": "kimi_code",
        "executable": "node",
        "executable_args": [str(main_js)],
        "kimi_code_home": str(tmp_path / "home"),
        "api_key_env": "AUTOMM_TEST_KIMI_KEY",
        "api_key_file": str(key_file),
        "model": "kimi-code/kimi-for-coding",
        "max_prompt_chars": 30000,
    }
    value.update(overrides)
    return value


def test_prepare_uses_prompt_argument_and_key_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")
    provider = get_provider(make_profile(tmp_path))
    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.command[:2] == ["node", str(tmp_path / "main.mjs")]
    assert "-m" in invocation.command
    assert "kimi-code/kimi-for-coding" in invocation.command
    assert "-p" in invocation.command
    assert "hello" in invocation.command
    assert "--output-format" in invocation.command
    assert invocation.stdin is None
    assert invocation.env["KIMI_API_KEY"] == "secret"
    assert invocation.env["KIMI_CODE_HOME"] == str(tmp_path / "home")


def test_prompt_limit_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")
    provider = get_provider(make_profile(tmp_path, max_prompt_chars=3))
    with pytest.raises(ProviderConfigError, match="max_prompt_chars"):
        provider.prepare("hello", tmp_path / "response.json")


def test_extract_retryable_exit_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")
    provider = get_provider(make_profile(tmp_path))
    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert provider.extract_response(invocation, '{"ok": true}', "", 0) == {"ok": True}
    with pytest.raises(ProviderError, match="可重试"):
        provider.extract_response(invocation, "", "rate limited", 75)


def test_missing_key_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")
    cfg = make_profile(tmp_path)
    cfg["api_key_file"] = str(tmp_path / "missing.json")
    with pytest.raises(ProviderConfigError, match="api_key"):
        get_provider(cfg).prepare("hello", tmp_path / "response.json")
