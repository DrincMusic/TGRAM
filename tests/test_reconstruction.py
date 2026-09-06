from pathlib import Path

from rlmgraph.models import (
    Claim,
    Evidence,
    GraphEdge,
    GraphRelation,
    ReconstructionAction,
    Task,
)
from rlmgraph.reconstruction import ActiveMemoryReconstructor
from rlmgraph.store import SQLiteGraphStore


def save_claim(store, task, claim):
    store.save_claim(task, claim)
    return claim


def test_active_reconstruction_expands_dependencies_and_prunes_noise(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "contract.txt").write_text("sampling requires continuity\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = Task(
        id="TASK-query",
        question="Why does terrain sampling require face continuity?",
        fingerprint="query",
        project_fingerprint="state",
        project_root=str(project),
    )
    store.save_task(task)
    seed = save_claim(
        store,
        task,
        Claim(
            id="CLAIM-answer",
            fingerprint="answer",
            project_fingerprint="state",
            subject=task.question,
            producer="fixture",
            conclusion="Terrain sampling requires face continuity.",
            confidence=0.99,
            source_claim_ids=["CLAIM-evidence"],
        ),
    )
    evidence = save_claim(
        store,
        task,
        Claim(
            id="CLAIM-evidence",
            fingerprint="evidence",
            project_fingerprint="state",
            subject="Sampling contract",
            producer="fixture",
            conclusion="The contract requires continuous face coordinates.",
            confidence=1.0,
            evidence=[Evidence(path="contract.txt", line=1, detail="Continuity contract")],
            source_claim_ids=["CLAIM-observation"],
        ),
    )
    observation = save_claim(
        store,
        task,
        Claim(
            id="CLAIM-observation",
            fingerprint="observation",
            project_fingerprint="state",
            subject="Observed seam test",
            producer="fixture",
            conclusion="The seam test passes only with continuous coordinates.",
            confidence=1.0,
            evidence=[Evidence(path="contract.txt", line=1, detail="Observed requirement")],
        ),
    )
    store.save_edge(
        GraphEdge(
            source=seed.id,
            relation=GraphRelation.DERIVED_FROM,
            target=evidence.id,
        )
    )
    store.save_edge(
        GraphEdge(
            source=evidence.id,
            relation=GraphRelation.DERIVED_FROM,
            target=observation.id,
        )
    )
    distractors = []
    for index in range(8):
        distractor = save_claim(
            store,
            task,
            Claim(
                id=f"CLAIM-noise-{index}",
                fingerprint=f"noise-{index}",
                project_fingerprint="state",
                subject=f"Unrelated editor history {index}",
                producer="fixture",
                conclusion="UI color and character animation notes " * 8,
                confidence=0.9,
            ),
        )
        distractors.append(distractor)
        store.save_edge(
            GraphEdge(
                source=seed.id,
                relation=GraphRelation.SUPPORTS,
                target=distractor.id,
            )
        )

    session = ActiveMemoryReconstructor(store, seed_count=1).reconstruct(
        task,
        [seed, evidence, observation, *distractors],
        required_evidence_ids=[evidence.id, observation.id],
    )
    store.save_reconstruction(session)

    assert session.seed_node_ids == [seed.id]
    assert session.selected_node_ids == [seed.id, evidence.id, observation.id]
    assert set(session.pruned_node_ids) == {claim.id for claim in distractors}
    assert session.evidence_preserved is True
    assert session.reconstructed_token_estimate < session.baseline_token_estimate
    assert len(session.selected_node_ids) < len(session.baseline_node_ids)
    assert [step.action for step in session.steps].count(ReconstructionAction.EXPAND) == 2
    assert [step.action for step in session.steps].count(ReconstructionAction.PRUNE) == 8
    persisted = store.get_reconstruction(session.id)
    assert persisted == session
    assert any(
        edge.source == task.id
        and edge.relation == GraphRelation.HAS_RECONSTRUCTION
        and edge.target == session.id
        for edge in store.edges()
    )


def test_missing_required_evidence_marks_reconstruction_incomplete(tmp_path: Path) -> None:
    store = SQLiteGraphStore(tmp_path / "graph.db")
    store.initialize()
    task = Task(
        question="Find required evidence",
        fingerprint="query",
        project_root=str(tmp_path),
    )
    claim = Claim(
        fingerprint="claim",
        subject=task.question,
        producer="fixture",
        conclusion="Partial answer",
        confidence=0.9,
    )

    session = ActiveMemoryReconstructor(store, seed_count=1).reconstruct(
        task, [claim], required_evidence_ids=["CLAIM-missing"]
    )

    assert session.evidence_preserved is False
    assert session.status.value == "INCOMPLETE"
