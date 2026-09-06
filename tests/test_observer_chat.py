from pathlib import Path
from types import SimpleNamespace

import pytest

from rlmgraph.observer_chat import ObserverChat


class Store:
    def initialize(self): pass
    def projects(self):
        return [SimpleNamespace(
            id="P1", root="C:/safe/Dummy", read_only=True, organization="Personal",
            latest_scan_id="S1",
        )]
    def project_tickets(self):
        return [SimpleNamespace(id="T1", project_id="P1", status="READY")]
    def execution_attempts(self):
        return [SimpleNamespace(total_tokens=300)]
    def planning_runs(self):
        return [SimpleNamespace(retrieval_tokens_used=50)]
    def benchmark_runs(self):
        return [SimpleNamespace(fixed=SimpleNamespace(total_tokens=1000), active=SimpleNamespace(total_tokens=400))]
    def pathway_benchmarks(self): return []
    def codex_readonly_proofs(self): return []
    def generic_codex_evaluations(self): return []
    def resumable_session_evaluations(self): return []
    def project_workspace_records(self): return []
    def implementation_sandboxes(self): return []


@pytest.fixture
def chat(monkeypatch):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr("rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace())
    return ObserverChat(Store(), model="test-model")


def test_usage_is_answered_from_rlm_ledger_without_model_call(chat) -> None:
    result = chat.reply("What is my token usage and savings?", [], "P1", None)
    assert result["route"] == "RLM_TELEMETRY_LEDGER"
    assert result["metrics"]["observed_usage_tokens"] == 350
    assert result["metrics"]["measured_savings_tokens"] == 600
    assert result["metrics"]["measured_savings_percent"] == 60.0
    assert result["authority"] == "READ_ONLY_MEASUREMENT_NO_MODEL_CALL"


def test_savings_ui_and_architecture_statement_is_not_telemetry(chat) -> None:
    evidence = SimpleNamespace(model_dump=lambda **kwargs: {"path": "page.tsx", "line": 1})
    claim = SimpleNamespace(
        conclusion="Mirror architecture answer", id="C-ARCH", confidence=.9,
        evidence=[evidence], unresolved_questions=[],
    )
    chat.recursive_supervisor.run = lambda *args, **kwargs: SimpleNamespace(
        claim=claim, task=SimpleNamespace(id="T-ARCH", reuse_type=None), cache_hit=False,
    )

    result = chat.reply(
        "You made a Savings tab. Read-only might be better for your architecture while you work.",
        [], "P1", None,
    )

    assert result["route"] == "RLM_SYSTEM_INVESTIGATION"
    assert result["operation_route"] != "TELEMETRY"


def test_repository_question_runs_through_graph_supervisor(chat) -> None:
    evidence = SimpleNamespace(model_dump=lambda **kwargs: {"path": "a.py", "line": 2})
    claim = SimpleNamespace(conclusion="Grounded answer", id="C1", confidence=.9, evidence=[evidence], unresolved_questions=[])
    chat.supervisor.run = lambda question, root: SimpleNamespace(claim=claim, task=SimpleNamespace(id="T1"), cache_hit=True)
    result = chat.reply("Why did this fail?", [], "P1", None, investigation_mode="DIRECT")
    assert result["route"] == "RLM_GRAPH_SUPERVISOR"
    assert result["claim_id"] == "C1"
    assert result["cache_hit"] is True


def test_projects_question_reads_registry_instead_of_selected_repository(chat) -> None:
    result = chat.reply("Can RLMGraph tell me about its projects?", [], "P1", None)
    assert result["route"] == "RLM_PROJECT_REGISTRY"
    assert result["authority"] == "READ_ONLY_REGISTRY_QUERY_NO_MODEL_CALL"
    assert result["projects"][0]["name"] == "Dummy"
    assert result["projects"][0]["ticket_statuses"] == {"READY": 1}


def test_rlmgraph_architecture_question_cannot_be_routed_to_selected_scoreboard(chat) -> None:
    evidence = SimpleNamespace(model_dump=lambda **kwargs: {"path": "README.md", "line": 1})
    claim = SimpleNamespace(
        conclusion="System architecture answer", id="C-SYSTEM", confidence=.87,
        evidence=[evidence], unresolved_questions=[],
    )
    observed_roots = []
    observed_questions = []
    observed_options = []
    chat.recursive_supervisor.run = lambda question, root, **options: (
        observed_options.append(options)
        or
        observed_questions.append(question) or observed_roots.append(root) or SimpleNamespace(
            claim=claim, task=SimpleNamespace(id="T-SYSTEM", reuse_type=None), cache_hit=False,
        )
    )
    result = chat.reply(
        "Where did development go wrong while implementing RLMGraph?", [], "P1", None
    )
    assert result["route"] == "RLM_SYSTEM_INVESTIGATION"
    assert result["scope"] == "SYSTEM"
    assert result["project_id"] is None
    assert observed_roots == [chat.system_root]
    assert len(observed_questions) == 1
    assert (
        '"current_user_prompt_verbatim": '
        '"Where did development go wrong while implementing RLMGraph?"'
        in observed_questions[0]
    )
    assert observed_options == [{"force_investigation": True}]
    assert observed_roots[0] != Path("C:/safe/Dummy")
    assert result["routing_confidence"] == 1.0


def test_explicit_project_scope_can_override_auto_detection(chat) -> None:
    evidence = SimpleNamespace(model_dump=lambda **kwargs: {"path": "integration.py", "line": 4})
    claim = SimpleNamespace(
        conclusion="Repository integration answer", id="C-PROJECT", confidence=.8,
        evidence=[evidence], unresolved_questions=[],
    )
    observed_roots = []
    chat.supervisor.run = lambda question, root: (
        observed_roots.append(root) or SimpleNamespace(
            claim=claim, task=SimpleNamespace(id="T-PROJECT", reuse_type=None), cache_hit=False,
        )
    )
    result = chat.reply(
        "How does this repository integrate with RLMGraph?", [], "P1", None,
        scope="PROJECT", investigation_mode="DIRECT",
    )
    assert result["scope"] == "PROJECT"
    assert observed_roots == [Path("C:/safe/Dummy")]
    assert result["routing_confidence"] == 1.0


def test_complex_project_question_uses_recursive_investigation_in_auto_mode(chat) -> None:
    evidence = SimpleNamespace(model_dump=lambda **kwargs: {"path": "service.py", "line": 8})
    claim = SimpleNamespace(
        conclusion="Recursive answer", id="C-RECURSIVE", confidence=.86,
        evidence=[evidence], unresolved_questions=[],
    )
    root_task = SimpleNamespace(
        id="T-ROOT", reuse_type=None, parent_task_id=None,
        question="Why does startup fail?", depth=0,
        status=SimpleNamespace(value="DONE"), route=None, reused_claim_id=None,
        output_claim_id="C-RECURSIVE",
        stopping_reason=SimpleNamespace(value="COMPLETED"),
    )
    child = SimpleNamespace(
        id="T-CHILD", parent_task_id="T-ROOT", question="Trace the failing path",
        depth=1, status=SimpleNamespace(value="DONE"), route=None,
        reused_claim_id=None, output_claim_id="C-BRANCH",
        stopping_reason=SimpleNamespace(value="COMPLETED"),
    )
    chat.recursive_supervisor.run = lambda question, root, **options: SimpleNamespace(
        claim=claim, task=root_task, cache_hit=False, sub_tasks=[child],
        planning_questions=[child.question], conflicts=[], investigation_calls=3,
        budget_exhausted=False,
    )
    result = chat.reply(
        "Why does the selected repository fail during startup?", [], "P1", None
    )
    assert result["scope"] == "PROJECT"
    assert result["investigation_mode"] == "RECURSIVE"
    assert result["recursive"] is True
    assert result["task_tree"][1]["parent_task_id"] == "T-ROOT"


def test_chat_rejects_empty_and_oversized_messages(chat) -> None:
    with pytest.raises(ValueError, match="between 1 and 4,000"):
        chat.reply(" ", [], None, None)
    with pytest.raises(ValueError, match="between 1 and 4,000"):
        chat.reply("x" * 4001, [], None, None)
