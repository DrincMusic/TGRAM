from pathlib import Path

import pytest

from rlmgraph.dashboard import build_dashboard_snapshot
from rlmgraph.fingerprint import project_fingerprint, task_fingerprint
from rlmgraph.models import (
    Claim,
    ClaimValidity,
    Evidence,
    FileChangeKind,
    GraphRelation,
    InvestigationResult,
    Task,
)
from rlmgraph.onboarding import (
    ProjectSelection,
    ProjectSelectionError,
    ReadOnlyProjectOnboarder,
    ReadOnlyProjectView,
    ReadOnlyViolation,
    ReadOnlyWorkerBoundary,
)
from rlmgraph.store import SQLiteGraphStore


def fixture_project(tmp_path: Path) -> Path:
    root = tmp_path / "selected-project"
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "util.py").write_text("def clamp(value):\n    return max(0, value)\n")
    (root / "pkg" / "pricing.py").write_text(
        "from pkg.util import clamp\n\n"
        "class Calculator:\n"
        "    def discounted(self, price, percent):\n"
        "        return clamp(price * (1 - percent / 100))\n"
    )
    (root / "tests" / "test_pricing.py").write_text(
        "from pkg.pricing import Calculator\n\n"
        "def test_discounted():\n"
        "    assert Calculator().discounted(100, 10) == 90\n"
    )
    return root


def test_explicit_selection_and_storage_outside_project_are_mandatory(
    tmp_path: Path,
) -> None:
    root = fixture_project(tmp_path)
    with pytest.raises(ProjectSelectionError):
        ReadOnlyProjectOnboarder(SQLiteGraphStore(tmp_path / "graph.db")).scan(
            ProjectSelection(root=root, explicitly_selected=False)
        )
    with pytest.raises(ReadOnlyViolation, match="storage must be outside"):
        ReadOnlyProjectOnboarder(SQLiteGraphStore(root / "graph.db")).scan(
            ProjectSelection.explicit(root)
        )


def test_project_view_rejects_outside_and_absolute_reads(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("outside")
    view = ReadOnlyProjectView(ProjectSelection.explicit(root))

    assert "Calculator" in view.read_text("pkg/pricing.py")
    with pytest.raises(ReadOnlyViolation, match="escapes"):
        view.read_text("../secret.txt")
    with pytest.raises(ReadOnlyViolation, match="Absolute"):
        view.read_text(secret)


def test_initial_scan_builds_files_symbols_tests_and_dependencies(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")

    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))

    project = store.projects()[0]
    files = store.project_files(project.id)
    symbols = store.project_symbols(project.id)
    tests = store.project_tests(project.id)
    dependencies = store.project_dependencies(project.id)
    assert project.root == str(root.resolve())
    assert project.explicitly_selected and project.read_only
    assert scan.read_only_verified and scan.model_calls == 0
    assert scan.file_count == 4
    assert scan.parsed_file_count == 4
    assert {change.kind for change in scan.changes} == {FileChangeKind.ADDED}
    assert {item.path for item in files} == {
        "pkg/__init__.py",
        "pkg/pricing.py",
        "pkg/util.py",
        "tests/test_pricing.py",
    }
    assert {item.name for item in symbols} >= {"Calculator", "discounted", "clamp"}
    assert {item.name for item in tests} == {"test_discounted"}
    assert {item.import_name for item in dependencies} == {"pkg.util", "pkg.pricing"}
    assert all(item.target_file_id for item in dependencies)
    assert all(item.source_path and len(item.source_content_hash) == 64 for item in symbols)
    assert all(item.source_path and len(item.source_content_hash) == 64 for item in tests)
    assert all(item.source_path and len(item.source_content_hash) == 64 for item in dependencies)
    relations = {edge.relation for edge in store.edges()}
    assert relations >= {
        GraphRelation.HAS_PROJECT_SCAN,
        GraphRelation.CONTAINS_PROJECT_FILE,
        GraphRelation.OBSERVED_PROJECT_FILE,
        GraphRelation.DECLARES_SYMBOL,
        GraphRelation.DECLARES_TEST,
        GraphRelation.IMPORTS_DEPENDENCY,
        GraphRelation.DEPENDS_ON_FILE,
    }
    snapshot = build_dashboard_snapshot(store)
    node_types = {node["node_type"] for node in snapshot["nodes"]}
    assert node_types >= {
        "project",
        "project_scan",
        "project_file",
        "project_symbol",
        "project_test",
        "project_dependency",
    }
    assert snapshot["metrics"]["read_only_projects"] == 1
    assert snapshot["metrics"]["project_files"] == 4
    assert snapshot["metrics"]["scan_model_calls"] == 0


