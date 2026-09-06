"""Sourced lessons and bounded application reports, separate from verified evidence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class LessonDraft(BaseModel):
    topic: str = Field(min_length=1, max_length=160)
    statement: str = Field(min_length=1, max_length=2000)
    source_kind: Literal["PUBLICATION", "GPT_EXPLANATION", "EXPERIENCE"]
    source_ref: str = Field(min_length=1, max_length=500)
    source_excerpt: str = Field(min_length=1, max_length=1000)
    applies_when: str = Field(min_length=1, max_length=600)
    limitations: str = Field(min_length=1, max_length=600)


class ApplicationReport(BaseModel):
    outcome: Literal["HELPED", "DID_NOT_HELP", "INCONCLUSIVE"]
    context: str = Field(min_length=1, max_length=600)
    observation: str = Field(min_length=1, max_length=1000)
    evidence_ref: str = Field(min_length=1, max_length=500)


class LessonLibrary:
    def __init__(self, store):
        path = getattr(store, "path", None)
        if not path:
            raise ValueError("The lesson library requires a local persistent store.")
        self.path = Path(f"{path}.lessons.sqlite3")
        self.store = store

    def _check_project(self, project_id):
        if not any(p.id == project_id for p in self.store.projects()):
            raise ValueError("Select a connected project for this lesson.")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10, factory=_ClosingConnection)
        connection.execute("CREATE TABLE IF NOT EXISTS lessons "
                           "(id TEXT PRIMARY KEY, project_id TEXT, payload TEXT)")
        return connection

    def list(self, project_id):
        self._check_project(project_id)
        if not self.path.exists():
            return []
        with self._connect() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM lessons WHERE project_id=? ORDER BY rowid DESC", (project_id,),
            )]

    def learn(self, project_id, draft: LessonDraft, actor: str):
        lesson = self.prepare(project_id, draft, actor)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT payload FROM lessons WHERE id=?", (lesson["id"],)).fetchone()
            if prior:
                return json.loads(prior[0])
            if db.execute("SELECT COUNT(*) FROM lessons").fetchone()[0] >= 500:
                raise ValueError("The 500-lesson storage limit is reached. No lesson was discarded.")
            db.execute("INSERT INTO lessons VALUES (?, ?, ?)",
                       (lesson["id"], project_id, json.dumps(lesson)))
        return lesson

    def prepare(self, project_id, draft: LessonDraft, actor: str):
        """Build a validated indexed record; callers own the persistence transaction."""
        self._check_project(project_id)
        if any(not value.strip() for value in draft.model_dump().values()):
            raise ValueError("Lesson fields must contain meaningful text.")
        key = hashlib.sha256(json.dumps(
            [project_id, draft.model_dump()], sort_keys=True,
        ).encode()).hexdigest()[:24]
        lesson = dict(id=f"LESSON-{key}", project_id=project_id, **draft.model_dump(),
                      recorded_by=actor, recorded_at=datetime.now(UTC).isoformat(),
                      status="UNTESTED", reports=[], outcome_counts={})
        from .project_world_memory import ProjectWorldMemory
        lesson["world_index"] = ProjectWorldMemory.index(" ".join(
            lesson[k] for k in ("topic", "statement", "applies_when", "limitations")
        ))
        return lesson

    def report(self, project_id, lesson_id, report: ApplicationReport, actor):
        self._check_project(project_id)
        if any(not value.strip() for value in report.model_dump().values()):
            raise ValueError("An application report needs context, observations, and an evidence reference.")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM lessons WHERE id=? AND project_id=?",
                             (lesson_id, project_id)).fetchone()
            if not row:
                raise ValueError("Lesson not found in this project.")
            lesson = json.loads(row[0])
            lesson["reports"] = (lesson["reports"] + [dict(
                **report.model_dump(), reported_by=actor, recorded_at=datetime.now(UTC).isoformat(),
            )])[-12:]
            outcomes = {item["outcome"] for item in lesson["reports"]}
            counts = lesson.setdefault("outcome_counts", {})
            counts[report.outcome] = counts.get(report.outcome, 0) + 1
            outcomes.update(counts)
            lesson["status"] = "CONTESTED" if "DID_NOT_HELP" in outcomes else "APPLICATION_REPORTED"
            db.execute("UPDATE lessons SET payload=? WHERE id=?", (json.dumps(lesson), lesson_id))
        from .project_world_memory import ProjectWorldMemory
        ProjectWorldMemory(self.store).report_outcome(lesson, report)
        return lesson

    def search(self, query, project_id, limit=3):
        from .project_world_memory import ProjectWorldMemory
        result = ProjectWorldMemory(self.store).search(query, project_id, limit=8)
        return [item["payload"] for item in result["memories"]
                if item["kind"] == "LESSON"][:max(0, min(limit, 6))]
