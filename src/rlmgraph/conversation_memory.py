from __future__ import annotations

import re
from pathlib import Path

from .conversation_interpreter import MemoryInterpreter
from .episodic_recall import retrieve_episodes
from .federated_memory import FederatedConversationMemory
from .memory_association import MemoryAssociationEngine
from .models import (
    ChatTurn,
    ConversationActionMemory,
    ConversationFact,
    ConversationFactKind,
    ConversationInterpretationRecord,
    ConversationMemoryProjection,
    MemoryLayerModel,
    MemorySystemState,
)
from .neural_memory import NeuralMemoryRanker
from .project_action_memory import ProjectActionMemory
from .system_evaluation_memory import SystemEvaluationMemoryStore


class ConversationMemoryPipeline:
    """Conversation-only persistence, consolidation, and bounded recall."""

    _IDENTITY = re.compile(
        r"^(?P<owner>this|the|my|our)\s+"
        r"(?P<subject>project|system|app|application|graph|repository|repo)\s+"
        r"(?:is|is called|is named|means|refers to)\s+(?P<value>.+?)\s*[.!]?$",
        re.IGNORECASE,
    )

    def __init__(
        self, store, interpreter: MemoryInterpreter | None = None,
        relationship_interpreter=None, system_root: str | Path | None = None,
    ) -> None:
        self.store = store
        self.system_root = Path(system_root).resolve() if system_root else None
        self.interpreter = interpreter or MemoryInterpreter()
        self.associations = MemoryAssociationEngine(
            store,
            interpreter=(
                relationship_interpreter
                if callable(getattr(relationship_interpreter, "interpret_relationship", None))
                else None
            ),
        )
        self.neural_ranker = NeuralMemoryRanker(store)
        self.federated_memory = FederatedConversationMemory(store, self.system_root)

    def reconstruct(
        self, session_id: str, message: str, turns: list[ChatTurn],
        records: list[ConversationInterpretationRecord], project_id: str | None = None,
        *, profile_id: str = "LOCAL-LEGACY", include_legacy_memory: bool = False,
    ) -> ConversationMemoryProjection:
        global_turns, global_records = self._global_history(
            turns, records, profile_id, include_legacy_memory
        )
        profile_session_ids = self._session_ids(profile_id, include_legacy_memory)
        projection = self.interpreter.reconstruct(
            session_id, message, global_turns, global_records
        )
        self._set_episodes(projection, global_turns, message)
        from .latency_memory import latency_observations
        projection.latency_observations = latency_observations(profile_id)
        if (project_id and getattr(self.store, "path", None)
                and any(project.id == project_id for project in self.store.projects())):
            from .project_world_memory import ProjectWorldMemory
            world = ProjectWorldMemory(self.store).search(message, project_id)
            projection.relevant_lessons = [item["payload"] for item in world["memories"]
                                          if item["kind"] == "LESSON"]
            projection.relevant_world_memories = [item for item in world["memories"]
                                                  if item["kind"] != "LESSON"]
            projection.world_neural_state = world["neural_state"]
        # Worker claims and evidence cross only through a future explicit bridge.
        projection.relevant_claim_ids = []
        (
            projection.relevant_facts,
            projection.neural_memory_scores,
            rescued_memory_ids,
        ) = self._retrieve_facts(
            session_id, message, profile_session_ids
        )
        projection.neural_memory_state = self.neural_ranker.state(rescued_memory_ids)
        projection.relevant_profile_memories = self._retrieve_profile_memories(
            session_id, message, profile_session_ids
        )
        projection.relevant_action_memories = self._retrieve_action_memories(
            message, project_id
        )
        projection.relevant_evaluation_memories = self._retrieve_evaluation_memories(
            message
        )
        known_fact_ids = {fact.id for fact in projection.relevant_facts}
        projection.relevant_facts.extend(
            fact for fact in projection.relevant_profile_memories
            if fact.id not in known_fact_ids
        )
        projection.relevant_associations = self._retrieve_associations(
            session_id, projection.relevant_facts, profile_session_ids
        )
        association_ids = {item.id for item in projection.relevant_associations}
        interpretation_reader = getattr(
            self.store, "memory_relationship_interpretations", None
        )
        projection.relevant_relationship_interpretations = (
            [
                item for item in interpretation_reader(session_id)
                if item.association_id in association_ids
            ][:12]
            if callable(interpretation_reader) else []
        )
        fact_ids = {fact.id for fact in projection.relevant_facts}
        cluster_reader = getattr(self.store, "memory_clusters", None)
        projection.relevant_memory_clusters = (
            sorted(
                [
                    item for item in cluster_reader(session_id)
                    if fact_ids.intersection(item.supporting_fact_ids)
                ],
                key=lambda item: (-item.abstraction_level, -item.confidence, item.id),
            )[:12]
            if callable(cluster_reader) else []
        )
        branch_reader = getattr(self.store, "concept_branches", None)
        projection.relevant_concept_branches = (
            [
                item for item in branch_reader(session_id)
                if fact_ids.intersection(item.supporting_fact_ids)
            ][:12]
            if callable(branch_reader) else []
        )
        theory_reader = getattr(self.store, "deductive_theories", None)
        projection.relevant_theories = (
            self._retrieve_theories(
                session_id, message, theory_reader, profile_session_ids
            )
            if callable(theory_reader) else []
        )
        report_reader = getattr(self.store, "self_assessment_reports", None)
        projection.recent_self_assessments = (
            self._global_items(report_reader, session_id, profile_session_ids)[-4:]
            if callable(report_reader) else []
        )
        projection.memory_system = self._memory_system(
            session_id, turns, records, projection.relevant_facts
        )
        projection.memory_system.live_record_counts["retrieved_project_actions"] = len(
            projection.relevant_action_memories
        )
        projection.memory_system.live_record_counts["retrieved_system_evaluations"] = len(
            projection.relevant_evaluation_memories
        )
        projection.token_estimate += sum(
            len(fact.subject) + len(fact.predicate) + len(fact.value)
            for fact in projection.relevant_facts
        ) // 4
        return projection

    def enrich_operational_memory(
        self, projection: ConversationMemoryProjection, message: str,
        project_id: str | None,
    ) -> None:
        projection.relevant_operational_memories = self.federated_memory.retrieve(
            message, project_id, theories=projection.relevant_theories,
            architecture_contexts=projection.architecture_contexts,
        )
        if projection.memory_system is not None:
            projection.memory_system.live_record_counts["retrieved_operational_memories"] = len(
                projection.relevant_operational_memories
            )

    def _retrieve_evaluation_memories(self, message: str) -> list:
        if self.system_root is None or not re.search(
            r"\b(?:test|trial|benchmark|evaluation|score|pass rate|tokens?|savings)\b",
            message, re.IGNORECASE,
        ):
            return []
        path = self.system_root / ".rlmgraph" / "system-evaluation-memory.jsonl"
        if not path.is_file():
            return []
        return SystemEvaluationMemoryStore(path).retrieve(message)

    def _retrieve_action_memories(
        self, message: str, selected_project_id: str | None
    ) -> list[ConversationActionMemory]:
        """Resolve a project boundary, then expose only bounded parsed change memories."""
        project_reader = getattr(self.store, "projects", None)
        projects = list(project_reader()) if callable(project_reader) else []
        lowered = message.casefold()
        system_recall = bool(re.search(
            r"\b(?:tgram|rlm\s*graph|this (?:system|engine)|the engine|"
            r"your (?:memory|architecture|system|engine|code|capabilit(?:y|ies)|"
            r"identity|weakness|action memory))\b",
            message, re.IGNORECASE,
        ))
        selected = []
        if not system_recall:
            for project in projects:
                name = Path(project.root).name
                mentioned = (
                    project.id.casefold() in lowered
                    or (name and name.casefold() in lowered)
                )
                if project.id == selected_project_id or mentioned:
                    selected.append(project)
        if not selected and not system_recall:
            return []

        recalled: list[ConversationActionMemory] = []
        seen_paths: set[Path] = set()
        if system_recall and self.system_root:
            system_candidates = [
                self.system_root / ".rlmgraph" / "system-action-memory.jsonl",
                self.system_root / ".rlmgraph" / "project-action-memory"
                / "TGRAM-SYSTEM.jsonl",
            ]
            recalled.extend(self._action_records(
                message=message,
                project_id="TGRAM-SYSTEM",
                project_name="TGRAM",
                root=self.system_root,
                candidates=system_candidates,
                seen_paths=seen_paths,
            ))
        for project in selected:
            root = Path(project.root).resolve()
            candidates = [
                root / ".rlmgraph" / "action-memory.jsonl",
                root.parent / "rlmgraph-action-memory.jsonl",
            ]
            if self.system_root:
                candidates.append(
                    self.system_root / ".rlmgraph" / "project-action-memory"
                    / f"{project.id}.jsonl"
                )
            recalled.extend(self._action_records(
                message=message,
                project_id=project.id,
                project_name=Path(project.root).name,
                root=root,
                candidates=candidates,
                seen_paths=seen_paths,
            ))
        recalled.sort(key=lambda item: (-item.relevance, -item.milestone, item.memory_id))
        return recalled[:8]

    @staticmethod
    def _action_records(
        *, message: str, project_id: str, project_name: str, root: Path,
        candidates: list[Path], seen_paths: set[Path],
    ) -> list[ConversationActionMemory]:
        recalled = []
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen_paths or not resolved.is_file():
                continue
            seen_paths.add(resolved)
            memory = ProjectActionMemory(resolved, max_records=6, char_budget=1800)
            records = memory.records()
            current_milestone = max(
                (record.milestone_index for record in records), default=0
            ) + 1
            for item in memory.retrieve(message, current_milestone=current_milestone):
                recalled.append(ConversationActionMemory(
                    project_id=project_id,
                    project_name=project_name,
                    project_root=str(root),
                    memory_id=item["memory_id"],
                    milestone=item["milestone"],
                    phase=item["phase"],
                    action=item["action"],
                    invariant=item["invariant"],
                    files=item.get("files", []),
                    symbols=item.get("symbols", []),
                    confidence=item["confidence"],
                    archive_ref=item.get("archive_ref", ""),
                    relevance=item.get("relevance", 0.0),
                ))
        return recalled

    def learn_from_usage(
        self, session_id: str, message: str, facts: list[ConversationFact],
        used_fact_ids: list[str],
    ) -> None:
        self.neural_ranker.reinforce(
            message, facts, set(used_fact_ids), session_id
        )

    def _session_ids(
        self, profile_id: str | None = None, include_legacy_memory: bool = False
    ) -> list[str]:
        reader = getattr(self.store, "chat_sessions", None)
        if not callable(reader):
            return []
        allowed = {profile_id} if profile_id else None
        if allowed is not None and include_legacy_memory:
            allowed.add("LOCAL-LEGACY")
        return [
            item.id for item in reader()
            if allowed is None or item.profile_id in allowed
        ]

    def _global_items(
        self, reader, fallback_session_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> list:
        items = []
        if session_ids is None and fallback_session_id:
            session = next(
                (item for item in getattr(self.store, "chat_sessions", list)()
                 if item.id == fallback_session_id), None,
            )
            session_ids = self._session_ids(session.profile_id) if session else []
        session_ids = list(session_ids if session_ids is not None else self._session_ids())
        if fallback_session_id and fallback_session_id not in session_ids:
            session_ids.append(fallback_session_id)
        for remembered_session_id in session_ids:
            turn_reader = getattr(self.store, "chat_turns", None)
            superseded = {
                turn.id for turn in turn_reader(remembered_session_id) if turn.superseded_by_turn_id
            } if callable(turn_reader) else set()
            items.extend(
                item for item in reader(remembered_session_id)
                if getattr(item, "source_turn_id", None) not in superseded
            )
        return sorted(items, key=lambda item: item.created_at)

    def _global_history(self, turns, records, profile_id=None, include_legacy_memory=False):
        turn_reader = getattr(self.store, "chat_turns", None)
        record_reader = getattr(self.store, "conversation_interpretations", None)
        if not callable(turn_reader) or not callable(record_reader):
            return turns, records
        session_ids = self._session_ids(profile_id, include_legacy_memory)
        all_turns = sorted(
            [item for remembered in session_ids for item in turn_reader(remembered)],
            key=lambda item: item.created_at,
        )
        all_records = sorted(
            [item for remembered in session_ids for item in record_reader(remembered)],
            key=lambda item: item.created_at,
        )
        superseded = {turn.id for turn in all_turns if turn.superseded_by_turn_id}
        return (
            [turn for turn in (all_turns or turns) if not turn.superseded_by_turn_id],
            [record for record in (all_records or records) if record.turn_id not in superseded],
        )

    @staticmethod
    def _set_episodes(memory, turns, query):
        previous = sum(len(item.user_message) + len(item.assistant_answer) for item in memory.verbatim_turns)
        memory.verbatim_turns = retrieve_episodes(turns, query, memory.session_id)
        memory.relevant_turn_ids = [item.turn_id for item in memory.verbatim_turns]
        current = sum(len(item.user_message) + len(item.assistant_answer) for item in memory.verbatim_turns)
        memory.token_estimate = max(0, memory.token_estimate + (current - previous) // 4)

    def retry_dialogue(self, memory, query, profile_id, include_legacy_memory=False):
        session_ids = self._session_ids(profile_id, include_legacy_memory)
        turns = sorted(
            [turn for sid in session_ids for turn in self.store.chat_turns(sid)],
            key=lambda turn: turn.created_at,
        )
        self._set_episodes(memory, turns, query)

    def _retrieve_theories(
        self, session_id: str, message: str, reader, session_ids: list[str] | None = None
    ) -> list:
        """Recall active/relevant learned theories without turning them into fixed identity."""
        terms = set(re.findall(r"[a-z0-9_]+", message.casefold()))
        theories = self._global_items(reader, session_id, session_ids)
        scored = []
        for ordinal, theory in enumerate(theories):
            text = " ".join((
                theory.subject,
                theory.inference_rule,
                theory.conclusion,
                " ".join(premise.statement for premise in theory.premises),
            )).casefold()
            theory_terms = self.neural_ranker.terms(f"THEORY:{theory.id}", text)
            overlap = len(terms & theory_terms)
            active = 2 if theory.status == "ACTIVE_THEORY" else 0
            recency = (ordinal + 1) / max(len(theories), 1)
            scored.append((overlap * 3 + active + theory.confidence + recency, theory))
        return [item[1] for item in sorted(scored, key=lambda item: -item[0])[:12]]

    def _memory_system(
        self, session_id: str, turns: list[ChatTurn],
        records: list[ConversationInterpretationRecord], facts: list[ConversationFact],
    ) -> MemorySystemState:
        def count(method: str) -> int:
            reader = getattr(self.store, method, None)
            return len(list(reader(session_id))) if callable(reader) else 0

        proposal_reader = getattr(self.store, "self_improvement_proposals", None)
        proposals = (
            [item for item in proposal_reader() if item.session_id == session_id]
            if callable(proposal_reader) else []
        )
        return MemorySystemState(
            identity_statement=(
                "TGRAM is the durable tokenized graph, conversation state, retrieval rules, and governed "
                "coordination that persist across disposable language-model calls. The called LLMs "
                "interpret input, investigate bounded questions, or phrase responses; they are not "
                "the durable identity or memory of TGRAM."
            ),
            interpreter_role=(
                "Translate one complete human prompt into a typed meaning hypothesis; retain no "
                "private state after returning the schema."
            ),
            responder_role=(
                "Translate current typed conversation state into natural language without worker "
                "authority or private durable memory."
            ),
            worker_role=(
                "Perform a bounded evidence-seeking investigation from an explicit read-only work "
                "request and return task/claim provenance."
            ),
            layers=[
                MemoryLayerModel(
                    name="system_workspace",
                    role=(
                        "Anchor TGRAM's permanent identity, internal architecture, and system "
                        "action history outside the loaded-project registry."
                    ),
                    owns=["TGRAM-SYSTEM identity", "internal architecture", "system actions"],
                    excludes=["loaded project identity", "implicit source-write authority"],
                    persistence="Reserved system root and typed system manifest",
                    source_ids=["src/rlmgraph/architecture_context.py"],
                ),
                MemoryLayerModel(
                    name="conversation_memory",
                    role="Maintain human dialogue continuity and self/context state.",
                    owns=["exact turns", "interpretations", "reflection", "conversation facts"],
                    excludes=["repository claims", "worker evidence", "mutation authority"],
                    persistence="SQLite or Neo4j, scoped by chat session",
                    source_ids=["src/rlmgraph/conversation_memory.py", "src/rlmgraph/store.py"],
                ),
                MemoryLayerModel(
                    name="worker_memory",
                    role="Maintain evidence-grounded repository tasks, claims, and provenance.",
                    owns=["tasks", "claims", "evidence", "validity", "contradictions"],
                    excludes=["user statements as repository truth", "conversation authority"],
                    persistence="GraphStore with source and validity provenance",
                    source_ids=["src/rlmgraph/supervisor.py", "src/rlmgraph/store.py"],
                ),
                MemoryLayerModel(
                    name="project_action_memory",
                    role=(
                        "Recall compact records of completed project changes by project, "
                        "functionality, file, and symbol."
                    ),
                    owns=[
                        "parsed completed actions", "changed file paths", "changed symbols",
                        "task invariants", "action archive references",
                    ],
                    excludes=[
                        "raw worker context", "user profile facts", "mutation authority",
                    ],
                    persistence="Bounded project-scoped JSONL action records",
                    source_ids=["src/rlmgraph/project_action_memory.py"],
                ),
                MemoryLayerModel(
                    name="system_evaluation_memory",
                    role=(
                        "Remember evaluations TGRAM underwent, including methodology, models, "
                        "quality gates, measurements, limitations, and source reports."
                    ),
                    owns=[
                        "evaluation methodology", "quality-gated results", "model identities",
                        "evaluation limitations", "invalidated-run provenance",
                    ],
                    excludes=[
                        "unqualified savings claims", "project actions", "workflow authority",
                    ],
                    persistence="Append-only system-scoped JSONL evaluation records",
                    source_ids=["src/rlmgraph/system_evaluation_memory.py"],
                ),
                MemoryLayerModel(
                    name="federated_operational_memory",
                    role=(
                        "Retrieve bounded task, symbol, theory, architecture, and causal repair "
                        "records while preserving separate source stores."
                    ),
                    owns=[
                        "typed cross-store references", "repair verification outcomes",
                        "task state", "symbol addresses", "deductive theories",
                    ],
                    excludes=["raw project context", "automatic truth promotion", "write authority"],
                    persistence="Source stores remain separate; projections are reconstructed per turn",
                    source_ids=[
                        "src/rlmgraph/federated_memory.py",
                        "src/rlmgraph/repair_outcome_memory.py",
                    ],
                ),
                MemoryLayerModel(
                    name="conversation_work_bridge",
                    role="Exchange selected context and evidence-linked results across memory planes.",
                    owns=["read-only work requests", "work results", "selected fact IDs"],
                    excludes=["raw transcript transfer", "implicit mutation", "self approval"],
                    persistence="Durable request/result records",
                    source_ids=["src/rlmgraph/conversation_work_bridge.py"],
                ),
            ],
            background_flow=[
                "Persist the exact human turn.",
                "Interpret it into typed meaning using bounded retrieved conversation state.",
                "Consolidate supported conversational facts and supersede corrected values.",
                "Retrieve bounded project action records when a named or selected project matches.",
                "Respond from conversation state or submit an explicit read-only worker request.",
                "Persist evidence-linked worker output separately and return it through the bridge.",
            ],
            live_record_counts={
                "turns": len(turns),
                "interpretations": len(records),
                "active_retrieved_facts": len(facts),
                "memory_associations": count("memory_associations"),
                "memory_relationship_interpretations": count(
                    "memory_relationship_interpretations"
                ),
                "memory_clusters": count("memory_clusters"),
                "concept_branches": count("concept_branches"),
                "autonomous_decisions": count("autonomous_decisions"),
                "autonomous_inquiries": count("autonomous_inquiries"),
                "concept_branch_outcomes": count("concept_branch_outcomes"),
                "autonomous_tasks": count("autonomous_tasks"),
                "autonomous_task_plans": count("autonomous_task_plans"),
                "deductive_theories": count("deductive_theories"),
                "self_assessment_reports": count("self_assessment_reports"),
                "work_requests": count("conversation_work_requests"),
                "work_results": count("conversation_work_results"),
                "self_improvement_proposals": len(proposals),
            },
            current_fact_ids=[fact.id for fact in facts],
            authority_boundary=(
                "Memory and language interpretation may inform read-only investigation. Planning, "
                "implementation, approval, promotion, and self-modification require their ordinary "
                "separate user-governed transitions."
            ),
            evidence_basis=[
                "src/rlmgraph/conversation_memory.py",
                "src/rlmgraph/conversation_interpreter.py",
                "src/rlmgraph/conversation_work_bridge.py",
                "src/rlmgraph/observer_chat.py",
                "src/rlmgraph/store.py",
            ],
        )

    def commit(
        self, turn: ChatTurn, record: ConversationInterpretationRecord,
    ) -> list[ConversationFact]:
        facts, _ = self.commit_with_associations(turn, record)
        return facts

    def commit_with_associations(
        self, turn: ChatTurn, record: ConversationInterpretationRecord,
    ) -> tuple[list[ConversationFact], list]:
        writer = getattr(self.store, "save_conversation_fact", None)
        if not callable(writer):
            return [], []
        candidates = self._extract(turn, record)
        existing = self._active_facts(turn.session_id)
        profile_existing = [
            fact for fact in self._active_all_facts(turn.session_id) if fact.profile_memory
        ]
        by_key = {(fact.subject, fact.predicate, fact.meaning): fact for fact in existing}
        profile_by_key = {
            (fact.subject, fact.predicate, fact.meaning): fact for fact in profile_existing
        }
        saved = []
        associations = []
        for fact in candidates:
            index = profile_by_key if fact.profile_memory else by_key
            prior = index.get((fact.subject, fact.predicate, fact.meaning))
            if prior and prior.value.casefold() == fact.value.casefold():
                # Repetition adds provenance, never confidence or another copy of the fact.
                if turn.id != prior.source_turn_id and turn.id not in prior.supporting_turn_ids:
                    prior.supporting_turn_ids = (prior.supporting_turn_ids + [turn.id])[-8:]
                    prior.last_confirmed_at = fact.created_at
                    writer(prior)
                continue
            if prior:
                fact.supersedes_fact_id = prior.id
            self.neural_ranker.remember_text(
                fact.id, f"{fact.subject} {fact.predicate} {fact.value} {fact.useful_when} {' '.join(fact.aliases)}",
                importance=(1.0 if fact.kind == ConversationFactKind.IDENTITY else fact.confidence),
                protected=fact.kind in {
                    ConversationFactKind.IDENTITY, ConversationFactKind.OBJECTIVE,
                },
            )
            writer(fact)
            saved.append(fact)
            associations.extend(self.associations.discover(fact))
            index[(fact.subject, fact.predicate, fact.meaning)] = fact
        return saved, associations

    def _retrieve_associations(
        self, session_id: str, facts: list[ConversationFact],
        session_ids: list[str] | None = None,
    ) -> list:
        reader = getattr(self.store, "memory_associations", None)
        if not callable(reader):
            return []
        fact_ids = {fact.id for fact in facts}
        relevant = [
            item for item in self._global_items(reader, session_id, session_ids)
            if fact_ids.intersection(item.source_memory_ids)
        ]
        return sorted(relevant, key=lambda item: (-item.confidence, item.id))[:12]

    def _extract(
        self, turn: ChatTurn, record: ConversationInterpretationRecord,
    ) -> list[ConversationFact]:
        facts = []
        identity = self._IDENTITY.fullmatch(" ".join(turn.user_message.split()))
        if identity:
            subject = identity.group("subject").casefold()
            canonical = "current_project" if subject in {"project", "repository", "repo"} else subject
            facts.append(ConversationFact(
                session_id=turn.session_id,
                kind=ConversationFactKind.IDENTITY,
                subject=f"conversation.{canonical}",
                predicate="is",
                value=identity.group("value").strip(),
                source_turn_id=turn.id,
                source_interpretation_id=record.id,
                confidence=max(.9, record.interpretation.confidence),
            ))
        objective = record.interpretation.objective_update
        if objective:
            facts.append(ConversationFact(
                session_id=turn.session_id,
                kind=ConversationFactKind.OBJECTIVE,
                subject="conversation.active_objective",
                predicate="is",
                value=objective,
                source_turn_id=turn.id,
                source_interpretation_id=record.id,
                confidence=record.interpretation.confidence,
            ))
        for candidate in record.interpretation.memory_candidates:
            # Authentication material must never become conversational profile memory.
            if candidate.sensitivity == "SECRET":
                continue
            subject = re.sub(r"[^a-z0-9]+", ".", candidate.subject.casefold()).strip(".")
            if not subject:
                continue
            aliases = list(dict.fromkeys(
                alias.strip() for alias in candidate.aliases if alias.strip()
            ))[:12]
            facts.append(ConversationFact(
                session_id=turn.session_id,
                kind=ConversationFactKind(candidate.kind),
                subject=f"user.{subject}",
                predicate=candidate.predicate.strip().casefold(),
                value=candidate.value.strip(),
                source_turn_id=turn.id,
                source_interpretation_id=record.id,
                confidence=candidate.confidence,
                aliases=aliases,
                profile_memory=True,
                meaning=candidate.meaning,
                source_excerpt=(candidate.source_excerpt
                    if candidate.source_excerpt in turn.user_message else ""),
                useful_when=candidate.useful_when,
            ))
        return facts

    def _facts(self, session_id: str) -> list[ConversationFact]:
        reader = getattr(self.store, "conversation_facts", None)
        return self._global_items(reader, session_id, [session_id]) if callable(reader) else []

    def _all_facts(
        self, fallback_session_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> list[ConversationFact]:
        reader = getattr(self.store, "conversation_facts", None)
        return (
            self._global_items(reader, fallback_session_id, session_ids)
            if callable(reader) else []
        )

    def _active_facts(self, session_id: str) -> list[ConversationFact]:
        facts = self._facts(session_id)
        superseded = {fact.supersedes_fact_id for fact in facts if fact.supersedes_fact_id}
        return [fact for fact in facts if fact.id not in superseded]

    def _active_all_facts(
        self, fallback_session_id: str | None = None,
        session_ids: list[str] | None = None,
    ) -> list[ConversationFact]:
        facts = self._all_facts(fallback_session_id, session_ids)
        superseded = {fact.supersedes_fact_id for fact in facts if fact.supersedes_fact_id}
        return [fact for fact in facts if fact.id not in superseded]

    def _retrieve_profile_memories(
        self, session_id: str, message: str, session_ids: list[str] | None = None
    ) -> list[ConversationFact]:
        """Return bounded cross-session user memories with lexical provenance."""
        query = MemoryInterpreter._terms(message)
        recall_request = bool(re.search(
            r"\b(?:remember|recall|remind me|what was|what did i|have i told you)\b",
            message, re.IGNORECASE,
        ))
        scored = []
        facts = self._all_facts(session_id, session_ids)
        superseded = {fact.supersedes_fact_id for fact in facts if fact.supersedes_fact_id}
        profile = [
            fact for fact in facts if fact.profile_memory and fact.id not in superseded
        ]
        for ordinal, fact in enumerate(profile):
            text = " ".join((
                fact.subject, fact.predicate, fact.value, fact.useful_when, " ".join(fact.aliases)
            ))
            overlap = len(query & self.neural_ranker.terms(fact.id, text))
            if overlap == 0:
                continue
            exact_alias = any(
                alias.casefold() in message.casefold() for alias in fact.aliases
            )
            score = (
                4 * overlap + (4 if exact_alias else 0)
                + (1 if fact.session_id == session_id else 0)
                + (1 if recall_request else 0)
                + fact.confidence
                + (ordinal + 1) / max(len(profile), 1)
            )
            scored.append((score, ordinal, fact))
        return [
            item[2] for item in sorted(scored, key=lambda item: (-item[0], -item[1]))[:8]
        ]

    def _retrieve_facts(
        self, session_id: str, message: str, session_ids: list[str] | None = None
    ) -> tuple[list[ConversationFact], list, list[str]]:
        query = MemoryInterpreter._terms(message)
        facts = self._all_facts(session_id, session_ids)
        superseded = {fact.supersedes_fact_id for fact in facts if fact.supersedes_fact_id}
        facts = [fact for fact in facts if fact.id not in superseded]
        scored = []
        for ordinal, fact in enumerate(facts):
            text = f"{fact.subject} {fact.predicate} {fact.value} {fact.useful_when} {' '.join(fact.aliases)}"
            terms = self.neural_ranker.terms(fact.id, text)
            identity_priority = 4 if fact.kind == ConversationFactKind.IDENTITY else 0
            current_session = 1 if fact.session_id == session_id else 0
            score = (
                identity_priority + current_session + 3 * len(query & terms)
                + (ordinal + 1) / max(len(facts), 1)
            )
            scored.append((score, ordinal, fact))
        ranked = sorted(scored, key=lambda item: (-item[0], -item[1]))
        selected = [item[2] for item in ranked[:12]]
        neural_scores = self.neural_ranker.rank(
            message,
            [(fact, score) for score, _, fact in ranked],
            {fact.id for fact in selected},
            session_id,
        )
        rescued_ids = []
        if self.neural_ranker.ready():
            by_id = {fact.id: fact for fact in facts}
            selected_ids = {fact.id for fact in selected}
            rescued_ids = [
                score.memory_id for score in neural_scores
                if score.memory_id not in selected_ids
                and score.neural_score >= self.neural_ranker.rescue_threshold
            ][:2]
            selected.extend(by_id[memory_id] for memory_id in rescued_ids if memory_id in by_id)
        return selected, neural_scores, rescued_ids
