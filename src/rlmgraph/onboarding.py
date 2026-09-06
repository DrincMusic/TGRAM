from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .fingerprint import file_content_hash, indexed_project_fingerprint, project_fingerprint
from .models import (
    FileChange,
    FileChangeKind,
    FileLifecycle,
    InvestigationResult,
    ProjectDependency,
    ProjectFile,
    ProjectRecord,
    ProjectScan,
    ProjectSymbol,
    ProjectTest,
    ScanStatus,
    SymbolKind,
)
from .provenance import assess_claim_from_index, record_validity
from .store import GraphStore, SQLiteGraphStore


class ProjectSelectionError(ValueError):
    pass


class ReadOnlyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectSelection:
    root: Path
    explicitly_selected: bool

    @classmethod
    def explicit(cls, root: str | Path) -> ProjectSelection:
        candidate = Path(root).resolve(strict=True)
        if not candidate.is_dir():
            raise ProjectSelectionError(f"Selected project root is not a directory: {candidate}")
        return cls(root=candidate, explicitly_selected=True)


class ReadOnlyProjectView:
    """Contain every scanner read within one explicitly selected root."""

    def __init__(self, selection: ProjectSelection) -> None:
        if not selection.explicitly_selected:
            raise ProjectSelectionError("Project access requires an explicit root selection.")
        self.root = selection.root

    def resolve(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ReadOnlyViolation("Absolute paths are not allowed in a project view.")
        candidate = (self.root / relative).resolve(strict=True)
        if not _is_relative_to(candidate, self.root):
            raise ReadOnlyViolation(f"Path escapes the selected project root: {relative}")
        return candidate

    def read_text(self, relative_path: str | Path) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")


@dataclass(frozen=True)
class _Source:
    path: str
    absolute_path: Path
    content_hash: str
    size_bytes: int
    modified_time_ns: int
    language: str
    is_test: bool
    content_read: bool


IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    ".rlmgraph",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    ".wrangler",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    "binaries",
    "content",
    "deriveddatacache",
    "intermediate",
    "saved",
}

DEFAULT_MAX_SOURCE_FILES = 10_000
DEFAULT_MAX_SOURCE_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024

LANGUAGES = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
}


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _test_file(path: str) -> bool:
    name = Path(path).name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or any(marker in name for marker in (".test.", ".spec.", "tests.cs"))
        or "tests" in Path(path).parts
    )


