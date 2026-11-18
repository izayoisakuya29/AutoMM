from __future__ import annotations

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
    monkeypatch.setenv("PATH", "/usr/bin")

    env = build_env({"KIMI_API_KEY": "profile-key", "KIMI_CODE_HOME": "/tmp/kimi"})

    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_ENTRYPOINT" not in env
    assert "OPENAI_API_KEY" not in env
    assert "DEEPSEEK_API_KEY" not in env
    assert env["KIMI_API_KEY"] == "profile-key"
    assert env["KIMI_CODE_HOME"] == "/tmp/kimi"
    assert env["PATH"] == "/usr/bin"
