from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from automm.llm import get_provider
from automm.llm.codex import find_codex_executable
from automm.llm.base import Invocation, ProviderAuthError


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


def test_extract_reads_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    provider = get_provider(profile(tmp_path))
    output = tmp_path / "response.json"
    output.write_text(json.dumps({"ok": True}), encoding="utf-8")
    invocation = Invocation(command=["codex"], output_path=output)

    assert provider.extract_response(invocation, "", "", 0) == {"ok": True}
    with pytest.raises(ProviderAuthError):
        provider.extract_response(invocation, "", "401 Unauthorized", 1)


def test_find_codex_executable_accepts_explicit_path() -> None:
    assert find_codex_executable({"executable": sys.executable}) == sys.executable