class ReadOnlyProjectOnboarder:
    """Incrementally projects an explicitly selected source tree into graph storage."""

    def __init__(
        self,
        store: GraphStore,
        *,
        max_source_files: int = DEFAULT_MAX_SOURCE_FILES,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    ) -> None:
        self.store = store
        self.max_source_files = max_source_files
        self.max_source_bytes = max_source_bytes
        self.max_file_bytes = max_file_bytes
        self.store.initialize()

    def scan(
        self, selection: ProjectSelection, *, force_parse_paths: set[str] | None = None
    ) -> ProjectScan:
        if not selection.explicitly_selected:
            raise ProjectSelectionError("Project onboarding requires an explicit root selection.")
        root = selection.root.resolve(strict=True)
        self._assert_storage_outside(root)
        canonical_root = str(root).casefold()
        for registered in self.store.projects():
            canonical_registered = str(Path(registered.root).resolve()).casefold()
            if canonical_registered == canonical_root:
                continue
            try:
                common = os.path.commonpath([canonical_root, canonical_registered]).casefold()
            except ValueError:
                continue
            if common in {canonical_root, canonical_registered}:
                raise ProjectSelectionError(
                    "Registered project roots must not overlap or contain one another."
                )
        before = self._manifest(root)
        project_id = _stable_id("PROJECT", str(root).casefold())
        previous_scans = self.store.project_scans(project_id)
        previous = previous_scans[-1] if previous_scans else None
        previous_files = self.store.project_files(project_id, include_deleted=True)
        previous_active = {
            item.path: item for item in previous_files if item.lifecycle == FileLifecycle.ACTIVE
        }
        sources = self._sources(root, previous_active)
        source_by_path = {item.path: item for item in sources}
        changes, ids_by_path = self._changes(project_id, previous_active, source_by_path)

        old_symbols = self.store.project_symbols(project_id)
        old_tests = self.store.project_tests(project_id)
        old_dependencies = self.store.project_dependencies(project_id)
        symbols_by_file = self._group(old_symbols)
        tests_by_file = self._group(old_tests)
        dependencies_by_file = self._group(old_dependencies, "source_file_id")

        scan = ProjectScan(
            project_id=project_id,
            root=str(root),
            previous_scan_id=previous.id if previous else None,
            changes=changes,
            started_at=datetime.now(UTC),
        )
        active_files: list[ProjectFile] = []
        symbols: list[ProjectSymbol] = []
        tests: list[ProjectTest] = []
        dependencies: list[ProjectDependency] = []
        changed_paths = {
            change.path
            for change in changes
            if change.kind != FileChangeKind.UNCHANGED
        }
        forced_paths = {path.replace("\\", "/") for path in (force_parse_paths or set())}
        unknown_forced = forced_paths - set(source_by_path)
        if unknown_forced:
            raise ReadOnlyViolation(
                "Forced incremental parse references unknown paths: "
                + ", ".join(sorted(unknown_forced))
            )
        parse_paths = changed_paths | forced_paths
        for source in sources:
            file_id = ids_by_path[source.path]
            item = ProjectFile(
                id=file_id,
                project_id=project_id,
                path=source.path,
                content_hash=source.content_hash,
                size_bytes=source.size_bytes,
                modified_time_ns=source.modified_time_ns,
                language=source.language,
                is_test=source.is_test,
                last_scan_id=scan.id,
            )
            active_files.append(item)
            if source.path not in parse_paths:
                symbols.extend(symbols_by_file.get(file_id, []))
                tests.extend(tests_by_file.get(file_id, []))
                dependencies.extend(dependencies_by_file.get(file_id, []))
                scan.reused_file_ids.append(file_id)
            else:
                parsed_symbols, parsed_tests, parsed_dependencies = self._parse(
                    project_id, item, source.absolute_path
                )
                symbols.extend(parsed_symbols)
                tests.extend(parsed_tests)
                dependencies.extend(parsed_dependencies)
                scan.parsed_file_count += 1

        active_ids = {item.id for item in active_files}
        path_to_id = {item.path: item.id for item in active_files}
        for dependency in dependencies:
            dependency.target_file_id = self._resolve_dependency(
                dependency.import_name,
                next(item.path for item in active_files if item.id == dependency.source_file_id),
                path_to_id,
            )
        tombstones = [
            ProjectFile(
                **item.model_dump(exclude={"lifecycle", "last_scan_id"}),
                lifecycle=FileLifecycle.DELETED,
                last_scan_id=scan.id,
            )
            for item in previous_files
            if item.id not in active_ids
        ]

        state = indexed_project_fingerprint(
            root, [(item.path, item.content_hash) for item in active_files]
        )
        for claim in self.store.claims():
            if not claim.project_root or Path(claim.project_root).resolve() != root:
                continue
            valid, reason = assess_claim_from_index(claim, active_files, state)
            was_valid = claim.validity_status.value == "CURRENT"
            if record_validity(claim, valid, state, reason):
                self.store.update_claim(claim)
            if was_valid and not valid:
                scan.invalidated_claim_ids.append(claim.id)

        after = self._manifest(root)
        if before != after:
            raise ReadOnlyViolation(
                "The selected project changed during onboarding; no graph snapshot was committed."
            )
        scan.file_count = len(active_files)
        scan.symbol_count = len(symbols)
        scan.test_count = len(tests)
        scan.dependency_count = len(dependencies)
        scan.content_read_file_count = sum(item.content_read for item in sources)
        scan.model_calls = 0
        scan.read_only_verified = True
        scan.status = ScanStatus.COMPLETED
        scan.completed_at = datetime.now(UTC)
        project = next(
            (item for item in self.store.projects() if item.id == project_id),
            ProjectRecord(
                id=project_id,
                root=str(root),
                explicitly_selected=True,
                read_only=True,
            ),
        )
        project.latest_scan_id = scan.id
        self.store.save_project_snapshot(
            project,
            scan,
            [*active_files, *tombstones],
            symbols,
            tests,
            dependencies,
        )
        return scan

    def _assert_storage_outside(self, root: Path) -> None:
        if not isinstance(self.store, SQLiteGraphStore):
            return
        storage = Path(self.store.path).resolve()
        if _is_relative_to(storage, root):
            raise ReadOnlyViolation(
                f"Graph storage must be outside the read-only project root: {storage}"
            )

    def _sources(
        self, root: Path, previous: dict[str, ProjectFile] | None = None
    ) -> list[_Source]:
        result: list[_Source] = []
        total_bytes = 0
        previous = previous or {}
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = sorted(
                name for name in names if name.casefold() not in IGNORED_DIRECTORIES
            )
            base = Path(directory)
            for name in sorted(filenames):
                candidate = base / name
                resolved = candidate.resolve()
                if not _is_relative_to(resolved, root) or not resolved.is_file():
                    continue
                language = LANGUAGES.get(resolved.suffix.lower())
                if language is None:
                    continue
                relative = resolved.relative_to(root).as_posix()
                metadata = resolved.stat()
                if metadata.st_size > self.max_file_bytes:
                    raise ReadOnlyViolation(
                        f"Source file exceeds the {self.max_file_bytes}-byte scan limit: {relative}"
                    )
                prior = previous.get(relative)
                content_read = not (
                    prior
                    and prior.size_bytes == metadata.st_size
                    and prior.modified_time_ns == metadata.st_mtime_ns
                )
                result.append(
                    _Source(
                        path=relative,
                        absolute_path=resolved,
                        content_hash=(
                            file_content_hash(resolved) if content_read else prior.content_hash
                        ),
                        size_bytes=metadata.st_size,
                        modified_time_ns=metadata.st_mtime_ns,
                        language=language,
                        is_test=_test_file(relative),
                        content_read=content_read,
                    )
                )
                total_bytes += metadata.st_size
                if len(result) > self.max_source_files:
                    raise ReadOnlyViolation(
                        f"Project exceeds the {self.max_source_files}-source-file scan limit."
                    )
                if total_bytes > self.max_source_bytes:
                    raise ReadOnlyViolation(
                        f"Project exceeds the {self.max_source_bytes}-byte source scan limit."
                    )
        return sorted(result, key=lambda item: item.path)

    def _manifest(self, root: Path) -> tuple[tuple[str, int, int], ...]:
        """Capture a no-content-read safety manifest around the scan."""
        result: list[tuple[str, int, int]] = []
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = sorted(
                name for name in names if name.casefold() not in IGNORED_DIRECTORIES
            )
            for name in sorted(filenames):
                candidate = (Path(directory) / name).resolve()
                if not _is_relative_to(candidate, root) or not candidate.is_file():
                    continue
                if LANGUAGES.get(candidate.suffix.lower()) is None:
                    continue
                metadata = candidate.stat()
                result.append(
                    (candidate.relative_to(root).as_posix(), metadata.st_size, metadata.st_mtime_ns)
                )
        return tuple(sorted(result))

    def _changes(self, project_id, previous, current):
        changes: list[FileChange] = []
        ids = {
            path: previous[path].id
            for path in current.keys() & previous.keys()
        }
        removed = set(previous) - set(current)
        added = set(current) - set(previous)
        removed_by_hash: dict[str, list[str]] = {}
        for path in sorted(removed):
            removed_by_hash.setdefault(previous[path].content_hash, []).append(path)
        renamed_old: set[str] = set()
        for path in sorted(added):
            matches = removed_by_hash.get(current[path].content_hash, [])
            old_path = next((item for item in matches if item not in renamed_old), None)
            if old_path:
                renamed_old.add(old_path)
                ids[path] = previous[old_path].id
                changes.append(
                    FileChange(
                        kind=FileChangeKind.RENAMED,
                        path=path,
                        previous_path=old_path,
                        content_hash=current[path].content_hash,
                        previous_hash=previous[old_path].content_hash,
                    )
                )
            else:
                ids[path] = _stable_id("FILE", project_id, path)
                changes.append(
                    FileChange(
                        kind=FileChangeKind.ADDED,
                        path=path,
                        content_hash=current[path].content_hash,
                    )
                )
        for path in sorted(removed - renamed_old):
            changes.append(
                FileChange(
                    kind=FileChangeKind.DELETED,
                    path=path,
                    previous_hash=previous[path].content_hash,
                )
            )
        for path in sorted(current.keys() & previous.keys()):
            old = previous[path]
            source = current[path]
            kind = (
                FileChangeKind.UNCHANGED
                if old.content_hash == source.content_hash
                else FileChangeKind.MODIFIED
            )
            changes.append(
                FileChange(
                    kind=kind,
                    path=path,
                    content_hash=source.content_hash,
                    previous_hash=old.content_hash,
                )
            )
        return sorted(changes, key=lambda item: (item.path, item.kind)), ids

    @staticmethod
    def _group(items, key: str = "file_id"):
        grouped = {}
        for item in items:
            grouped.setdefault(getattr(item, key), []).append(item)
        return grouped

    def _parse(self, project_id, file, path):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        if file.language == "python":
            return self._parse_python(project_id, file, text)
        return self._parse_text(project_id, file, text)

    def _parse_python(self, project_id, file, text):
        symbols: list[ProjectSymbol] = []
        tests: list[ProjectTest] = []
        dependencies: list[ProjectDependency] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return symbols, tests, dependencies

        class Visitor(ast.NodeVisitor):
            def __init__(self, outer):
                self.outer = outer
                self.classes: list[str] = []

            def visit_ClassDef(self, node):
                qualified = ".".join([*self.classes, node.name])
                symbols.append(self.outer._symbol(project_id, file, node.name, qualified, SymbolKind.CLASS, node.lineno))
                self.classes.append(node.name)
                self.generic_visit(node)
                self.classes.pop()

            def visit_FunctionDef(self, node):
                qualified = ".".join([*self.classes, node.name])
                kind = SymbolKind.METHOD if self.classes else SymbolKind.FUNCTION
                symbols.append(self.outer._symbol(project_id, file, node.name, qualified, kind, node.lineno))
                if node.name.startswith("test_") or file.is_test:
                    tests.append(self.outer._test(project_id, file, node.name, qualified, node.lineno, "pytest"))
                self.generic_visit(node)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Import(self, node):
                for alias in node.names:
                    dependencies.append(self.outer._dependency(project_id, file, alias.name))

            def visit_ImportFrom(self, node):
                prefix = "." * node.level
                dependencies.append(self.outer._dependency(project_id, file, prefix + (node.module or "")))

        Visitor(self).visit(tree)
        return symbols, tests, self._unique_dependencies(dependencies)

    def _parse_text(self, project_id, file, text):
        symbols: list[ProjectSymbol] = []
        tests: list[ProjectTest] = []
        dependencies: list[ProjectDependency] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            symbol = re.search(r"\b(class|function|def)\s+([A-Za-z_]\w*)", line)
            if symbol:
                kind = SymbolKind.CLASS if symbol.group(1) == "class" else SymbolKind.FUNCTION
                symbols.append(self._symbol(project_id, file, symbol.group(2), symbol.group(2), kind, line_number))
                if file.is_test or symbol.group(2).lower().startswith("test"):
                    tests.append(self._test(project_id, file, symbol.group(2), symbol.group(2), line_number, file.language))
            if file.language in {"c", "cpp", "csharp"}:
                imported = re.match(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', line)
            else:
                imported = re.match(
                    r'^\s*(?:from\s+|import\s*(?:\()?)([./A-Za-z0-9_@-]+)', line
                )
            if imported:
                dependencies.append(self._dependency(project_id, file, imported.group(1)))
        return symbols, tests, self._unique_dependencies(dependencies)

    @staticmethod
    def _unique_dependencies(dependencies):
        """Keep one graph edge for each source/import relationship."""
        return list({item.id: item for item in dependencies}.values())

    def _symbol(self, project_id, file, name, qualified, kind, line):
        return ProjectSymbol(
            id=_stable_id("SYMBOL", file.id, kind.value, qualified, str(line)),
            project_id=project_id,
            file_id=file.id,
            source_path=file.path,
            source_content_hash=file.content_hash,
            name=name,
            qualified_name=qualified,
            kind=kind,
            line=line,
        )

    def _test(self, project_id, file, name, qualified, line, framework):
        return ProjectTest(
            id=_stable_id("TEST", file.id, qualified, str(line)),
            project_id=project_id,
            file_id=file.id,
            source_path=file.path,
            source_content_hash=file.content_hash,
            name=name,
            qualified_name=qualified,
            line=line,
            framework=framework,
        )

    def _dependency(self, project_id, file, import_name):
        return ProjectDependency(
            id=_stable_id("DEPENDENCY", file.id, import_name),
            project_id=project_id,
            source_file_id=file.id,
            source_path=file.path,
            source_content_hash=file.content_hash,
            import_name=import_name,
        )

    @staticmethod
    def _resolve_dependency(import_name, source_path, path_to_id):
        source = Path(source_path)
        candidates: list[str] = []
        if import_name.startswith("."):
            level = len(import_name) - len(import_name.lstrip("."))
            base = source.parent
            for _ in range(max(level - 1, 0)):
                base = base.parent
            module = import_name.lstrip(".").replace(".", "/")
            candidates.extend([(base / f"{module}.py").as_posix(), (base / module / "__init__.py").as_posix()])
        elif import_name.startswith(("./", "../")):
            base = (source.parent / import_name).as_posix()
            candidates.extend([base, *(base + suffix for suffix in (".js", ".ts", ".tsx", ".jsx"))])
        else:
            module = import_name.replace(".", "/")
            candidates.extend([f"{module}.py", f"{module}/__init__.py", import_name])
            candidates.extend(
                [
                    (source.parent / f"{module}.py").as_posix(),
                    (source.parent / module / "__init__.py").as_posix(),
                    (source.parent / import_name).as_posix(),
                ]
            )
        return next((path_to_id[item] for item in candidates if item in path_to_id), None)


class ReadOnlyWorkerBoundary:
    """Give a worker a disposable mirror and never disclose the selected project path."""

    def __init__(self, selection: ProjectSelection) -> None:
        if not selection.explicitly_selected:
            raise ProjectSelectionError("Worker access requires an explicit project selection.")
        self.selection = selection

    def investigate(self, worker, question: str) -> InvestigationResult:
        original = self.selection.root
        before = project_fingerprint(original)
        with TemporaryDirectory(prefix="rlmgraph-readonly-") as directory:
            mirror = Path(directory) / "project"
            mirror.mkdir()
            for source, relative in self._safe_files(original):
                destination = mirror / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for path in mirror.rglob("*"):
                if path.is_file():
                    path.chmod(stat.S_IREAD)
            result = worker.investigate(question, mirror)
        after = project_fingerprint(original)
        if before != after:
            raise ReadOnlyViolation("The selected project changed while a worker was running.")
        if result.files_changed:
            raise ReadOnlyViolation(
                "Read-only workers must not report project changes: "
                + ", ".join(result.files_changed)
            )
        return result

    @staticmethod
    def _safe_files(root: Path):
        for directory, names, filenames in os.walk(root, followlinks=False):
            names[:] = sorted(name for name in names if name not in IGNORED_DIRECTORIES)
            for name in sorted(filenames):
                candidate = Path(directory) / name
                try:
                    resolved = candidate.resolve(strict=True)
                    relative = resolved.relative_to(root)
                except (OSError, ValueError):
                    continue
                if resolved.is_file():
                    yield resolved, relative


class BoundedReadOnlyWorkerBoundary:
    """Expose exactly an authorized file slice through a disposable read-only mirror."""

    def __init__(self, selection: ProjectSelection, allowed_paths: list[str]) -> None:
        if not selection.explicitly_selected:
            raise ProjectSelectionError("Bounded worker access requires explicit selection.")
        self.selection = selection
        self.allowed_paths = tuple(
            dict.fromkeys(path.replace("\\", "/") for path in allowed_paths)
        )
        if not self.allowed_paths:
            raise ReadOnlyViolation("A bounded worker requires at least one authorized file.")
        view = ReadOnlyProjectView(selection)
        for path in self.allowed_paths:
            view.resolve(path)

    def investigate(self, worker, question: str) -> InvestigationResult:
        original_before = self._authorized_fingerprint()
        with TemporaryDirectory(prefix="rlmgraph-slice-") as directory:
            mirror = Path(directory) / "project"
            mirror.mkdir()
            for relative in self.allowed_paths:
                source = ReadOnlyProjectView(self.selection).resolve(relative)
                destination = mirror / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            mirror_before = project_fingerprint(mirror)
            for path in mirror.rglob("*"):
                if path.is_file():
                    path.chmod(stat.S_IREAD)
            result = worker.investigate(question, mirror)
            mirror_after = project_fingerprint(mirror)
        if self._authorized_fingerprint() != original_before:
            raise ReadOnlyViolation(
                "An authorized source file changed while a bounded worker was running."
            )
        if mirror_after != mirror_before or result.files_changed:
            raise ReadOnlyViolation("A bounded read-only worker attempted to change its slice.")
        reported = {
            path.replace("\\", "/")
            for path in [
                *result.files_examined,
                *(evidence.path for evidence in result.evidence),
            ]
        }
        outside = sorted(reported - set(self.allowed_paths))
        if outside:
            raise ReadOnlyViolation(
                "Worker reported access outside its authorized slice: "
                + ", ".join(outside)
                + ". Authorized slice: "
                + ", ".join(self.allowed_paths)
            )
        return result

    def _authorized_fingerprint(self) -> str:
        view = ReadOnlyProjectView(self.selection)
        rows = [
            (relative, file_content_hash(view.resolve(relative)))
            for relative in self.allowed_paths
        ]
        return hashlib.sha256(repr(rows).encode()).hexdigest()