def test_generated_directories_are_ignored_case_insensitively_and_limits_are_enforced(
    tmp_path: Path,
) -> None:
    root = fixture_project(tmp_path)
    for generated in ("Binaries", "Intermediate", "Saved", "DerivedDataCache", "Content"):
        directory = root / generated
        directory.mkdir()
        (directory / "generated.cpp").write_text("class MustNotBeIndexed {};\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")

    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))

    assert scan.file_count == 4
    assert all("generated.cpp" not in item.path for item in store.project_files())
    with pytest.raises(ReadOnlyViolation, match="source-file scan limit"):
        ReadOnlyProjectOnboarder(
            SQLiteGraphStore(tmp_path / "limited.db"), max_source_files=3
        ).scan(ProjectSelection.explicit(root))


def test_text_parser_indexes_cpp_includes_without_regex_failure(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    (root / "pkg" / "feature.h").write_text(
        '#include "pkg/util.h"\nclass Feature {};\n'
    )
    (root / "pkg" / "util.h").write_text("class Utility {};\n")
    store = SQLiteGraphStore(tmp_path / "graph.db")

    scan = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))

    assert scan.file_count == 6
    assert any(item.import_name == "pkg/util.h" for item in store.project_dependencies())
    assert {item.name for item in store.project_symbols()} >= {"Feature", "Utility"}


def test_repeated_imports_are_one_relationship_and_cpp_comments_are_not_imports(
    tmp_path: Path,
) -> None:
    root = fixture_project(tmp_path)
    (root / "pkg" / "repeated.py").write_text(
        "import os\nif True:\n    import os\n", encoding="utf-8"
    )
    (root / "pkg" / "comments.cpp").write_text(
        '// import the configured registry\n#include "pkg/util.h"\n'
        '// import the configured registry again\n',
        encoding="utf-8",
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")

    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))

    repeated = [
        item for item in store.project_dependencies()
        if item.source_path == "pkg/repeated.py"
    ]
    comments = [
        item for item in store.project_dependencies()
        if item.source_path == "pkg/comments.cpp"
    ]
    assert [item.import_name for item in repeated] == ["os"]
    assert [item.import_name for item in comments] == ["pkg/util.h"]


def test_python_sibling_import_resolves_within_source_directory(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    (root / "tools").mkdir()
    (root / "tools" / "helper.py").write_text("VALUE = 1\n")
    (root / "tools" / "test_cli.py").write_text(
        "from helper import VALUE\n\ndef test_value():\n    assert VALUE == 1\n"
    )
    store = SQLiteGraphStore(tmp_path / "graph.db")

    ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(root))

    dependency = next(
        item
        for item in store.project_dependencies()
        if item.source_path == "tools/test_cli.py" and item.import_name == "helper"
    )
    helper = next(item for item in store.project_files() if item.path == "tools/helper.py")
    assert dependency.target_file_id == helper.id
    with pytest.raises(ReadOnlyViolation, match="source scan limit"):
        ReadOnlyProjectOnboarder(
            SQLiteGraphStore(tmp_path / "byte-limited.db"), max_source_bytes=10
        ).scan(ProjectSelection.explicit(root))
    with pytest.raises(ReadOnlyViolation, match="file exceeds"):
        ReadOnlyProjectOnboarder(
            SQLiteGraphStore(tmp_path / "file-limited.db"), max_file_bytes=10
        ).scan(ProjectSelection.explicit(root))


