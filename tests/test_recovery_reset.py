from __future__ import annotations

from pathlib import Path

import pytest

from automm.common import write_json
from automm.problems import load_problem, problem_dir
from automm.runner import run_once
from automm.state import load_state, save_state

pytestmark = pytest.mark.integration


def test_successful_idle_resets_stale_recovery(
    initialized_problem: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem_id, _ = initialized_problem
    problem = load_problem(problem_id)
    problem["summary_status"] = "built"
    problem["completion_notification"] = "sent"
    write_json(problem_dir(problem_id) / "problem_state.json", problem)

    state = load_state()
    state.update(
        {
            "current_stage": "completed",
            "current_question": None,
            "recovery_status": "retrying",
            "failure_class": "code_runtime",
            "blocking": [],
        }
    )
    state["recovery"].update({"mode": "convergence", "same_fingerprint_streak": 34})
    save_state(state, event="test_setup")

    monkeypatch.setattr("automm.runner._run_mail_poll", lambda: None)
    result = run_once()
    state = load_state()

    assert result["status"] == "completed"
    assert result["action"]["action"] == "idle"
    assert state["recovery_status"] == "normal"
    assert state["failure_class"] is None
    assert state["recovery"]["mode"] == "normal"
    assert state["recovery"]["same_fingerprint_streak"] == 0
