from pathlib import Path

from rlmgraph.models import (
    Assertion,
    ClaimValidity,
    Evidence,
    GraphRelation,
    InvestigationResult,
)
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.supervisor import Supervisor


class FileBackedInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        value = (project_root / "contract.txt").read_text().strip()
        return InvestigationResult(
            conclusion=f"The contract value is {value}.",
            confidence=0.99,
            evidence=[Evidence(path="contract.txt", line=1, detail="Authoritative value")],
            files_examined=["contract.txt", "notes.txt"],
            assertions=[Assertion(key="contract.value", value=value)],
        )


def test_unrelated_change_reuses_claim_by_supporting_file_provenance(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "contract.txt").write_text("alpha\n")
    (project / "notes.txt").write_text("first note\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = FileBackedInvestigator()
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("What is the contract value?", project)
    (project / "notes.txt").write_text("unrelated note changed\n")
    second = supervisor.run("What is the contract value?", project)

    assert first.claim.source_task_id == first.task.id
    assert first.claim.valid_from == first.task.project_fingerprint
    assert first.claim.learned_at is not None
    assert first.claim.source_files[0].path == "contract.txt"
    assert first.claim.source_files[0].evidence_lines == [1]
    assert second.cache_hit is True
    assert second.reuse_type == "provenance"
    assert second.claim.id == first.claim.id
    assert investigator.calls == 1
    assert any(
        edge.source == second.task.id
        and edge.relation == GraphRelation.REUSED
        and edge.target == first.claim.id
        for edge in store.edges()
    )


def test_changed_evidence_supersedes_old_claim_and_revert_reuses_history(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    contract = project / "contract.txt"
    contract.write_text("alpha\n")
    (project / "notes.txt").write_text("notes\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = FileBackedInvestigator()
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("What is the contract value?", project)
    contract.write_text("beta\n")
    replacement = supervisor.run("What is the contract value?", project)

    old = store.get_claim(first.claim.id)
    assert replacement.cache_hit is False
    assert replacement.claim.id != first.claim.id
    assert replacement.claim.assertions[0].value == "beta"
    assert old.validity_status == ClaimValidity.SUPERSEDED
    assert old.valid_until == replacement.task.project_fingerprint
    assert old.superseded_by_claim_id == replacement.claim.id
    assert [event.status for event in old.validity_history] == [
        ClaimValidity.CURRENT,
        ClaimValidity.INVALIDATED,
        ClaimValidity.SUPERSEDED,
    ]
    assert any(
        edge.source == replacement.claim.id
        and edge.relation == GraphRelation.SUPERSEDES
        and edge.target == first.claim.id
        for edge in store.edges()
    )

    contract.write_text("alpha\n")
    restored = supervisor.run("What is the contract value?", project)

    restored_old = store.get_claim(first.claim.id)
    stale_replacement = store.get_claim(replacement.claim.id)
    assert restored.cache_hit is True
    assert restored.claim.id == first.claim.id
    assert restored.claim.assertions[0].value == "alpha"
    assert investigator.calls == 2
    assert restored_old.validity_status == ClaimValidity.CURRENT
    assert restored_old.valid_until is None
    assert restored_old.validity_history[-1].status == ClaimValidity.CURRENT
    assert stale_replacement.validity_status == ClaimValidity.INVALIDATED


class UngroundedInvestigator:
    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.calls += 1
        return InvestigationResult(conclusion="A hypothesis", confidence=0.6)


def test_ungrounded_claim_is_restricted_to_exact_repository_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "state.txt").write_text("one\n")
    investigator = UngroundedInvestigator()
    supervisor = Supervisor(SQLiteGraphStore(tmp_path / "graph.db"), investigator)

    first = supervisor.run("What might be true?", project)
    (project / "unrelated.txt").write_text("new\n")
    second = supervisor.run("What might be true?", project)

    assert first.claim.source_files == []
    assert second.cache_hit is False
    assert investigator.calls == 2


def test_available_git_commit_is_recorded(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "contract.txt").write_text("alpha\n")
    (project / "notes.txt").write_text("notes\n")
    monkeypatch.setattr(
        "rlmgraph.provenance.repository_commit", lambda project_root: "abc123"
    )

    result = Supervisor(
        SQLiteGraphStore(tmp_path / "graph.db"), FileBackedInvestigator()
    ).run("What is the contract value?", project)

    assert result.claim.source_commit == "abc123"


def test_validation_never_crosses_project_boundaries(tmp_path: Path) -> None:
    first_project = tmp_path / "first"
    second_project = tmp_path / "second"
    first_project.mkdir()
    second_project.mkdir()
    for project, value in ((first_project, "alpha"), (second_project, "beta")):
        (project / "contract.txt").write_text(f"{value}\n")
        (project / "notes.txt").write_text("notes\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    investigator = FileBackedInvestigator()
    supervisor = Supervisor(store, investigator)

    first = supervisor.run("What is the contract value?", first_project)
    second = supervisor.run("What is the contract value?", second_project)

    persisted_first = store.get_claim(first.claim.id)
    assert second.cache_hit is False
    assert second.claim.id != first.claim.id
    assert investigator.calls == 2
    assert persisted_first.project_root == str(first_project.resolve())
    assert persisted_first.validity_status == ClaimValidity.CURRENT
    assert len(persisted_first.validity_history) == 1
