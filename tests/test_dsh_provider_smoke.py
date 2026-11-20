from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from automm.agent_runtime import invoke_agent

pytestmark = pytest.mark.integration


def _response(action_id: str, problem_id: str, question_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "status": "success",
        "problem_id": problem_id,
        "question_id": question_id,
        "assumption_version": None,
        "formulation_version": None,
        "artifacts_created": [],
        "artifacts_updated": [],
        "findings": [],
        "warnings": [],
        "blocking_reasons": [],
        "recommended_next_stage": None,
        "commands": [],
    }


def test_invoke_agent_dsh_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    initialized_problem: tuple[str, Path],
    tmp_path: Path,
) -> None:
    """用 mock 的 dsh headless 走完 invoke_agent 全链路。"""
    problem_id, _ = initialized_problem
    action_id = "act-1234567890abcdef"
    canned = json.dumps(_response(action_id, problem_id, "prob01"), ensure_ascii=False)

    class FakeProcess:
        returncode = 0

        def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]:
            return canned, ""

    monkeypatch.setattr("automm.agent_runtime.subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    monkeypatch.setattr(
        "automm.agent_runtime.resolve_profile",
        lambda agent: {
            "name": "test-dsh",
            "harness": "dsh_headless",
            "executable": "dsh",
            "dsh_home": str(Path.home() / ".dsh"),
            "dsh_profile": "headless",
            "provider": "deepseek-official",
            "model": "deepseek-v4-pro",
            "permission_mode": "workspace-write",
            "approval_policy": "never",
        },
    )
    monkeypatch.setattr(
        "automm.agent_runtime.runtime_config",
        lambda: {
            "output_schema": "config/agent_response.schema.json",
            "registry": "config/agent_registry.yaml",
            "max_output_chars": 200000,
            "capability_probe_on_start": False,
        },
    )

    action = {
        "action": "run_agent",
        "agent": "sanity-checker",
        "stage": "sanity_check",
        "problem_id": problem_id,
        "question_id": "prob01",
    }
    response, meta = invoke_agent("sanity-checker", action, action_id)
    assert response["action_id"] == action_id
    assert response["status"] == "success"
    assert response["problem_id"] == problem_id
    assert meta["provider"] == "dsh_headless"
    assert meta["harness"] == "dsh_headless"
    assert meta["profile"] == "test-dsh"
    assert meta["model"] == "deepseek-v4-pro"