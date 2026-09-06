"""Bounded document extraction, source review, and atomic indexed learning."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from pydantic import BaseModel, Field

from .learning import LessonDraft, LessonLibrary
from .relevance import terms

_LEARNING_LOCK = Lock()


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    source_ref: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=24000)


class DocumentFact(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=2000)
    excerpt: str = Field(min_length=1, max_length=1000)
    applies_when: str = Field(min_length=1, max_length=600)
    limitations: str = Field(min_length=1, max_length=600)
    collection: str = Field(min_length=1, max_length=160)


class DocumentExtraction(BaseModel):
    candidates: list[DocumentFact] = Field(max_length=12)


class FactVerdict(BaseModel):
    candidate: int = Field(ge=0, le=11)
    verdict: Literal["SUPPORTED", "UNSUPPORTED", "CONFLICT", "DUPLICATE"]
    reason: str = Field(min_length=1, max_length=800)
    related_lesson_ids: list[str] = Field(default_factory=list, max_length=6)


class DocumentReview(BaseModel):
    verdicts: list[FactVerdict] = Field(max_length=12)


class DocumentLearning:
    def __init__(self, store, interpreter):
        self.library = LessonLibrary(store)
        self.interpreter = interpreter

    def _connect(self):
        db = self.library._connect()
        db.execute("CREATE TABLE IF NOT EXISTS learned_documents "
                   "(id TEXT PRIMARY KEY, project_id TEXT, source TEXT, receipt TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS knowledge_collections "
                   "(id TEXT PRIMARY KEY, project_id TEXT, name TEXT)")
        return db

    def history(self, project_id):
        self.library._check_project(project_id)
        if not self.library.path.exists():
            return []
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT receipt FROM learned_documents WHERE project_id=? ORDER BY rowid DESC", (project_id,))]

    def ingest(self, project_id, document: DocumentInput, actor):
        self.library._check_project(project_id)
        if any(not value.strip() for value in document.model_dump().values()) or "\0" in document.text:
            raise ValueError("Supply readable document text, a title, and a source reference.")
        if not _LEARNING_LOCK.acquire(blocking=False):
            raise ValueError("Another document is being learned. Wait for it to finish before trying again.")
        try:
            return self._ingest(project_id, document, actor)
        finally:
            _LEARNING_LOCK.release()

    def _ingest(self, project_id, document, actor):
        digest = hashlib.sha256(document.text.encode()).hexdigest()
        document_id = "DOCUMENT-" + hashlib.sha256(
            json.dumps([project_id, digest, document.source_ref]).encode()).hexdigest()[:24]
        with self._connect() as db:
            prior = db.execute("SELECT receipt FROM learned_documents WHERE id=?", (document_id,)).fetchone()
            if prior:
                return {**json.loads(prior[0]), "reused": True}
            if db.execute("SELECT COUNT(*) FROM learned_documents").fetchone()[0] >= 100:
                raise ValueError("The 100-document limit is reached; nothing was discarded.")
            collections = [row[0] for row in db.execute(
                "SELECT name FROM knowledge_collections WHERE project_id=?", (project_id,))]
        extraction = self.interpreter.extract_document_facts(document, collections)
        if not isinstance(extraction, DocumentExtraction):
            extraction = DocumentExtraction.model_validate(extraction)
        existing = self.library.list(project_id)
        query = terms(" ".join(candidate.statement for candidate in extraction.candidates))
        related = sorted(existing, key=lambda item: -len(query & terms(item["statement"])))[:24]
        context = [{key: item[key] for key in ("id", "statement", "applies_when", "limitations", "source_ref")}
                   for item in related]
        review = self.interpreter.review_document_facts(document, extraction, context) if extraction.candidates else DocumentReview(verdicts=[])
        if not isinstance(review, DocumentReview):
            review = DocumentReview.model_validate(review)
        verdicts = {item.candidate: item for item in review.verdicts}
        if len(verdicts) != len(review.verdicts) or set(verdicts) != set(range(len(extraction.candidates))):
            raise ValueError("The source review did not cover each candidate exactly once. No facts were saved.")
        receipt = {"document_id": document_id, "title": document.title, "source_ref": document.source_ref,
                   "source_sha256": digest, "recorded_by": actor, "recorded_at": datetime.now(UTC).isoformat(),
                   "status": "REVIEWED", "reused": False, "decisions": [], "saved_count": 0,
                   "collection_names": [], "review_scope": "Source support and up to 24 related stored lessons; not independent truth verification."}
        pending = []
        for index, candidate in enumerate(extraction.candidates):
            verdict = verdicts[index]
            decision = {"candidate": index, "statement": candidate.statement, "excerpt": candidate.excerpt,
                        "outcome": verdict.verdict, "reason": verdict.reason,
                        "related_lesson_ids": verdict.related_lesson_ids}
            start = document.text.find(candidate.excerpt)
            if start < 0 or not candidate.excerpt.strip():
                decision.update(outcome="REJECTED", reason="The supporting excerpt is not present in the supplied document.")
            elif any(ref not in {item["id"] for item in related} for ref in verdict.related_lesson_ids):
                decision.update(outcome="REJECTED", reason="The review cited an unavailable memory reference.")
            elif verdict.verdict == "SUPPORTED":
                duplicate = next((item for item in [*existing, *pending]
                    if all(" ".join(item[key].casefold().split()) == " ".join(getattr(candidate, key).casefold().split())
                           for key in ("statement", "applies_when", "limitations"))), None)
                if duplicate:
                    decision.update(outcome="DUPLICATE", related_lesson_ids=[duplicate["id"]])
                else:
                    name = " ".join(candidate.collection.split()).casefold()
                    if not name:
                        raise ValueError("A candidate has an empty collection. No facts were saved.")
                    collection_id = "COLLECTION-" + hashlib.sha256(f"{project_id}\0{name}".encode()).hexdigest()[:20]
                    lesson = self.library.prepare(project_id, LessonDraft(
                        topic=candidate.topic, statement=candidate.statement, source_kind="PUBLICATION",
                        source_ref=document.source_ref, source_excerpt=candidate.excerpt,
                        applies_when=candidate.applies_when, limitations=candidate.limitations), actor)
                    lesson.update(status="SOURCE_SUPPORTED", document_id=document_id,
                                  collection_id=collection_id, collection_name=name,
                                  source_span={"start": start, "end": start + len(candidate.excerpt)},
                                  source_review=verdict.reason)
                    pending.append(lesson)
                    decision.update(outcome="SAVED", lesson_id=lesson["id"], collection=name)
            receipt["decisions"].append(decision)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM learned_documents").fetchone()[0] >= 100:
                raise ValueError("The document limit was reached. No facts were saved.")
            if db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] + len(pending) > 500:
                raise ValueError("Saving this document would exceed the lesson limit. No facts were saved.")
            for lesson in pending:
                db.execute("INSERT INTO lessons VALUES (?, ?, ?)", (lesson["id"], project_id, json.dumps(lesson)))
                db.execute("INSERT OR IGNORE INTO knowledge_collections VALUES (?, ?, ?)",
                           (lesson["collection_id"], project_id, lesson["collection_name"]))
            receipt["saved_count"] = len(pending)
            receipt["collection_names"] = sorted({item["collection_name"] for item in pending})
            db.execute("INSERT INTO learned_documents VALUES (?, ?, ?, ?)",
                       (document_id, project_id, document.model_dump_json(), json.dumps(receipt)))
        return receipt
