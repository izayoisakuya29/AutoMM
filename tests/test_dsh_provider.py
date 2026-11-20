from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from automm.llm import get_provider
from automm.llm.base import Invocation, ProviderAuthError, ProviderConfigError


def profile(tmp_path: Path) -> dict:
    home = tmp_path / "dsh-home"
    (home / "profiles" / "headless").mkdir(parents=True)
    return {
        "name": "deepseek",
        "harness": "dsh_headless",
        "executable": "dsh",
        "dsh_home": str(home),
        "dsh_profile": "headless",
        "provider": "deepseek-official",
        "model": "deepseek-v4-pro",
        "permission_mode": "workspace-write",
        "approval_policy": "never",
    }


def test_prepare_uses_stdin_patch_and_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    provider = get_provider(profile(tmp_path))
    invocation = provider.prepare("hello task", tmp_path / "response.json")

    assert invocation.command[:5] == ["dsh", "--profile", "headless", "--patch", str(tmp_path / "dsh_patch.yml")]
    assert invocation.command[-3:] == ["--approval-policy", "never", "-"]
    assert "--permission-mode" in invocation.command
    assert invocation.stdin == "hello task"
    assert invocation.env["DSH_HOME"] == str(tmp_path / "dsh-home")

    patch = yaml.safe_load((tmp_path / "dsh_patch.yml").read_text(encoding="utf-8"))
    assert patch == [
        {
            "id": "agent-default-model",
            "config": {"provider": "deepseek-official", "model": "deepseek-v4-pro"},
        }
    ]


def test_prepare_merges_patch_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    cfg = profile(tmp_path)
    cfg["patch_config"] = {"reasoningEffort": "high"}
    provider = get_provider(cfg)
    provider.prepare("p", tmp_path / "response.json")
    patch = yaml.safe_load((tmp_path / "dsh_patch.yml").read_text(encoding="utf-8"))
    assert patch[0]["config"]["reasoningEffort"] == "high"
    assert patch[0]["config"]["provider"] == "deepseek-official"


def test_extract_parses_stdout_and_detects_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    provider = get_provider(profile(tmp_path))
    invocation = Invocation(command=["dsh"], output_path=tmp_path / "response.json")

    assert provider.extract_response(invocation, '```json\n{"ok": true}\n```', "", 0) == {"ok": True}
    with pytest.raises(ProviderAuthError):
        provider.extract_response(invocation, "", "HTTP 401 Unauthorized", 1)


def test_prepare_requires_provider_and_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    cfg = profile(tmp_path)
    cfg["provider"] = ""
    with pytest.raises(ProviderConfigError, match="provider"):
        get_provider(cfg).prepare("p", tmp_path / "response.json")
