from __future__ import annotations

import pytest

from automm.agent_runtime import _agent_prompt

pytestmark = pytest.mark.unit


def test_resume_prompt_references_previous_action() -> None:
    action = {
        "action": "run_agent",
        "agent": "sanity-checker",
        "stage": "sanity_check",
        "problem_id": "synthetic",
        "question_id": "prob01",
        "resume": True,
        "recovery": {
            "mode": "retrying",
            "last_action_id": "act-previous12345678",
            "last_error": "network reset",
        },
    }

    prompt = _agent_prompt("sanity-checker", action, "act-current123456789")

    assert "runtime/actions/act-previous12345678" in prompt
    assert "断点" in prompt or "继续" in prompt
