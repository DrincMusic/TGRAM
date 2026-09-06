from types import SimpleNamespace

import pytest

from rlmgraph.project_access import project_access_question, project_access_reply


def registry(root, **overrides):
    values = {"id": "P1", "root": str(root), "read_only": True, "explicitly_selected": True}
    values.update(overrides)
    return SimpleNamespace(projects=lambda: [SimpleNamespace(**values)])


@pytest.mark.parametrize(
    "message",
    [
        "are you able to work inside of Atlas project?",
        "Can you work inside project Atlas?",
        "Could you access the Atlas project?",
        'Are you actually able to work within "Atlas"?',
    ],
)
def test_access_question_forms(message):
    result = project_access_question(message)
    assert result is not None
    assert result[1] == "Atlas"


@pytest.mark.parametrize("message", [
    "are you able to work on the project, RLMGraph?",
    "can you inspect project: RLMGraph?",
])
def test_project_punctuation(message):
    assert project_access_question(message)[1] == "RLMGraph"


def test_project_access_checks_actual_folder_and_never_falls_back_to_selection(tmp_path):
    root = tmp_path / "Atlas"
    root.mkdir()
    store = registry(root)
    answer = project_access_reply(store, ("work inside", "Atlas"), None)
    assert answer["answer"].startswith("Yes")
    assert answer["project_access"]["available"] is True
    unknown = project_access_reply(store, ("work inside", "Unknown"), "P1")
    assert unknown["answer"].startswith("No")
    assert unknown["project_access"]["project_id"] is None
    missing = project_access_reply(registry(root / "Missing"), ("access", "P1"), None)
    assert missing["answer"].startswith("No")
    assert missing["project_access"]["directory_accessible"] is False


def test_read_only_access_does_not_claim_direct_edit_authority(tmp_path):
    reply = project_access_reply(registry(tmp_path), ("edit", "P1"), None)
    assert reply["answer"].startswith("No")
    assert "approval" in reply["answer"]
    assert not reply["project_access"]["available"]
    reply = project_access_reply(
        registry(tmp_path, explicitly_selected=False), ("access", "P1"), None
    )
    assert not reply["project_access"]["available"]


def test_ambiguous_names_and_selected_project(tmp_path):
    store = registry(tmp_path)
    assert project_access_reply(store, ("access", "this"), "P1")["answer"].startswith("Yes")
    assert project_access_reply(store, ("access", "this"), None)["answer"].startswith("No")
    project = store.projects()[0]
    store.projects = lambda: [project, SimpleNamespace(**{**vars(project), "id": "P2"})]
    assert "which project" in project_access_reply(store, ("access", tmp_path.name), None)["answer"]


@pytest.mark.parametrize(
    "message",
    [
        "Can you actually reason?",
        "Can you read this file?",
        "Can you work on fixing the bug?",
        "Please edit Atlas project",
        "What are your weaknesses?",
    ],
)
def test_other_requests_keep_existing_routes(message):
    assert project_access_question(message) is None


def test_observer_persists_access_answer_without_interpreter_or_worker(tmp_path, monkeypatch):
    from rlmgraph.models import ProjectRecord, ProjectScan
    from rlmgraph.observer_chat import ObserverChat
    from rlmgraph.store import SQLiteGraphStore

    monkeypatch.setattr("rlmgraph.observer_chat.CodexCliInvestigator", lambda *args: object())
    monkeypatch.setattr(
        "rlmgraph.observer_chat.GraphGroundedSupervisor", lambda *args: SimpleNamespace()
    )
    store = SQLiteGraphStore(tmp_path / "access.db")
    store.initialize()
    root = tmp_path / "Atlas"
    root.mkdir()
    project = ProjectRecord(id="P1", root=str(root), explicitly_selected=True, read_only=True)
    scan = ProjectScan(project_id=project.id, root=str(root), read_only_verified=True)
    store.save_project_snapshot(project, scan, [], [], [], [])
    chat = ObserverChat(store)
    monkeypatch.setattr(chat, "_interpret", lambda *args: pytest.fail("Must not call a model"))
    result = chat.reply("are you able to work inside of Atlas project?", [], None, None)
    assert result["answer"].startswith("Yes")
    reopened = SQLiteGraphStore(tmp_path / "access.db")
    turn = reopened.chat_turns(result["session_id"])[0]
    assert turn.answer == result["answer"]
    assert turn.evidence[1]["path"] == str(root)
    correction = chat.reply("it should be already connected.", [], None, None, result["session_id"])
    assert "I rechecked" in correction["answer"]
    assert "Yes" in correction["answer"]
    explain = chat.reply("got what?", [], None, None, result["session_id"])
    assert "access to Atlas" in explain["answer"]
    assert "Yes" in explain["answer"]

    from rlmgraph.conversation_interpreter import MemoryInterpreter
    projection = MemoryInterpreter().reconstruct(
        result["session_id"], "What can we do next?", store.chat_turns(result["session_id"]), [],
    )
    assert len(projection.verbatim_turns) == 2
    assert projection.verbatim_turns[-1].assistant_answer == explain["answer"]
