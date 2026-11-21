from __future__ import annotations

import pytest

from automm.failure_policy import AgentTimeoutError, AgentTransportError
from automm.runner import run_once
from automm.state import load_state

pytestmark = pytest.mark.integration


def test_agent_timeout_is_retrying_and_not_blocking(initialized_problem: tuple[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_: object, **__: object) -> None:
        raise AgentTimeoutError("injected timeout")

    monkeypatch.setattr("automm.runner.invoke_agent", timeout)
    result = run_once()
    state = load_state()
    assert result["status"] == "retrying"
    assert state["recovery_status"] == "retrying"
    assert state["blocking"] == []
    assert state["recovery"]["last_action_id"] == result["action_id"]


def test_transport_failure_records_last_action_id(
    initialized_problem: tuple[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def transport(*_: object, **__: object) -> None:
        raise AgentTransportError("injected network failure")

    monkeypatch.setattr("automm.runner.invoke_agent", transport)
    result = run_once()
    state = load_state()
    assert result["status"] in {"retrying", "failed"}
    assert state["recovery"]["last_action_id"] == result["action_id"]
