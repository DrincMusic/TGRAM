from __future__ import annotations

import re
from pathlib import Path

from .memory_tokenization import PersistentMemoryTokenIndex, tokenize_memory
from .models import ConversationOperationalMemory, DeductiveTheory, ProjectArchitectureContext
from .project_symbol_memory import ProjectSymbolMemory
from .project_task_graph import ProjectTaskGraph
from .repair_outcome_memory import RepairOutcomeMemoryStore
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore

_WORDS = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


class FederatedConversationMemory(TokenizedMemoryStore):
    """Retrieve bounded references across stores without collapsing their ownership."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, store, system_root: Path | None) -> None:
        self.store = store
        self.system_root = system_root
        store_path = getattr(store, "path", None)
        index_root = Path(store_path) if store_path else (system_root or Path(".rlmgraph"))
        self.token_index = PersistentMemoryTokenIndex(
            Path(f"{index_root}.federated-memory"),
        )

    def retrieve(
        self, message: str, project_id: str | None, *, theories: list[DeductiveTheory],
        architecture_contexts: list[ProjectArchitectureContext] | None = None,
        limit: int = 12,
    ) -> list[ConversationOperationalMemory]:
        roots = self._roots(message, project_id)
        records: list[ConversationOperationalMemory] = []
        for remembered_project_id, root, scope in roots:
            records.extend(self._repairs(message, remembered_project_id, root, scope))
            records.extend(self._tasks(message, remembered_project_id, root, scope))
            records.extend(self._symbols(message, remembered_project_id, root, scope))
        records.extend(self._theories(message, theories))
        records.extend(self._architecture(message, architecture_contexts or []))
        deduplicated = {record.memory_id: record for record in records}
        ranked = sorted(
            deduplicated.values(),
            key=lambda item: (-item.relevance, -item.confidence, item.memory_id),
        )
        return ranked[:limit]

    def _roots(self, message: str, selected_project_id: str | None):
        projects_reader = getattr(self.store, "projects", None)
        projects = list(projects_reader()) if callable(projects_reader) else []
        lowered = message.casefold()
        roots = []
        system_hint = bool(re.search(
            r"\b(?:tgram|rlm\s*graph|you|your|yourself|system|engine|graph)\b",
            message, re.IGNORECASE,
        ))
        if system_hint and self.system_root:
            roots.append(("TGRAM-SYSTEM", self.system_root, "SYSTEM"))
        for project in projects:
            root = Path(project.root).resolve()
            if (
                project.id == selected_project_id
                or project.id.casefold() in lowered
                or root.name.casefold() in lowered
            ):
                roots.append((project.id, root, "PROJECT"))
        return roots

    def _repairs(self, query: str, project_id: str, root: Path, scope: str):
        candidates = [
            root / ".rlmgraph" / "repair-outcome-memory.jsonl",
            root.parent / "rlmgraph-repair-memory.jsonl",
        ]
        if scope == "SYSTEM":
            candidates.append(root / ".rlmgraph" / "system-repair-memory.jsonl")
            benchmark_root = root / ".rlmgraph" / "credible-benchmark" / "runs"
            if benchmark_root.is_dir():
                candidates.extend(sorted(
                    benchmark_root.rglob("rlmgraph-repair-memory.jsonl"),
                    key=lambda path: path.stat().st_mtime, reverse=True,
                )[:12])
        records = []
        for path in dict.fromkeys(candidates):
            if not path.is_file():
                continue
            for item in RepairOutcomeMemoryStore(path).retrieve(query, limit=4):
                records.append(ConversationOperationalMemory(
                    memory_id=item.id, memory_type="REPAIR_OUTCOME", scope=scope,
                    project_id=project_id, title=f"Repair of {item.criterion}",
                    summary=(
                        f"{item.observed_failure} Diagnosis: {item.diagnosis} "
                        f"Outcome: {'verified' if item.verified else 'not verified'}."
                    ),
                    status="VERIFIED" if item.verified else "REJECTED_THEORY",
                    confidence=1.0 if item.verified else .65,
                    evidence_refs=item.evidence_refs,
                    details={
                        "task_id": item.task_id, "attempt": item.attempt,
                        "attempted_change": item.attempted_change,
                        "target_passed": item.target_passed,
                        "regressions": item.regressions,
                        "action_memory_id": item.action_memory_id,
                    }, relevance=self._score(
                        query, item.criterion + " " + item.diagnosis, 5, item.id,
                    ),
                ))
        return records

    def _tasks(self, query: str, project_id: str, root: Path, scope: str):
        candidates = [
            root / ".rlmgraph" / "task-state.db",
            root.parent / "rlmgraph-task-state.db",
        ]
        records = []
        for path in candidates:
            if not path.is_file():
                continue
            for item in ProjectTaskGraph(path).snapshot():
                text = f"{item['objective']} {item['acceptance']} {item['failure']}"
                memory_id = f"TASK-{project_id}-{item['task_id']}"
                score = self._score(
                    query, text, 2 if item["status"] != "DONE" else 0, memory_id,
                )
                if score <= 0:
                    continue
                records.append(ConversationOperationalMemory(
                    memory_id=memory_id, memory_type="TASK_STATE",
                    scope=scope, project_id=project_id, title=item["objective"][:160],
                    summary=(
                        f"Task {item['task_id']} is {item['status']} after "
                        f"{item['attempt_count']} attempt(s). {item['failure']}"
                    ).strip(), status=item["status"], confidence=1.0,
                    evidence_refs=item["memory_refs"][:12],
                    details={
                        "acceptance": item["acceptance"], "dependencies": item["dependencies"],
                        "completed_at": item["completed_at"],
                    }, relevance=score,
                ))
        return records

    def _symbols(self, query: str, project_id: str, root: Path, scope: str):
        candidates = [
            root / ".rlmgraph" / "symbol-memory.json",
            root.parent / "rlmgraph-symbol-memory.json",
            root.parent / f"{root.name}-symbol-memory.json",
        ]
        records = []
        for path in candidates:
            if not path.is_file():
                continue
            for item in ProjectSymbolMemory(path).records():
                text = f"{item.path} {item.symbol} {item.signature} {' '.join(item.concepts)}"
                memory_id = f"SYMBOL-{item.content_hash[:12]}"
                score = self._score(query, text, memory_id=memory_id)
                if score <= 0:
                    continue
                records.append(ConversationOperationalMemory(
                    memory_id=memory_id, memory_type="SYMBOL",
                    scope=scope, project_id=project_id, title=item.symbol,
                    summary=f"{item.kind} {item.symbol} is in {item.path}:{item.start_line}.",
                    confidence=1.0, evidence_refs=[f"{item.path}:{item.start_line}"],
                    details={
                        "path": item.path, "signature": item.signature,
                        "dependencies": item.dependencies[:12],
                    }, relevance=score,
                ))
        return records

    def _theories(self, query: str, theories: list[DeductiveTheory]):
        records = []
        for theory in theories:
            text = f"{theory.subject} {theory.inference_rule} {theory.conclusion}"
            score = self._score(
                query, text, 1 if theory.status == "ACTIVE_THEORY" else 0, theory.id,
            )
            if score <= 0:
                continue
            records.append(ConversationOperationalMemory(
                memory_id=theory.id, memory_type="DEDUCTIVE_THEORY", scope="SYSTEM",
                title=theory.subject, summary=theory.conclusion, status=theory.status,
                confidence=theory.confidence,
                evidence_refs=[premise.source_id for premise in theory.premises],
                details={
                    "inference_rule": theory.inference_rule,
                    "falsifiers": theory.falsifiers,
                }, relevance=score,
            ))
        return records

    def _architecture(self, query: str, contexts: list[ProjectArchitectureContext]):
        records = []
        for context in contexts:
            for component in context.components:
                text = f"{component.name} {component.role} {' '.join(component.paths)}"
                memory_id = f"ARCHITECTURE-{context.project_id}-{component.name}"
                score = self._score(query, text, memory_id=memory_id)
                if score <= 0:
                    continue
                records.append(ConversationOperationalMemory(
                    memory_id=memory_id,
                    memory_type="ARCHITECTURE", scope=context.scope,
                    project_id=context.project_id, title=component.name,
                    summary=component.role, confidence=.9, evidence_refs=component.paths,
                    relevance=score,
                ))
        return records

    def _score(self, query: str, text: str, bonus: float = 0,
               memory_id: str | None = None) -> float:
        query_terms = set(_WORDS.findall(query.casefold()))
        text_terms = (
            self.token_index.terms(memory_id, text)
            if memory_id else set(tokenize_memory(text))
        )
        return float(len(query_terms.intersection(text_terms)) * 3 + bonus)
