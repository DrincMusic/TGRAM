from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rlmgraph.automatic_tickets import AutomaticTicketRunner
from rlmgraph.models import ProjectExecutionMode


@pytest.mark.parametrize("promote", [False, True])
def test_runner_finishes_validated_ticket_in_authorized_mode(promote):
    mode = (
        ProjectExecutionMode.AUTONOMOUS_PROJECT
        if promote else ProjectExecutionMode.AUTONOMOUS_SANDBOX
    )
    store = Mock()
    store.projects.return_value = [SimpleNamespace(id="project", execution_mode=mode)]
    workspace, sandbox, tickets = Mock(), Mock(), Mock()
    workspace.snapshot.return_value = {"status": "COMPLETED", "result_id": "plan"}
    sandbox.snapshot.side_effect = [
        {"status": "READY_FOR_REVIEW", "attempt_id": "attempt"},
        {"status": "PROMOTED"},
    ]
    runner = AutomaticTicketRunner(store, workspace, sandbox, tickets)
    ticket = SimpleNamespace(id="ticket", title="Fix", description="Fix", acceptance_criteria=[])
    runner._ready = Mock(side_effect=[[ticket], [], []])
    runner._complete_validations = Mock(return_value=SimpleNamespace(
        id="attempt", status="READY_FOR_REVIEW"
    ))
    runner._run("project")
    assert runner.snapshot()["status"] == "COMPLETED"
    assert runner.snapshot()["completed"] == 1
    assert runner.snapshot()["failed"] == 0
    assert sandbox.promote.call_count == int(promote)
    assert sandbox.reconcile.call_count == int(promote)
    assert tickets.transition.call_args.args[1] == "AWAITING_REVIEW"


def test_runner_stops_if_project_is_no_longer_registered():
    store, workspace = Mock(), Mock()
    store.projects.return_value = []
    runner = AutomaticTicketRunner(store, workspace, Mock(), Mock())
    runner._run("removed-project")
    assert runner.snapshot()["status"] == "FAILED"
    workspace.start_change_plan.assert_not_called()
