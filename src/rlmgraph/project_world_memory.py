"""Project knowledge accessible to both conversation and work through source references."""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .memory_tokenization import extract_memory_concepts, hashed_memory_vector, tokenize_memory
from .relevance import terms
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore
from .world_neural_memory import WorldMemoryRanker

_LOCK = RLock()


class ProjectWorldMemory(TokenizedMemoryStore):
    tokenization_mode = TokenizationMode.INLINE_RECORD

    def __init__(self, store):
        from .learning import LessonLibrary
        self.store = store
        self.library = LessonLibrary(store)
        self.state_path = Path(f"{store.path}.world-neural-memory.json")

    def _connect(self):
        db = self.library._connect()
        db.execute("CREATE TABLE IF NOT EXISTS world_fact_links "
                   "(project_id TEXT, session_id TEXT, fact_id TEXT, actor TEXT, "
                   "PRIMARY KEY(project_id, fact_id))")
        if "index_payload" not in {row[1] for row in db.execute("PRAGMA table_info(world_fact_links)")}:
            db.execute("ALTER TABLE world_fact_links ADD COLUMN index_payload TEXT")
        return db

    @staticmethod
    def index(text):
        tokens = tokenize_memory(text)
        return {"terms": sorted(terms(text)), "concepts": list(extract_memory_concepts(text)),
                "vector": list(hashed_memory_vector(tokens))}

    def link(self, project_id, session_id, fact_id, actor, *, owns_legacy=False):
        self.library._check_project(project_id)
        session = next((s for s in self.store.chat_sessions() if s.id == session_id), None)
        allowed = {actor, "LOCAL-LEGACY"} if owns_legacy else {actor}
        if session is None or session.profile_id not in allowed:
            raise PermissionError("This conversation does not belong to the signed-in profile.")
        fact = next((f for f in self._current_facts(session_id) if f.id == fact_id), None)
        if fact is None:
            raise ValueError("Only current conversation facts can be shared with project work.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT 1 FROM world_fact_links WHERE project_id=? AND fact_id=?",
                                (project_id, fact_id)).fetchone()
            if not exists and db.execute("SELECT COUNT(*) FROM world_fact_links").fetchone()[0] >= 1000:
                raise ValueError("The 1000 project-fact link limit is reached.")
            text = f"{fact.subject} {fact.predicate} {fact.value} {fact.useful_when} {' '.join(fact.aliases)}"
            db.execute("INSERT OR IGNORE INTO world_fact_links VALUES (?, ?, ?, ?, ?)",
                       (project_id, session_id, fact_id, actor, json.dumps(self.index(text))))
        return {"fact_id": fact_id, "project_id": project_id,
                "memory_domains": ["CONVERSATION", "WORLD"], "status": "LINKED"}

    def _current_facts(self, session_id):
        # A replacement in another session also retires an explicitly shared old fact.
        owner = next((s.profile_id for s in self.store.chat_sessions() if s.id == session_id), None)
        sessions = [s for s in self.store.chat_sessions() if s.profile_id == owner]
        all_facts = [f for s in sessions for f in self.store.conversation_facts(s.id)]
        superseded_turns = {t.id for s in sessions for t in self.store.chat_turns(s.id)
                            if t.superseded_by_turn_id}
        valid = [f for f in all_facts if f.source_turn_id not in superseded_turns]
        superseded = {f.supersedes_fact_id for f in valid if f.supersedes_fact_id}
        return [f for f in valid if f.session_id == session_id and f.id not in superseded]

    def search(self, query, project_id, limit=6):
        query_terms = terms(query)
        records = []
        for lesson in self.library.list(project_id):
            text = " ".join(lesson[k] for k in ("topic", "statement", "applies_when", "limitations"))
            index = lesson.get("world_index") or self.index(text)
            records.append({"id": lesson["id"], "kind": "LESSON", "text": text,
                            "index": index, "payload": lesson})
        if self.library.path.exists():
            with self._connect() as db:
                links = db.execute("SELECT session_id, fact_id, index_payload FROM world_fact_links WHERE project_id=?",
                                   (project_id,)).fetchall()
            sessions = {session: {f.id: f for f in self._current_facts(session)}
                        for session in {item[0] for item in links}}
            for session, fact_id, index_payload in links:
                fact = sessions[session].get(fact_id)
                if fact is None:
                    continue
                text = f"{fact.subject} {fact.predicate} {fact.value} {fact.useful_when} {' '.join(fact.aliases)}"
                records.append({"id": fact.id, "kind": "CONVERSATION_FACT", "text": text,
                                "index": json.loads(index_payload) if index_payload else self.index(text), "payload": {
                                    "id": fact.id, "statement": fact.value, "meaning": fact.meaning,
                                    "source_turn_id": fact.source_turn_id, "source_session_id": session,
                                    "applies_when": fact.useful_when, "status": "USER_REPORTED",
                                }})
        candidates = []
        by_id = {}
        for record in records:
            score = len(query_terms & set(record["index"]["terms"]))
            if score:
                by_id[record["id"]] = record
                candidates.append((record["id"], record["text"], score, record["kind"].lower(),
                                   .5, record["index"]["vector"], record["index"]["terms"]))
        # Reload within the lock so concurrent conversations cannot overwrite newer weights.
        with _LOCK:
            ranker = WorldMemoryRanker(self.state_path)
            ordered, state = ranker.rank(query, candidates)
        selected = []
        for memory_id in ordered[:max(0, min(limit, 8))]:
            record = by_id[memory_id]
            payload = dict(record["payload"])
            payload.pop("world_index", None)
            if "reports" in payload:
                payload["reports"] = [
                    {key: value[:400] if isinstance(value, str) else value for key, value in report.items()}
                    for report in payload["reports"][-2:]
                ]
            selected.append({"id": memory_id, "kind": record["kind"], "project_id": project_id,
                             "memory_domains": ["WORLD", "CONVERSATION"], "payload": payload})
        return {"memories": selected, "neural_state": state}

    def report_outcome(self, lesson, report):
        if report.outcome == "INCONCLUSIVE":
            return
        text = " ".join(lesson[k] for k in ("topic", "statement", "applies_when", "limitations"))
        candidate = (lesson["id"], text, 1.0, "lesson", .5)
        with _LOCK:
            ranker = WorldMemoryRanker(self.state_path)
            ranker.reinforce(report.context, [candidate],
                {lesson["id"]} if report.outcome == "HELPED" else set(),
                rejected_ids={lesson["id"]} if report.outcome == "DID_NOT_HELP" else set())
