"""Small opt-in live check. Five model calls; all learned state is temporary."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from pydantic import BaseModel

from rlmgraph.adapters import CodexCliInvestigator
from rlmgraph.conversation_memory import ConversationMemoryPipeline
from rlmgraph.document_learning import (
    DocumentExtraction,
    DocumentFact,
    DocumentInput,
    DocumentLearning,
)
from rlmgraph.models import ChatSession
from rlmgraph.onboarding import ProjectSelection, ReadOnlyProjectOnboarder
from rlmgraph.project_world_memory import ProjectWorldMemory
from rlmgraph.store import SQLiteGraphStore
from rlmgraph.workflow_fact_search import WorkflowFactSearch


class Answer(BaseModel):
    width: float | None
    explanation: str
    source_ids: list[str]


QUESTION = "Under the fictional Varn strip specification, what is the total width of four slabs, each 23 units wide?"
DOCUMENT = (
    "Varn strip specification, revision Q. This is a fictional system, not a CSS standard. "
    "A Varn strip is a single horizontal row of slabs. "
    "There is a gap of 7 units between each adjacent pair of slabs, and no gap outside the row. "
    "The strip has an additional empty margin of 11 units at each of its two ends. "
    "Total strip width equals the sum of slab widths, the internal gaps, and both end margins. "
    "This specification gives no rule for slab height or material density."
)


def check_source_review(adapter, report):
    lesson = next((item["payload"] for item in report["paraphrase"]["memories"]
                   if "7 units" in item["payload"]["statement"]), None)
    if lesson is None:
        report["checks"].update(live_duplicate_detected=False, live_unsupported_rejected=False)
        return
    correct = DocumentFact(topic=lesson["topic"], statement=lesson["statement"],
        excerpt=lesson["source_excerpt"], applies_when=lesson["applies_when"],
        limitations=lesson["limitations"], collection=lesson["collection_name"])
    wrong = correct.model_copy(update={"statement": "Each adjacent pair of slabs in a Varn strip must have a gap of 999 units."})
    review = adapter.review_document_facts(DocumentInput(title="Fictional Varn specification",
        source_ref="test:varn-Q", text=DOCUMENT), DocumentExtraction(candidates=[correct, wrong]), [lesson])
    verdicts = {item.candidate: item.verdict for item in review.verdicts}
    report["live_review"] = review.model_dump()
    report["checks"].update(live_duplicate_detected=verdicts.get(0) == "DUPLICATE",
        live_unsupported_rejected=verdicts.get(1) in {"UNSUPPORTED", "CONFLICT"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    adapter = CodexCliInvestigator(model=args.model, sandbox="read-only")
    report = {"model": args.model, "question": QUESTION, "expected_width": 135,
              "scope": "One synthetic transfer problem; not a general learning benchmark."}
    with tempfile.TemporaryDirectory(prefix="tgram-teaching-check-") as directory:
        temp = Path(directory)
        project_root = temp / "project"
        project_root.mkdir()
        (project_root / "core.py").write_text("value = 1\n")
        store = SQLiteGraphStore(temp / "graph.db")
        store.initialize()
        project = ReadOnlyProjectOnboarder(store).scan(ProjectSelection.explicit(project_root)).project_id
        session = ChatSession(project_id=project, profile_id="test-owner")
        store.save_chat_session(session)
        answer_root = temp / "answer"
        answer_root.mkdir()

        def answer(memories):
            return adapter._run_structured(
                "Do not use tools or read files. Answer using only supplied memory. If the rules "
                "needed for a numeric answer are absent, return width=null and explain what is missing. "
                "Do not invent fictional specifications. Cite only supplied lesson IDs.\n"
                f"Question: {QUESTION}\nMemory: {json.dumps(memories)}",
                answer_root, Answer, timeout_seconds=60, sandbox_override="read-only",
            ).model_dump()

        report["baseline"] = answer([])
        receipt = DocumentLearning(store, adapter).ingest(project, DocumentInput(
            title="Fictional Varn specification", source_ref="test:varn-Q", text=DOCUMENT), "test-owner")
        report["teaching"] = receipt
        world = ProjectWorldMemory(store)
        recalled = world.search(QUESTION, project)
        projection = ConversationMemoryPipeline(store).reconstruct(
            session.id, QUESTION, [], [], project, profile_id="test-owner")
        workflow = WorkflowFactSearch(store).search(QUESTION, project_root, project)
        report["world_ids"] = [item["id"] for item in recalled["memories"]]
        report["conversation_ids"] = [item["id"] for item in projection.relevant_lessons]
        report["workflow_ids"] = [item.reference for item in workflow.hits if item.kind == "SOURCED_LESSON"]
        report["neural_state"] = recalled["neural_state"]
        report["with_memory"] = answer(projection.relevant_lessons)
        report["paraphrase"] = world.search("How much empty space separates neighboring pieces?", project)
        report["unrelated"] = world.search("photosynthesis chlorophyll", project)
        report["checks"] = {
            "baseline_abstains": report["baseline"]["width"] is None,
            "facts_saved": receipt["saved_count"] > 0,
            "world_retrieval": bool(report["world_ids"]),
            "conversation_retrieval": bool(report["conversation_ids"]),
            "workflow_retrieval": bool(report["workflow_ids"]),
            "transfer_answer": report["with_memory"]["width"] == 135,
            "valid_citations": bool(report["with_memory"]["source_ids"]) and set(report["with_memory"]["source_ids"]) <= set(report["conversation_ids"]),
            "paraphrase_retrieval": bool(report["paraphrase"]["memories"]),
            "unrelated_rejected": not report["unrelated"]["memories"],
        }
        report["temporary_state_bytes"] = sum(path.stat().st_size for path in temp.rglob("*") if path.is_file())
    report["temporary_state_removed"] = not temp.exists()
    check_source_review(adapter, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"checks": report["checks"], "temporary_state_removed": report["temporary_state_removed"],
                      "temporary_state_bytes": report["temporary_state_bytes"], "report": str(args.output)}))


if __name__ == "__main__":
    main()
