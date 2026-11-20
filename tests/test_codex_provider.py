from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from automm.llm import get_provider
from automm.llm.base import Invocation, ProviderAuthError, ProviderConfigError, ProviderError
from automm.llm.codex import find_codex_executable

_HELP_TEXT = """\
exec [OPTIONS] [PROMPT]
--output-schema <FILE>
--output-last-message <FILE>
--skip-git-repo-check
--json
--sandbox <MODE>
--approve-for-me
--cd <DIR>
--dangerously-bypass-approvals-and-sandbox
--profile <NAME>
"""


class _Completed:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_run(help_text: str, calls: list[dict] | None = None):
    def run(command: list[str], **kwargs: object) -> _Completed:
        if calls is not None:
            calls.append({"command": list(command), **kwargs})
        if "--version" in command:
            return _Completed(stdout="codex-cli 9.9.9\n")
        return _Completed(stdout=help_text)

    return run


def profile(tmp_path: Path, **overrides) -> dict:
    value = {
        "name": "openai",
        "harness": "codex_exec",
        "executable": "codex",
        "codex_home": str(tmp_path),
        "model": "gpt-6-luna",
        "bypass_approvals": True,
        "skip_git_repo_check": True,
        "output_schema": "config/agent_response.schema.json",
    }
    value.update(overrides)
    return value


def test_prepare_uses_stdin_and_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path))
    invocation = provider.prepare("p", tmp_path / "response.json")

    assert invocation.command[:3] == ["codex", "exec", "-"]
    assert "--output-schema" in invocation.command
    assert "--output-last-message" in invocation.command
    assert "--dangerously-bypass-approvals-and-sandbox" in invocation.command
    assert "--sandbox" not in invocation.command
    assert "--model" in invocation.command
    assert invocation.stdin == "p"
    assert invocation.env["CODEX_HOME"] == str(tmp_path)


def test_prepare_uses_sandbox_when_not_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path, bypass_approvals=False, sandbox="workspace-write"))
    invocation = provider.prepare("p", tmp_path / "response.json")

    assert "--sandbox" in invocation.command
    assert "workspace-write" in invocation.command
    assert "--approve-for-me" in invocation.command
    assert "--dangerously-bypass-approvals-and-sandbox" not in invocation.command


def test_prepare_appends_config_profile_and_extra_args(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path, config_profile="work", extra_args=["--full-auto", "x"]))
    invocation = provider.prepare("p", tmp_path / "response.json")

    index = invocation.command.index("-p")
    assert invocation.command[index + 1] == "work"
    assert invocation.command[-2:] == ["--full-auto", "x"]


def test_prepare_requires_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path, model=""))

    with pytest.raises(ProviderConfigError, match="model"):
        provider.prepare("p", tmp_path / "response.json")


def test_prepare_requires_output_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path, output_schema=""))

    with pytest.raises(ProviderConfigError, match="output_schema"):
        provider.prepare("p", tmp_path / "response.json")


def test_prepare_wraps_invalid_output_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path, output_schema="config/does-not-exist.schema.json"))

    with pytest.raises(ProviderConfigError, match="output_schema"):
        provider.prepare("p", tmp_path / "response.json")


def test_extract_reads_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path))
    output = tmp_path / "response.json"
    output.write_text(json.dumps({"ok": True}), encoding="utf-8")
    invocation = Invocation(command=["codex"], output_path=output)

    assert provider.extract_response(invocation, "", "", 0) == {"ok": True}
    with pytest.raises(ProviderAuthError):
        provider.extract_response(invocation, "", "ERROR: 401 Unauthorized", 1)


def test_extract_classifies_timestamped_error_line_as_auth(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))

    with pytest.raises(ProviderAuthError):
        provider.extract_response(
            Invocation(command=["codex"]),
            "",
            "2026-11-20T12:00:00Z ERROR: 401 Unauthorized",
            1,
        )


def test_extract_ignores_auth_markers_in_tool_output(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))

    with pytest.raises(ProviderError, match="tool output") as excinfo:
        provider.extract_response(Invocation(command=["codex"]), "", "tool output says 401 Unauthorized", 1)
    assert not isinstance(excinfo.value, ProviderAuthError)


def test_extract_non_auth_error_line_is_provider_error(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))

    with pytest.raises(ProviderError, match="model overloaded") as excinfo:
        provider.extract_response(Invocation(command=["codex"]), "", "ERROR: model overloaded", 1)
    assert not isinstance(excinfo.value, ProviderAuthError)


def test_extract_rejects_invalid_json(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))
    output = tmp_path / "response.json"
    output.write_text("{not json", encoding="utf-8")

    with pytest.raises(ProviderError, match="无法读取"):
        provider.extract_response(Invocation(command=["codex"], output_path=output), "", "", 0)


def test_extract_rejects_non_object_json(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))
    output = tmp_path / "response.json"
    output.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ProviderError, match="不是 JSON 对象"):
        provider.extract_response(Invocation(command=["codex"], output_path=output), "", "", 0)


def test_extract_requires_output_file(tmp_path: Path) -> None:
    provider = get_provider(profile(tmp_path))
    invocation = Invocation(command=["codex"], output_path=tmp_path / "missing.json")

    with pytest.raises(ProviderError, match="response.json"):
        provider.extract_response(invocation, "", "", 0)


def test_probe_accepts_complete_flag_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    calls: list[dict] = []
    monkeypatch.setattr("automm.llm.codex.subprocess.run", _fake_run(_HELP_TEXT, calls))
    provider = get_provider(profile(tmp_path))

    assert provider.probe() == {"executable": "codex", "version": ["codex-cli 9.9.9"]}
    assert len(calls) == 2
    assert calls[0]["command"][1] == "--version"
    assert calls[1]["command"][1:3] == ["exec", "--help"]
    assert all(call["timeout"] == 30 for call in calls)


def test_probe_rejects_missing_required_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    incomplete = _HELP_TEXT.replace("--profile <NAME>\n", "")
    monkeypatch.setattr("automm.llm.codex.subprocess.run", _fake_run(incomplete))
    provider = get_provider(profile(tmp_path))

    with pytest.raises(ProviderConfigError, match="--profile"):
        provider.probe()


def test_find_codex_executable_accepts_explicit_path() -> None:
    assert find_codex_executable({"executable": sys.executable}) == sys.executable
