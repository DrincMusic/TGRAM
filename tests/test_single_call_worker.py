import hashlib

import pytest

from rlmgraph.implementation_sandbox import CodexPlanImplementationWorker
from rlmgraph.models import SingleCallSurgicalResult, SurgicalSymbolEdit


class FakeSingleCallAdapter:
    def __init__(self, result: SingleCallSurgicalResult) -> None:
        self.result = result
        self.calls = 0
        self.symbol_context = []
        self.reasoning_effort = None

    def single_call_surgical_edit(
        self, request, symbol_context, empty_root, *, reasoning_effort=None
    ):
        del request
        self.calls += 1
        self.symbol_context = symbol_context
        self.reasoning_effort = reasoning_effort
        assert list(empty_root.iterdir()) == []
        return self.result


def worker_with(result: SingleCallSurgicalResult) -> CodexPlanImplementationWorker:
    worker = object.__new__(CodexPlanImplementationWorker)
    worker.adapter = FakeSingleCallAdapter(result)
    worker.reasoning_effort = "max"
    return worker


def result_with(**edit) -> SingleCallSurgicalResult:
    return SingleCallSurgicalResult(
        rationale="updated", confidence=1, edits=[SurgicalSymbolEdit(**edit)]
    )


def test_worker_supplies_only_target_symbol_and_replaces_it_once(tmp_path) -> None:
    source = tmp_path / "pricing.py"
    source.write_text(
        "def unrelated():\n    return 'SECRET_CANARY_OUTSIDE_TARGET'\n\n"
        "def calculate_total(value):\n    return value\n",
        encoding="utf-8",
    )
    old = "def calculate_total(value):\n    return value\n"
    worker = worker_with(result_with(
        path="pricing.py", target_symbol="calculate_total",
        expected_hash=hashlib.sha256(old.encode()).hexdigest(),
        operation="REPLACE_SYMBOL",
        content="def calculate_total(value):\n    return value * 2",
    ))

    outcome = worker.implement("change calculate_total", [], tmp_path)

    assert worker.adapter.calls == 1
    supplied = "".join(item["source"] for item in worker.adapter.symbol_context)
    assert "calculate_total" in supplied
    assert "SECRET_CANARY_OUTSIDE_TARGET" not in supplied
    assert "return value * 2" in source.read_text(encoding="utf-8")
    assert "SECRET_CANARY_OUTSIDE_TARGET" in source.read_text(encoding="utf-8")
    assert outcome.files_changed == ["pricing.py"]
    assert outcome.model_calls == 1
    assert worker.adapter.reasoning_effort == "max"


def test_worker_inserts_after_an_authorized_symbol(tmp_path) -> None:
    source = tmp_path / "pricing.py"
    old = "def calculate_total(value):\n    return value\n"
    source.write_text(old, encoding="utf-8")
    worker = worker_with(result_with(
        path="pricing.py", target_symbol="calculate_total",
        expected_hash=hashlib.sha256(old.encode()).hexdigest(),
        operation="INSERT_AFTER", content="\ndef calculate_tax(value):\n    return value * .1",
    ))

    worker.implement("add calculate_tax after calculate_total", [], tmp_path)

    assert "def calculate_tax" in source.read_text(encoding="utf-8")


def test_worker_restores_nested_symbol_indentation(tmp_path) -> None:
    source = tmp_path / "taskboard.py"
    old = "    def __init__(self, name='Project'):\n        self.name = name\n"
    source.write_text(
        "class ProjectBoard:\n" + old + "\n"
        "    def __len__(self):\n        return 0\n",
        encoding="utf-8",
    )
    worker = worker_with(result_with(
        path="taskboard.py", target_symbol="ProjectBoard.__init__",
        expected_hash=hashlib.sha256(old.encode()).hexdigest(),
        operation="REPLACE_SYMBOL",
        content=(
            "def __init__(self, name=None):\n"
            "    self.name = 'Project' if name is None else name"
        ),
    ))

    outcome = worker.implement("make the board name optional", [], tmp_path)

    updated = source.read_text(encoding="utf-8")
    compile(updated, str(source), "exec")
    assert "    def __init__(self, name=None):" in updated
    assert "        self.name = 'Project' if name is None else name" in updated
    assert outcome.files_changed == ["taskboard.py"]


