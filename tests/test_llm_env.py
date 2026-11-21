from __future__ import annotations

import os

from automm.llm.base import ProviderAuthError, ProviderConfigError, ProviderError, build_env


def test_provider_exceptions_are_distinct() -> None:
    assert not issubclass(ProviderConfigError, ProviderError)
    assert not issubclass(ProviderAuthError, ProviderError)


def test_build_env_strips_host_provider_and_session_vars(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret")
    monkeypatch.setenv("KIMI_API_KEY", "inherited")
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/google.json")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-secret")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = build_env({"KIMI_API_KEY": "profile-key", "KIMI_CODE_HOME": "/tmp/kimi"})

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_ENTRYPOINT" not in env
    assert "OPENAI_API_KEY" not in env
    assert "DEEPSEEK_API_KEY" not in env
    assert "MOONSHOT_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in env
    assert "AZURE_OPENAI_API_KEY" not in env
    assert env["KIMI_API_KEY"] == "profile-key"
    assert env["KIMI_CODE_HOME"] == "/tmp/kimi"
    assert env["PATH"] == "/usr/bin"


def test_build_env_ignores_none_extra_values(monkeypatch) -> None:
    monkeypatch.delenv("OPTIONAL", raising=False)

    assert "OPTIONAL" not in build_env(None)
    assert "OPTIONAL" not in build_env({"OPTIONAL": None})


def test_build_env_does_not_mutate_host_environment(monkeypatch) -> None:
    monkeypatch.setenv("KIMI_API_KEY", "inherited")
    monkeypatch.setenv("PATH", "/usr/bin")
    before = dict(os.environ)

    build_env({"KIMI_API_KEY": "profile-key", "NEW_VAR": "x"})

    assert dict(os.environ) == before
    assert os.environ["KIMI_API_KEY"] == "inherited"
