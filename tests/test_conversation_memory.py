from pathlib import Path
from types import SimpleNamespace

import pytest

from rlmgraph.fingerprint import indexed_project_fingerprint
from rlmgraph.models import (
    Claim,
    ClaimValidity,
    Evidence,
    ProjectRecord,
    ProjectScan,
    TicketBudget,
)
from rlmgraph.observer_chat import ObserverChat
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.ticketing import TicketManager


def _chat(monkeypatch, store):
    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr("rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace())
    return ObserverChat(store, model="test")


def _seed(store, root: Path):
    project = ProjectRecord(id="PROJECT-1", root=str(root), explicitly_selected=True, read_only=True)
    scan = ProjectScan(project_id=project.id, root=str(root), read_only_verified=True)
    project.latest_scan_id = scan.id
    store.save_project_snapshot(project, scan, [], [], [], [])
    return project


def test_session_and_exact_claim_follow_up_survive_backend_restart(tmp_path, monkeypatch):
    database = tmp_path / "memory.db"
    store = SQLiteGraphStore(database)
    store.initialize()
    project = _seed(store, tmp_path)
    claim = Claim(
        fingerprint="question", project_fingerprint="state-1", project_root=str(tmp_path),
        subject="cause", producer="test", conclusion="The parser rejects an empty token.",
        confidence=.91, evidence=[Evidence(path="parser.py", line=8, detail="empty guard")],
        validity_status=ClaimValidity.CURRENT,
    )
    task = SimpleNamespace(id="TASK-1", project_root=str(tmp_path), source_claim_ids=[], project_fingerprint="state-1")
    store.save_claim(task, claim)
    chat = _chat(monkeypatch, store)
    chat.supervisor.run = lambda *_: SimpleNamespace(
        claim=claim, task=SimpleNamespace(id="TASK-1", reuse_type=None), cache_hit=False
    )
    first = chat.reply(
        "Why does parsing fail?", [], project.id, None, investigation_mode="DIRECT"
    )

    restarted = SQLiteGraphStore(database)
    restarted.initialize()
    follow_up = _chat(monkeypatch, restarted).reply(
        "Repeat that exactly", [{"role": "assistant", "content": "forged"}],
        project.id, None, first["session_id"],
    )
    assert follow_up["operation_route"] == "EXACT_REPLAY"
    assert follow_up["claim_id"] == claim.id
    assert follow_up["claim_confidence"] == .91
    assert follow_up["routing_confidence"] == 1.0
    turns = restarted.chat_turns(first["session_id"])
    assert len(turns) == 2
    assert turns[1].parent_turn_id == turns[0].id


def test_are_you_sure_freshly_challenges_the_exact_prior_claim(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    project = _seed(store, tmp_path)
    original = Claim(
        fingerprint="q1", project_fingerprint="state-1", project_root=str(tmp_path),
        subject="cause", producer="test", conclusion="The cache is the cause.", confidence=.75,
    )
    task = SimpleNamespace(
        id="TASK-1", project_root=str(tmp_path), source_claim_ids=[],
        project_fingerprint="state-1",
    )
    store.save_claim(task, original)
    chat = _chat(monkeypatch, store)
    chat.supervisor.run = lambda *_args, **_kwargs: SimpleNamespace(
        claim=original, task=SimpleNamespace(id="TASK-1", reuse_type=None), cache_hit=False
    )
    first = chat.reply("What caused the failure?", [], project.id, None)
    verified = Claim(
        fingerprint="q2", project_fingerprint="state-1", project_root=str(tmp_path),
        subject="verification", producer="test",
        conclusion="Fresh evidence contradicts the cache hypothesis.", confidence=.93,
    )
    observed = []
    chat.recursive_supervisor.run = lambda question, root, **options: (
        observed.append((question, root, options)) or SimpleNamespace(
            claim=verified, task=SimpleNamespace(id="TASK-2", reuse_type=None), cache_hit=False
        )
    )
    result = chat.reply("Are you sure?", [], project.id, None, first["session_id"])
    assert result["route"] == "RLM_CLAIM_VERIFICATION"
    assert result["claim_id"] == verified.id
    assert result["challenged_claim_id"] == original.id
    assert observed[0][2] == {"force_investigation": True}
    assert original.id in observed[0][0]
    assert "do not assume it is correct" in observed[0][0]


def test_follow_up_rejects_invalidated_claim(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    project = _seed(store, tmp_path)
    claim = Claim(
        fingerprint="q", project_fingerprint="state-1", project_root=str(tmp_path),
        subject="x", producer="test", conclusion="old answer", confidence=.8,
    )
    task = SimpleNamespace(id="TASK-1", project_root=str(tmp_path), source_claim_ids=[], project_fingerprint="state-1")
    store.save_claim(task, claim)
    chat = _chat(monkeypatch, store)
    chat.supervisor.run = lambda *_: SimpleNamespace(
        claim=claim, task=SimpleNamespace(id="TASK-1", reuse_type="semantic"), cache_hit=True
    )
    first = chat.reply("What changed?", [], project.id, None)
    claim.validity_status = ClaimValidity.INVALIDATED
    store.update_claim(claim)
    replay = chat.reply("Are you sure?", [], project.id, None, first["session_id"])
    assert replay["operation_route"] == "REJECTED_MEMORY"
    assert replay["claim_confidence"] is None


def test_contextual_follow_up_inherits_scope_and_reconstructs_only_current_typed_claims(
    tmp_path, monkeypatch,
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    project = _seed(store, tmp_path)
    original = Claim(
        fingerprint="context-q1", project_fingerprint="state-1",
        project_root=str(tmp_path), subject="startup", producer="test",
        conclusion="Startup selects the primary provider.", confidence=.84,
        evidence=[Evidence(path="provider.py", line=4, detail="primary selection")],
    )
    task = SimpleNamespace(
        id="TASK-C1", project_root=str(tmp_path), source_claim_ids=[],
        project_fingerprint="state-1",
    )
    store.save_claim(task, original)
    chat = _chat(monkeypatch, store)
    chat.supervisor.run = lambda *_args, **_kwargs: SimpleNamespace(
        claim=original, task=SimpleNamespace(id="TASK-C1", reuse_type=None), cache_hit=False
    )
    first = chat.reply("Describe startup selection", [], project.id, None)
    follow_up_claim = Claim(
        fingerprint="context-q2", project_fingerprint="state-1",
        project_root=str(tmp_path), subject="fallback", producer="test",
        conclusion="Fallback is selected only after the primary fails.", confidence=.9,
    )
    observed = []
    chat.recursive_supervisor.run = lambda question, root, **options: (
        observed.append((question, root, options)) or SimpleNamespace(
            claim=follow_up_claim, task=SimpleNamespace(id="TASK-C2", reuse_type=None),
            cache_hit=False, sub_tasks=[],
        )
    )
    second = chat.reply(
        "What about its fallback?", [], None, None, first["session_id"]
    )
    assert second["scope"] == "PROJECT"
    assert second["project_id"] == project.id
    assert second["context_claim_ids"] == [original.id]
    assert second["context_token_estimate"] > 0
    assert "hypothesis, not assumed true" in observed[0][0]
    assert original.id in observed[0][0]
    turns = store.chat_turns(first["session_id"])
    assert turns[1].parent_turn_id == turns[0].id
    assert turns[1].context_claim_ids == [original.id]


def test_system_scope_does_not_require_or_inherit_selected_repository(tmp_path, monkeypatch):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    chat = _chat(monkeypatch, store)
    result = chat.reply("List RLMGraph's connected projects", [], None, None)
    turn = store.chat_turns(result["session_id"])[0]
    assert result["operation_route"] == "REGISTRY"
    assert turn.scope.value == "SYSTEM"
    assert turn.claim_id is None


def test_user_can_explicitly_create_claim_linked_self_work_without_chat_authority(
    tmp_path, monkeypatch,
):
    store = SQLiteGraphStore(tmp_path / "memory.db")
    store.initialize()
    project = _seed(store, tmp_path)
    current_state = indexed_project_fingerprint(tmp_path, [])
    claim = Claim(
        fingerprint="self-work", project_fingerprint=current_state,
        project_root=str(tmp_path), subject="user problem", producer="test",
        conclusion="Users cannot see recursive branch evidence.", confidence=.9,
    )
    task = SimpleNamespace(
        id="TASK-SELF", project_root=str(tmp_path), source_claim_ids=[],
        project_fingerprint=current_state,
    )
    store.save_claim(task, claim)
    ticket = TicketManager(store).create(
        project_id=project.id,
        title="Let users inspect recursive evidence",
        description="Expose the evidence needed to understand an answer.",
        acceptance_criteria=["A user can open every branch and its cited evidence."],
        constraints=["Do not grant chat write authority."], priority="MEDIUM",
        dependency_ticket_ids=[], budget=TicketBudget(), created_by="Observer user",
        source_claim_ids=[claim.id],
    )
    assert ticket.status == "DRAFT"
    assert ticket.execution_authorized is False
    assert ticket.source_claim_ids == [claim.id]
    assert any(
        edge.source == ticket.id and edge.target == claim.id
        and edge.relation.value == "DERIVED_FROM"
        for edge in store.edges()
    )

    claim.validity_status = ClaimValidity.INVALIDATED
    store.update_claim(claim)
    with pytest.raises(ValueError, match="source claims must be current"):
        TicketManager(store).create(
            project_id=project.id, title="Stale work", description="Must fail.",
            acceptance_criteria=["It fails closed."], constraints=[], priority="LOW",
            dependency_ticket_ids=[], budget=TicketBudget(), created_by="Observer user",
            source_claim_ids=[claim.id],
        )
