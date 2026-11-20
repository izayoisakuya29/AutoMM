from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from automm.llm import get_provider
from automm.llm.base import (
    Invocation,
    ProviderAuthError,
    ProviderConfigError,
    ProviderError,
)

_CONFIG_TEXT = '[models.kimi-code]\nmodel = "kimi-code"\n'


def make_profile(tmp_path: Path, **overrides) -> dict:
    main_js = tmp_path / "main.mjs"
    main_js.write_text("", encoding="utf-8")
    key_file = tmp_path / "key.json"
    key_file.write_text(json.dumps({"apiKey": "secret"}), encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(_CONFIG_TEXT, encoding="utf-8")
    value = {
        "name": "kimi",
        "harness": "kimi_code",
        "executable": "node",
        "executable_args": [str(main_js)],
        "kimi_code_home": str(tmp_path / "home"),
        "api_key_env": "AUTOMM_TEST_KIMI_KEY",
        "api_key_file": str(key_file),
        "config_file": str(config_file),
        "model": "kimi-code",
        "max_prompt_chars": 30000,
    }
    value.update(overrides)
    return value


def _provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides):
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")
    return get_provider(make_profile(tmp_path, **overrides))


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_HELP_TEXT = """\
-m, --model <model>
-p, --prompt <prompt>
--output-format <format>
"""


def _fake_run(help_text: str, calls: list[dict] | None = None):
    def run(command: list[str], **kwargs: object) -> _Completed:
        if calls is not None:
            calls.append({"command": list(command), **kwargs})
        if "--version" in command:
            return _Completed(stdout="kimi-code 2.6.3\n")
        return _Completed(stdout=help_text)

    return run


def test_prepare_uses_prompt_argument_and_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)
    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.command[:2] == ["node", str(tmp_path / "main.mjs")]
    assert "-m" in invocation.command
    assert "kimi-code" in invocation.command
    assert "-p" in invocation.command
    assert "hello" in invocation.command
    assert "--output-format" in invocation.command
    assert invocation.stdin is None
    assert invocation.env["KIMI_API_KEY"] == "secret"
    assert invocation.env["KIMI_CODE_HOME"] == str(tmp_path / "home")


def test_prepare_copies_config_toml_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)
    provider.prepare("hello", tmp_path / "response.json")

    target = tmp_path / "home" / "config.toml"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == _CONFIG_TEXT


def test_prepare_does_not_overwrite_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / "config.toml"
    target.write_text('[models.custom]\nmodel = "custom"\n', encoding="utf-8")
    provider = _provider(tmp_path, monkeypatch)

    provider.prepare("hello", tmp_path / "response.json")

    assert target.read_text(encoding="utf-8") == '[models.custom]\nmodel = "custom"\n'


def test_existing_config_without_config_file_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = home / "config.toml"
    target.write_text('[models.kimi-code]\nmodel = "kimi-code"\n', encoding="utf-8")
    provider = _provider(tmp_path, monkeypatch, config_file=None)

    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert target.read_text(encoding="utf-8") == _CONFIG_TEXT
    assert invocation.env["KIMI_CODE_HOME"] == str(home)


def test_config_path_directory_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").mkdir()
    provider = _provider(tmp_path, monkeypatch)

    with pytest.raises(ProviderConfigError, match="config.toml"):
        provider.prepare("hello", tmp_path / "response.json")


def test_config_copy_oserror_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)

    def fail_replace(source: object, target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("automm.llm.kimi.os.replace", fail_replace)

    with pytest.raises(ProviderConfigError, match="复制失败"):
        provider.prepare("hello", tmp_path / "response.json")
    assert not list((tmp_path / "home").glob(".config-*.tmp"))


def test_missing_config_file_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch, config_file=None)
    with pytest.raises(ProviderConfigError, match="config.toml"):
        provider.prepare("hello", tmp_path / "response.json")


def test_missing_config_source_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch, config_file=str(tmp_path / "absent.toml"))
    with pytest.raises(ProviderConfigError, match="config_file"):
        provider.prepare("hello", tmp_path / "response.json")


def test_prompt_limit_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch, max_prompt_chars=3)
    with pytest.raises(ProviderConfigError, match="max_prompt_chars"):
        provider.prepare("hello", tmp_path / "response.json")


@pytest.mark.parametrize("value", [True, 1.5, "30000", "many", 0, -1, None])
def test_invalid_prompt_limit_raises_config_error(
    value: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch, max_prompt_chars=value)
    with pytest.raises(ProviderConfigError, match="max_prompt_chars"):
        provider.prepare("hello", tmp_path / "response.json")


def test_extract_retryable_exit_and_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)
    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert provider.extract_response(invocation, '{"ok": true}', "", 0) == {"ok": True}
    with pytest.raises(ProviderError, match="可重试"):
        provider.extract_response(invocation, "", "rate limited", 75)


