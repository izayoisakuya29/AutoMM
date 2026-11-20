from __future__ import annotations

from pathlib import Path

import jsonschema
import pytest

from automm.agent_runtime import _validate_response_context, apply_agent_commands
from automm.failure_policy import HarnessInvariantError
from automm.llm import ProviderError, get_provider
from automm.llm.dsh import _parse_json_text
from automm.common import read_json
from automm.problems import question_manifest

pytestmark = pytest.mark.unit


def response(action_id: str = "act-test") -> dict:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "status": "success",
        "problem_id": "synthetic",
        "question_id": "prob01",
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


def test_response_context_mismatch_is_harness_invariant() -> None:
    payload = response()
    payload["question_id"] = "prob02"
    with pytest.raises(HarnessInvariantError, match="question_id"):
        _validate_response_context(payload, {"problem_id": "synthetic", "question_id": "prob01"})


def test_failed_response_cannot_change_state() -> None:
    payload = response()
    payload["status"] = "failed"
    payload["commands"] = [{"name": "record_artifact", "arguments": {"name": "literature", "completed": True}}]
    with pytest.raises(HarnessInvariantError, match="不得携带"):
        _validate_response_context(payload, {"problem_id": "synthetic", "question_id": "prob01"})


def test_command_batch_rejects_unknown_artifact_without_partial_write(initialized_problem: tuple[str, Path]) -> None:
    problem_id, _ = initialized_problem
    payload = response()
    payload["problem_id"] = problem_id
    payload["commands"] = [
        {"name": "record_artifact", "arguments": {"name": "problem_understanding", "completed": True}},
        {"name": "record_artifact", "arguments": {"name": "not-a-logical-key", "completed": True}},
    ]
    with pytest.raises(HarnessInvariantError):
        apply_agent_commands(payload, {"problem_id": problem_id, "question_id": "prob01", "stage": "problem_understanding"})
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["artifacts"]["problem_understanding"] is False


def test_dsh_headless_command_uses_stdin_and_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.dsh.DshHeadlessProvider._executable", lambda self: "dsh")
    profile = {
        "name": "deepseek",
        "harness": "dsh_headless",
        "executable": "dsh",
        "dsh_home": str(Path.home() / ".dsh"),
        "dsh_profile": "headless",
        "provider": "deepseek-official",
        "model": "deepseek-v4-pro",
        "permission_mode": "workspace-write",
        "approval_policy": "never",
    }
    provider = get_provider(profile)
    invocation = provider.prepare("hello task", tmp_path / "response.json")
    assert invocation.command[:2] == ["dsh", "--profile"]
    assert invocation.command[-1] == "-"
    assert invocation.stdin == "hello task"
    assert (tmp_path / "dsh_patch.yml").is_file()


def test_codex_command_uses_bypass_and_stdin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("automm.llm.codex.CodexProvider._executable", lambda self: "codex")
    profile = {
        "name": "openai",
        "harness": "codex_exec",
        "executable": "codex",
        "codex_home": str(tmp_path),
        "model": "gpt-6-luna",
        "bypass_approvals": True,
        "skip_git_repo_check": True,
        "output_schema": "config/agent_response.schema.json",
    }
    provider = get_provider(profile)
    invocation = provider.prepare("p", tmp_path / "response.json")
    assert "--dangerously-bypass-approvals-and-sandbox" in invocation.command
    assert "--sandbox" not in invocation.command
    assert invocation.stdin == "p"


def test_dsh_json_text_extraction() -> None:
    assert _parse_json_text("`json\n{\"a\": 1}\n`") == {"a": 1}
    assert _parse_json_text("prefix {\"a\": 1} suffix") == {"a": 1}
    with pytest.raises(ProviderError):
        _parse_json_text("no json here")


def test_command_batch_rolls_back_state_on_mid_batch_failure(initialized_problem: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    problem_id, _ = initialized_problem
    payload = response()
    payload["problem_id"] = problem_id
    payload["commands"] = [
        {"name": "record_artifact", "arguments": {"name": "problem_understanding", "completed": True}},
        {"name": "record_sanity", "arguments": {"level": "level_1_4", "status": "PASS", "reason": "fixture", "failure_type": None, "return_stage": None}},
    ]

    def fail_once(**_: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr("automm.agent_runtime.record_sanity", fail_once)
    with pytest.raises(HarnessInvariantError, match="已回滚"):
        apply_agent_commands(payload, {"problem_id": problem_id, "question_id": "prob01", "stage": "problem_understanding"})
    _, manifest = question_manifest(problem_id, "prob01")
    assert manifest["artifacts"]["problem_understanding"] is False


def test_schema_enum_nodes_declare_type(project_root: Path) -> None:
    schema = read_json(project_root / "config" / "agent_response.schema.json")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "const" in node or "enum" in node:
                assert "type" in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    jsonschema.validate(response(), schema)
    walk(schema)