def test_worker_allows_no_change_and_ignores_model_hash_transcription(tmp_path) -> None:
    (tmp_path / "pricing.py").write_text(
        "def calculate_total(value):\n    return value\n", encoding="utf-8"
    )
    unchanged = worker_with(SingleCallSurgicalResult(
        rationale="already satisfied", confidence=1, edits=[]
    ))
    assert unchanged.implement("calculate_total", [], tmp_path).files_changed == []

    stale = worker_with(result_with(
        path="pricing.py", target_symbol="calculate_total", expected_hash="stale",
        operation="REPLACE_SYMBOL", content="def calculate_total(value):\n    return 2",
    ))
    stale.implement("calculate_total", [], tmp_path)
    assert "return 2" in (tmp_path / "pricing.py").read_text(encoding="utf-8")


def test_worker_rejects_live_symbol_change_during_model_call(tmp_path) -> None:
    source = tmp_path / "pricing.py"
    old = "def calculate_total(value):\n    return value\n"
    source.write_text(old, encoding="utf-8")
    worker = worker_with(result_with(
        path="pricing.py", target_symbol="calculate_total",
        expected_hash=hashlib.sha256(old.encode()).hexdigest(),
        operation="REPLACE_SYMBOL", content="def calculate_total(value):\n    return 2",
    ))
    original_call = worker.adapter.single_call_surgical_edit

    def mutate_during_call(
        request, symbol_context, empty_root, *, reasoning_effort=None
    ):
        result = original_call(
            request,
            symbol_context,
            empty_root,
            reasoning_effort=reasoning_effort,
        )
        source.write_text(
            "def calculate_total(value):\n    return value + 1\n", encoding="utf-8"
        )
        return result

    worker.adapter.single_call_surgical_edit = mutate_during_call

    with pytest.raises(ValueError, match="changed during the model call"):
        worker.implement("calculate_total", [], tmp_path)


def test_worker_rejects_unauthorized_edits(tmp_path) -> None:
    (tmp_path / "pricing.py").write_text(
        "def calculate_total(value):\n    return value\n", encoding="utf-8"
    )

    unauthorized = worker_with(result_with(
        path="pricing.py", target_symbol="not_supplied", expected_hash="x",
        operation="REPLACE_SYMBOL", content="def not_supplied():\n    return 2",
    ))
    with pytest.raises(ValueError, match="unauthorized symbol"):
        unauthorized.implement("calculate_total", [], tmp_path)


def test_worker_validates_all_files_before_writing_any(tmp_path) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first_old = "def first():\n    return 1\n"
    second_old = "def second():\n    return 2\n"
    first.write_text(first_old, encoding="utf-8")
    second.write_text(second_old, encoding="utf-8")
    worker = worker_with(SingleCallSurgicalResult(
        rationale="bad second edit", confidence=1,
        edits=[
            SurgicalSymbolEdit(
                path="first.py", target_symbol="first",
                expected_hash=hashlib.sha256(first_old.encode()).hexdigest(),
                operation="REPLACE_SYMBOL", content="def first():\n    return 10",
            ),
            SurgicalSymbolEdit(
                path="second.py", target_symbol="second",
                expected_hash=hashlib.sha256(second_old.encode()).hexdigest(),
                operation="REPLACE_SYMBOL", content="def second(:\n    return 20",
            ),
        ],
    ))

    with pytest.raises(SyntaxError):
        worker.implement("change first and second", [], tmp_path)

    assert first.read_text(encoding="utf-8") == first_old
    assert second.read_text(encoding="utf-8") == second_old