def test_empty_stdout_raises_provider_error(tmp_path: Path) -> None:
    provider = get_provider(make_profile(tmp_path))
    invocation = Invocation(command=["node"], output_path=tmp_path / "response.json")

    with pytest.raises(ProviderError, match="最终响应"):
        provider.extract_response(invocation, "  \n", "", 0)


def test_auth_classification_uses_error_lines_only(tmp_path: Path) -> None:
    provider = get_provider(make_profile(tmp_path))
    invocation = Invocation(command=["node"], output_path=tmp_path / "response.json")

    with pytest.raises(ProviderAuthError):
        provider.extract_response(invocation, "", "ERROR: 401 Unauthorized", 1)
    with pytest.raises(ProviderError) as tool_output:
        provider.extract_response(invocation, "", "tool output says 401 Unauthorized", 1)
    assert not isinstance(tool_output.value, ProviderAuthError)
    with pytest.raises(ProviderError) as rate_limited:
        provider.extract_response(invocation, "", "ERROR: rate limited", 1)
    assert not isinstance(rate_limited.value, ProviderAuthError)


def test_extract_recognizes_kimi_provider_auth_error(tmp_path: Path) -> None:
    provider = get_provider(make_profile(tmp_path))
    invocation = Invocation(command=["node"], output_path=tmp_path / "response.json")
    stderr = (
        "error: failed to run prompt: provider.auth_error: "
        "This API key is not permitted to access this endpoint."
    )

    with pytest.raises(ProviderAuthError):
        provider.extract_response(invocation, "", stderr, 1)


def test_missing_key_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch, api_key_file=str(tmp_path / "missing.json"))
    with pytest.raises(ProviderConfigError, match="api_key"):
        provider.prepare("hello", tmp_path / "response.json")


def test_invalid_key_json_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_profile(tmp_path)
    Path(cfg["api_key_file"]).write_text("{not json", encoding="utf-8")
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")

    with pytest.raises(ProviderConfigError, match="JSON"):
        get_provider(cfg).prepare("hello", tmp_path / "response.json")


def test_non_string_api_key_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_profile(tmp_path)
    Path(cfg["api_key_file"]).write_text(json.dumps({"apiKey": 123}), encoding="utf-8")
    monkeypatch.delenv("AUTOMM_TEST_KIMI_KEY", raising=False)
    monkeypatch.setattr("automm.llm.kimi.KimiCodeProvider._executable", lambda self: "node")

    with pytest.raises(ProviderConfigError, match="api_key"):
        get_provider(cfg).prepare("hello", tmp_path / "response.json")


def test_env_key_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch)
    monkeypatch.setenv("AUTOMM_TEST_KIMI_KEY", "env-secret")

    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.env["KIMI_API_KEY"] == "env-secret"


def test_base_url_sets_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch, base_url="https://kimi.example/v1")

    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.env["KIMI_CODE_BASE_URL"] == "https://kimi.example/v1"


def test_extra_args_appended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch, extra_args=["--foo", "bar"])

    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.command[-2:] == ["--foo", "bar"]


def test_extra_env_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch, extra_env={"KIMI_CODE_DEBUG": "1"})

    invocation = provider.prepare("hello", tmp_path / "response.json")

    assert invocation.env["KIMI_CODE_DEBUG"] == "1"


def test_probe_accepts_required_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)
    calls: list[dict] = []
    monkeypatch.setattr("automm.llm.kimi.subprocess.run", _fake_run(_HELP_TEXT, calls))

    result = provider.probe()

    assert result["executable"] == "node"
    assert result["version"] == ["kimi-code 2.6.3"]
    assert len(calls) == 2
    assert all(call["timeout"] == 30 for call in calls)


def test_probe_rejects_missing_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)
    incomplete = _HELP_TEXT.replace("--output-format <format>\n", "")
    monkeypatch.setattr("automm.llm.kimi.subprocess.run", _fake_run(incomplete))

    with pytest.raises(ProviderConfigError, match="output-format"):
        provider.probe()


def test_probe_wraps_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch)

    def run(command: list[str], **kwargs: object) -> _Completed:
        raise subprocess.TimeoutExpired(command, 30)

    monkeypatch.setattr("automm.llm.kimi.subprocess.run", run)

    with pytest.raises(ProviderError, match="探测失败"):
        provider.probe()


def test_probe_wraps_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(tmp_path, monkeypatch)

    def run(command: list[str], **kwargs: object) -> _Completed:
        raise OSError("node missing")

    monkeypatch.setattr("automm.llm.kimi.subprocess.run", run)

    with pytest.raises(ProviderError, match="探测失败"):
        provider.probe()


def test_probe_version_nonzero_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path, monkeypatch)

    def run(command: list[str], **kwargs: object) -> _Completed:
        if "--version" in command:
            return _Completed(returncode=1, stderr="version failed")
        return _Completed(stdout=_HELP_TEXT)

    monkeypatch.setattr("automm.llm.kimi.subprocess.run", run)

    with pytest.raises(ProviderError, match="版本探测失败"):
        provider.probe()
