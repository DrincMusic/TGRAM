from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .models import (
    ArchitectureComponent,
    ProjectArchitectureContext,
    SystemSelfModel,
    SystemWorkspace,
)


class ArchitectureProjector:
    """Build a bounded structural vocabulary for conversation interpretation."""

    def __init__(self, store, system_root: str | Path, max_files: int = 120) -> None:
        self.store = store
        self.system_root = Path(system_root).resolve()
        self.max_files = max_files

    def contexts(self, selected_project_id: str | None) -> list[ProjectArchitectureContext]:
        projects = self._items("projects")
        selected = next(
            (item for item in projects if item.id == selected_project_id), None
        )
        contexts = [self._context(None, self.system_root, "SYSTEM")]
        if selected is not None and not self._same_root(selected.root, self.system_root):
            contexts.append(self._context(selected, Path(selected.root), "PROJECT"))
        return contexts

    def system_workspace(self) -> SystemWorkspace:
        projects = [
            item for item in self._items("projects")
            if not self._same_root(getattr(item, "root", ""), self.system_root)
        ]
        return SystemWorkspace(
            root=str(self.system_root),
            purpose=(
                "Provide the durable tokenized-graph recursive agent memory engine that "
                "coordinates conversation, memory retrieval, workers, and loaded projects."
            ),
            action_memory_path=str(
                self.system_root / ".rlmgraph" / "system-action-memory.jsonl"
            ),
            loaded_project_ids=[item.id for item in projects],
        )

    @staticmethod
    def self_model() -> SystemSelfModel:
        return SystemSelfModel(
            aliases=[
                "TGRAM", "RLMGraph", "the engine", "the graph", "this graph", "this system", "this app",
                "you", "your", "yourself", "your own system",
            ],
            purpose=(
                "Maintain tokenized-graph recursive agent memory across conversation and loaded "
                "projects while coordinating bounded evidence-grounded work."
            ),
            capabilities=[
                "interpret conversation before workflow routing",
                "remember exact turns, semantic interpretations, and concepts",
                "inspect TGRAM's reserved system workspace when the user asks about the engine",
                "route repository questions through direct or recursive graph supervisors",
                "propose governed work without granting conversation write authority",
            ],
            authority_boundaries=[
                "self-description is context, not proof of implemented behavior",
                "self-reflection is read-only unless the user separately authorizes governed work",
                "conversation interpretation cannot approve or promote source changes",
            ],
            evidence_policy=(
                "For factual self-assessment, inspect current source, tests, persisted state, and "
                "runtime evidence; treat project documentation as stated intent."
            ),
        )

    def _context(self, project, root: Path, scope: str) -> ProjectArchitectureContext:
        project_id = getattr(project, "id", None)
        files = self._project_items("project_files", project_id)
        paths = [item.path for item in files[: self.max_files]]
        if not paths and root == self.system_root and root.exists():
            paths = self._system_paths(root)
        groups: dict[str, list[str]] = defaultdict(list)
        for path in paths:
            parts = Path(path).parts
            group = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
            groups[group].append(path.replace("\\", "/"))
        components = [
            ArchitectureComponent(
                name=name,
                role=self._role(name, grouped),
                paths=grouped[:12],
            )
            for name, grouped in sorted(groups.items())[:16]
        ]
        if scope == "SYSTEM":
            components = self._rlmgraph_identity_components()
        entry_points = [
            path for path in paths
            if Path(path).name.casefold() in {
                "cli.py", "dashboard.py", "main.py", "app.py", "page.tsx",
                "package.json", "pyproject.toml",
            }
        ][:16]
        concepts = list(dict.fromkeys(
            Path(path).stem.replace("_", " ")
            for path in paths
            if not Path(path).stem.startswith("test") and Path(path).stem != "__init__"
        ))[:40]
        if scope == "SYSTEM":
            concepts = [
                "ephemeral conversation interpreter",
                "reverse memory interpreter",
                "verbatim conversational memory",
                "intent and scope routing",
                "recursive graph investigation",
                "claims and evidence",
                "governed workflow authority",
            ]
        dependencies = self._project_items("project_dependencies", project_id)
        relationships = [
            f"{item.source_path} imports {item.import_name}"
            for item in dependencies[:40]
        ]
        if scope == "SYSTEM":
            relationships = [
                "ObserverChat sends each complete prompt to the ephemeral conversation interpreter before routing",
                "MemoryInterpreter retrieves semantic concepts and relevant verbatim turns for the next interpretation",
                "ObserverChat passes the exact prompt, interpreted concepts, and retrieved memory to graph supervisors",
                "Graph supervisors create evidence-backed tasks and claims; conversation interpretation grants no write authority",
            ]
        return ProjectArchitectureContext(
            project_id="TGRAM-SYSTEM" if scope == "SYSTEM" else project_id,
            project_name="TGRAM" if scope == "SYSTEM" else root.name,
            scope=scope,
            components=components,
            entry_points=entry_points,
            concepts=concepts,
            relationships=relationships,
        )

    def _system_paths(self, root: Path) -> list[str]:
        candidates = [root / "src", root / "dashboard" / "app"]
        paths = []
        for directory in candidates:
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix.casefold() in {
                    ".py", ".ts", ".tsx", ".js", ".json",
                }:
                    paths.append(path.relative_to(root).as_posix())
                    if len(paths) >= self.max_files:
                        return paths
        return paths

    @staticmethod
    def _rlmgraph_identity_components() -> list[ArchitectureComponent]:
        return [
            ArchitectureComponent(
                name="ConversationInterpreter",
                role="ephemeral meaning and concept extraction before workflow routing",
                paths=["src/rlmgraph/adapters.py", "src/rlmgraph/models.py"],
            ),
            ArchitectureComponent(
                name="MemoryInterpreter",
                role="reverse retrieval of remembered concepts and relevant exact conversation",
                paths=["src/rlmgraph/conversation_interpreter.py"],
            ),
            ArchitectureComponent(
                name="ObserverChat",
                role="conversation boundary, intent/scope routing, and authority separation",
                paths=["src/rlmgraph/observer_chat.py"],
            ),
            ArchitectureComponent(
                name="Graph supervisors",
                role="direct and recursive evidence-grounded investigation",
                paths=[
                    "src/rlmgraph/supervisor.py",
                    "src/rlmgraph/recursive_investigation.py",
                ],
            ),
            ArchitectureComponent(
                name="GraphStore",
                role="durable turns, interpretations, tasks, claims, and relationships",
                paths=["src/rlmgraph/store.py"],
            ),
        ]

    def _project_items(self, method: str, project_id: str | None) -> list:
        reader = getattr(self.store, method, None)
        if not callable(reader) or project_id is None:
            return []
        try:
            return list(reader(project_id))
        except (TypeError, ValueError):
            return []

    def _items(self, method: str) -> list:
        reader = getattr(self.store, method, None)
        return list(reader()) if callable(reader) else []

    @staticmethod
    def _same_root(left, right: Path) -> bool:
        try:
            return Path(left).resolve() == right
        except (OSError, TypeError, ValueError):
            return False

    @staticmethod
    def _role(name: str, paths: list[str]) -> str:
        lowered = name.casefold()
        if "test" in lowered or all("test" in path.casefold() for path in paths):
            return "validation"
        if "dashboard" in lowered or "app" in lowered:
            return "user interface"
        if "src" in lowered:
            return "runtime source"
        return "project support"
