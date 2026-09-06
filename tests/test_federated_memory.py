from types import SimpleNamespace

from rlmgraph.federated_memory import FederatedConversationMemory
from rlmgraph.project_symbol_memory import ProjectSymbolMemory
from rlmgraph.project_task_graph import ProjectTaskGraph
from rlmgraph.repair_outcome_memory import RepairOutcomeMemoryStore


class Store:
    def __init__(self, project):
        self.project = project

    def projects(self):
        return [self.project]


def test_federated_retrieval_connects_repair_task_and_symbol_memory(tmp_path):
    project = tmp_path / "notes"
    project.mkdir()
    (project / "notes.py").write_text(
        "class NoteBook:\n    def update(self, note_id, text):\n        return text\n",
        encoding="utf-8",
    )
    ProjectSymbolMemory(tmp_path / "notes-symbol-memory.json").refresh(project)
    graph = ProjectTaskGraph(tmp_path / "rlmgraph-task-state.db")
    graph.initialize([{
        "task_id": 5, "objective": "Implement NoteBook.update",
        "acceptance": "Reject unknown IDs", "dependencies": [], "priority": 1,
    }])
    repair_store = RepairOutcomeMemoryStore(tmp_path / "rlmgraph-repair-memory.jsonl")
    repair = repair_store.remember(
        task_id=5, criterion="update_note", diagnosis="Unknown IDs were not rejected.",
        attempted_change="Raise KeyError before validating text.", attempt=1,
        target_passed=True, regressions=[], action_memory_id="ACTION-1",
        evidence_refs=["VALIDATION-1"],
    )
    gateway = FederatedConversationMemory(
        Store(SimpleNamespace(id="PROJECT-NOTES", root=str(project))), tmp_path
    )

    recalled = gateway.retrieve(
        "Why did notes repair NoteBook.update?", "PROJECT-NOTES", theories=[]
    )

    by_type = {item.memory_type: item for item in recalled}
    assert by_type["REPAIR_OUTCOME"].memory_id == repair.id
    assert by_type["REPAIR_OUTCOME"].status == "VERIFIED"
    assert by_type["REPAIR_OUTCOME"].details["target_passed"] is True
    assert by_type["TASK_STATE"].details["acceptance"] == "Reject unknown IDs"
    assert any(
        item.memory_type == "SYMBOL" and item.title == "NoteBook.update"
        for item in recalled
    )


def test_rejected_repair_is_not_presented_as_verified(tmp_path):
    store = RepairOutcomeMemoryStore(tmp_path / "repairs.jsonl")
    record = store.remember(
        task_id=1, criterion="contract", diagnosis="Guessed at the cause.",
        attempted_change="Changed validation order.", attempt=1,
        target_passed=False, regressions=["prior_contract"],
        action_memory_id="ACTION-2", evidence_refs=["VALIDATION-2"],
    )

    assert record.verified is False
    assert store.retrieve("Why did the repair fail?") == [record]