def test_unchanged_scan_reuses_every_file_without_parsing_or_model_calls(
    tmp_path: Path,
) -> None:
    root = fixture_project(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    onboarder = ReadOnlyProjectOnboarder(store)
    first = onboarder.scan(ProjectSelection.explicit(root))
    first_ids = {item.path: item.id for item in store.project_files()}

    second = onboarder.scan(ProjectSelection.explicit(root))

    assert second.previous_scan_id == first.id
    assert second.parsed_file_count == 0
    assert second.model_calls == 0
    assert set(second.reused_file_ids) == set(first_ids.values())
    assert {change.kind for change in second.changes} == {FileChangeKind.UNCHANGED}
    assert {item.path: item.id for item in store.project_files()} == first_ids
    assert len(store.project_scans()) == 2


def test_incremental_scan_tracks_modify_rename_delete_add_and_invalidates_claim(
    tmp_path: Path,
) -> None:
    root = fixture_project(tmp_path)
    store = SQLiteGraphStore(tmp_path / "graph.db")
    onboarder = ReadOnlyProjectOnboarder(store)
    onboarder.scan(ProjectSelection.explicit(root))
    pricing_id = next(
        item.id for item in store.project_files() if item.path == "pkg/pricing.py"
    )
    state = project_fingerprint(root)
    task = Task.create("How does clamp work?", root, task_fingerprint("clamp", state), state)
    store.save_task(task)
    claim = Claim(
        fingerprint=task.fingerprint,
        subject=task.question,
        producer="FixtureWorker",
        conclusion="clamp returns a non-negative value",
        confidence=0.9,
        evidence=[Evidence(path="pkg/util.py", line=2, detail="Uses max(0, value).")],
        files_examined=["pkg/util.py"],
    )
    store.save_claim(task, claim)

    (root / "pkg" / "util.py").write_text("def clamp(value):\n    return min(100, max(0, value))\n")
    (root / "pkg" / "pricing.py").rename(root / "pkg" / "discounts.py")
    (root / "tests" / "test_pricing.py").unlink()
    (root / "tests" / "test_discounts.py").write_text(
        "from pkg.discounts import Calculator\n\ndef test_discounted():\n    assert Calculator()\n"
    )

    scan = onboarder.scan(ProjectSelection.explicit(root))

    changes = {(item.kind, item.path, item.previous_path) for item in scan.changes}
    assert (FileChangeKind.MODIFIED, "pkg/util.py", None) in changes
    assert (FileChangeKind.RENAMED, "pkg/discounts.py", "pkg/pricing.py") in changes
    assert (FileChangeKind.DELETED, "tests/test_pricing.py", None) in changes
    assert (FileChangeKind.ADDED, "tests/test_discounts.py", None) in changes
    renamed = next(item for item in store.project_files() if item.path == "pkg/discounts.py")
    assert renamed.id == pricing_id
    deleted = store.project_files(include_deleted=True)
    assert any(item.path == "tests/test_pricing.py" and item.lifecycle.value == "DELETED" for item in deleted)
    persisted_claim = store.get_claim(claim.id)
    assert persisted_claim is not None
    assert persisted_claim.validity_status == ClaimValidity.INVALIDATED
    assert scan.invalidated_claim_ids == [claim.id]
    assert any(
        edge.source == claim.id
        and edge.relation == GraphRelation.INVALIDATED_BY_SCAN
        and edge.target == scan.id
        for edge in store.edges()
    )
    snapshot = build_dashboard_snapshot(store)
    assert claim.id in {node["id"] for node in snapshot["nodes"]}
    assert any(
        edge["source"] == claim.id
        and edge["relation"] == GraphRelation.INVALIDATED_BY_SCAN
        and edge["target"] == scan.id
        for edge in snapshot["edges"]
    )


class WriteAttemptWorker:
    def __init__(self, original: Path) -> None:
        self.original = original
        self.received_root: Path | None = None

    def investigate(self, question: str, project_root: Path) -> InvestigationResult:
        self.received_root = project_root
        target = project_root / "pkg" / "util.py"
        try:
            target.write_text("corrupted")
        except OSError:
            pass
        return InvestigationResult(
            conclusion="write attempted",
            confidence=0.1,
            files_changed=["pkg/util.py"],
        )


def test_worker_write_attempt_is_isolated_and_rejected(tmp_path: Path) -> None:
    root = fixture_project(tmp_path)
    original = (root / "pkg" / "util.py").read_text()
    worker = WriteAttemptWorker(root)
    boundary = ReadOnlyWorkerBoundary(ProjectSelection.explicit(root))

    with pytest.raises(ReadOnlyViolation, match="must not report project changes"):
        boundary.investigate(worker, "Try to edit the project")

    assert worker.received_root is not None
    assert worker.received_root != root
    assert not worker.received_root.is_relative_to(root)
    assert (root / "pkg" / "util.py").read_text() == original
