from __future__ import annotations

from .models import (
    ChatScope,
    ConversationInterpretationRecord,
    ConversationMemoryProjection,
    ConversationWorkRequest,
    ConversationWorkResult,
)


class ConversationWorkBridge:
    """The sole typed path from conversation context into read-only worker memory."""

    def __init__(self, store) -> None:
        self.store = store

    def submit(
        self, session_id: str, message: str,
        interpretation_record: ConversationInterpretationRecord,
        memory: ConversationMemoryProjection, scope: ChatScope,
        project_id: str | None,
    ) -> ConversationWorkRequest:
        interpretation = interpretation_record.interpretation
        request = ConversationWorkRequest(
            session_id=session_id,
            source_interpretation_id=interpretation_record.id,
            exact_user_prompt=message,
            objective=(
                interpretation.workflow_request
                or interpretation.objective_update
                or interpretation.user_meaning
                or message
            ),
            scope=scope,
            project_id=project_id,
            conversation_fact_ids=[fact.id for fact in memory.relevant_facts],
            deductive_theory_ids=[theory.id for theory in memory.relevant_theories],
            self_assessment_report_ids=[
                report.id for report in memory.recent_self_assessments
            ],
            assumptions=list(interpretation.assumptions),
            unresolved_questions=list(interpretation.ambiguities),
        )
        writer = getattr(self.store, "save_conversation_work_request", None)
        if callable(writer):
            writer(request)
        return request

    def complete(self, request: ConversationWorkRequest, response: dict) -> ConversationWorkResult:
        claim_id = response.get("claim_id")
        result = ConversationWorkResult(
            request_id=request.id,
            session_id=request.session_id,
            task_id=str(response["task_id"]),
            claim_ids=[str(claim_id)] if claim_id else [],
            answer_summary=str(response["answer"]),
            confidence=float(response.get("claim_confidence") or 0.0),
            unresolved_questions=list(response.get("unresolved_questions", [])),
            worker_trace_id=str(response["task_id"]),
        )
        writer = getattr(self.store, "save_conversation_work_result", None)
        if callable(writer):
            writer(result)
        request.status = "COMPLETED"
        request_writer = getattr(self.store, "save_conversation_work_request", None)
        if callable(request_writer):
            request_writer(request)
        return result
