from __future__ import annotations

import re
from typing import Protocol

from .intent import IntentDecision, IntentRouter, MessageIntent
from .models import (
    ChatTurn,
    ConversationConcept,
    ConversationConfusion,
    ConversationExcerpt,
    ConversationInterpretation,
    ConversationInterpretationRecord,
    ConversationMemoryProjection,
    ConversationReference,
    ConversationReflectionStep,
    ConversationRepairPatch,
    ConversationResponse,
    SystemSelfModel,
)

_SELF_REFERENCE = re.compile(
    r"\b(?:tgram|rlm\s*graph|the engine|this engine|the graph|this graph|this system|"
    r"this app|you|your|yours|yourself|your own system)\b",
    re.IGNORECASE,
)


class ConversationInterpreter(Protocol):
    def interpret_conversation(
        self, message: str, memory: ConversationMemoryProjection
    ) -> ConversationInterpretation: ...

    def repair_conversation(
        self,
        message: str,
        memory: ConversationMemoryProjection,
        interpretation: ConversationInterpretation,
        confusion: ConversationConfusion,
    ) -> ConversationRepairPatch: ...

    def respond_conversation(
        self,
        message: str,
        memory: ConversationMemoryProjection,
        interpretation: ConversationInterpretation,
    ) -> ConversationResponse: ...


class MemoryInterpreter:
    """Reverse interpreter: retrieve semantic state plus exact relevant user turns."""

    def __init__(
        self, max_records: int = 8, max_characters: int = 6_000,
        max_verbatim_characters: int = 20_000,
    ) -> None:
        self.max_records = max_records
        self.max_characters = max_characters
        self.max_verbatim_characters = max_verbatim_characters

    def reconstruct(
        self,
        session_id: str,
        message: str,
        turns: list[ChatTurn],
        records: list[ConversationInterpretationRecord],
    ) -> ConversationMemoryProjection:
        superseded = {
            record.supersedes_interpretation_id
            for record in records if record.supersedes_interpretation_id
        }
        records = [record for record in records if record.id not in superseded]
        query_terms = self._terms(message)
        by_turn = {turn.id: turn for turn in turns}
        scored = []
        for ordinal, record in enumerate(records):
            meaning_terms = self._terms(
                " ".join(filter(None, (
                    record.interpretation.user_meaning,
                    record.interpretation.objective_update,
                    record.interpretation.workflow_request,
                    " ".join(record.interpretation.entities),
                )))
            )
            reference_targets = {
                item.target_id for item in record.interpretation.references if item.target_id
            }
            recency = (ordinal + 1) / max(len(records), 1)
            score = 3 * len(query_terms & meaning_terms) + recency
            if reference_targets:
                score += .5
            scored.append((score, ordinal, record))
        selected = [
            item[2] for item in sorted(scored, key=lambda item: (-item[0], -item[1]))
            [: self.max_records]
        ]
        selected.sort(key=lambda item: item.created_at)
        summaries: list[str] = []
        active_objective = None
        pending_request = None
        ambiguities: list[str] = []
        turn_ids: list[str] = []
        claim_ids: list[str] = []
        excerpts: list[ConversationExcerpt] = []
        remembered_concepts: dict[str, ConversationConcept] = {}
        reflection_history: list[ConversationReflectionStep] = []
        characters = 0
        verbatim_characters = 0
        # Direct registry/task responses have no interpretation record, but remain dialogue.
        for turn in reversed([item for item in turns if item.session_id == session_id][-2:]):
            remaining = self.max_verbatim_characters - verbatim_characters
            if len(turn.user_message) > remaining:
                continue
            answer = turn.answer[:max(0, remaining - len(turn.user_message))]
            excerpts.append(ConversationExcerpt(
                turn_id=turn.id, user_message=turn.user_message, assistant_answer=answer,
                interpretation_id=turn.interpretation_id,
            ))
            turn_ids.append(turn.id)
            if turn.claim_id:
                claim_ids.append(turn.claim_id)
            verbatim_characters += len(turn.user_message) + len(answer)
        for record in reversed(selected):
            interpretation = record.interpretation
            summary = (
                f"{interpretation.speech_act}/{interpretation.primary_intent}: "
                f"{interpretation.user_meaning}"
            )
            if characters + len(summary) > self.max_characters:
                continue
            characters += len(summary)
            summaries.append(summary)
            if active_objective is None and interpretation.objective_update:
                active_objective = interpretation.objective_update
            if pending_request is None and interpretation.workflow_request:
                pending_request = interpretation.workflow_request
            if interpretation.needs_clarification:
                ambiguities.extend(interpretation.ambiguities)
            reflection_history.extend(record.reflection_steps)
            for concept in interpretation.concept_bindings:
                remembered_concepts.setdefault(concept.name.casefold(), concept)
            if record.turn_id:
                turn_ids.append(record.turn_id)
                turn = by_turn.get(record.turn_id)
                if turn and turn.id not in {excerpt.turn_id for excerpt in excerpts}:
                    if turn.claim_id:
                        claim_ids.append(turn.claim_id)
                    answer = turn.answer
                    remaining = self.max_verbatim_characters - verbatim_characters
                    required = len(turn.user_message)
                    if required <= remaining:
                        answer_budget = max(0, min(len(answer), remaining - required))
                        stored_answer = answer[:answer_budget]
                        if answer_budget < len(answer):
                            stored_answer += " …[answer truncated by retrieval budget]"
                        excerpts.append(ConversationExcerpt(
                            turn_id=turn.id,
                            user_message=turn.user_message,
                            assistant_answer=stored_answer,
                            interpretation_id=turn.interpretation_id,
                        ))
                        verbatim_characters += required + len(stored_answer)
        summary_text = "\n".join(reversed(summaries)) or "No relevant semantic state."
        return ConversationMemoryProjection(
            session_id=session_id,
            semantic_summary=summary_text,
            active_objective=active_objective,
            pending_workflow_request=pending_request,
            relevant_turn_ids=list(dict.fromkeys(reversed(turn_ids))),
            relevant_interpretation_ids=[item.id for item in selected],
            relevant_claim_ids=list(dict.fromkeys(reversed(claim_ids))),
            unresolved_ambiguities=list(dict.fromkeys(ambiguities))[:8],
            verbatim_turns=list(reversed(excerpts)),
            remembered_concepts=list(reversed(remembered_concepts.values())),
            reflection_history=reflection_history[-8:],
            token_estimate=(len(summary_text) + verbatim_characters + 3) // 4,
        )

    @staticmethod
    def _terms(value: str | None) -> set[str]:
        return set(re.findall(r"[a-z0-9_]+", (value or "").casefold())) - {
            "a", "an", "and", "are", "i", "is", "it", "of", "the", "to", "we",
        }


def describe_confusion(
    interpretation: ConversationInterpretation,
) -> ConversationConfusion:
    unresolved = [item for item in interpretation.references if item.target_id is None]
    reasons = list(interpretation.ambiguities)
    if unresolved and not reasons:
        reasons.append("One or more references have no grounded target.")
    if not reasons:
        reasons.append("The interpreter marked the meaning as requiring clarification.")
    return ConversationConfusion(
        trigger="; ".join(reasons),
        ambiguities=reasons,
        unresolved_references=unresolved,
        attempted_intent=interpretation.primary_intent,
        attempted_scope=interpretation.proposed_scope,
        confidence=interpretation.confidence,
    )


def merge_repair_patch(
    interpretation: ConversationInterpretation,
    patch: ConversationRepairPatch,
) -> tuple[ConversationInterpretation, bool, str]:
    """Merge only interpreter-supplied repairs and require measurable ambiguity reduction."""
    merged = interpretation.model_copy(deep=True)
    before_unresolved = sum(item.target_id is None for item in merged.references)
    before_ambiguities = len(merged.ambiguities)
    references = {item.phrase.casefold(): item for item in merged.references}
    for reference in patch.resolved_references:
        references[reference.phrase.casefold()] = reference
    merged.references = list(references.values())
    concepts = {item.name.casefold(): item for item in merged.concept_bindings}
    for concept in patch.revised_concepts:
        concepts[concept.name.casefold()] = concept
    merged.concept_bindings = list(concepts.values())
    if patch.revised_primary_intent:
        merged.primary_intent = patch.revised_primary_intent
    if patch.revised_user_meaning:
        merged.user_meaning = patch.revised_user_meaning
    if patch.revised_workflow_request is not None:
        merged.workflow_request = patch.revised_workflow_request
    if patch.revised_objective_update is not None:
        merged.objective_update = patch.revised_objective_update
    if patch.revised_scope:
        merged.proposed_scope = patch.revised_scope
    merged.ambiguities = list(dict.fromkeys(patch.remaining_ambiguities))
    merged.assumptions = list(dict.fromkeys(merged.assumptions + patch.added_assumptions))
    merged.confidence = patch.confidence
    after_unresolved = sum(item.target_id is None for item in merged.references)
    merged.needs_clarification = bool(
        patch.needs_clarification or merged.ambiguities or after_unresolved
    )
    improved = (
        after_unresolved < before_unresolved
        or len(merged.ambiguities) < before_ambiguities
        or (merged.confidence > interpretation.confidence and not merged.needs_clarification)
    )
    reason = (
        "Repair reduced unresolved meaning and was accepted."
        if improved else "Repair did not reduce unresolved meaning; the prior hypothesis was retained."
    )
    return (merged if improved else interpretation), improved, reason

def resolve_system_self_reference(
    message: str,
    interpretation: ConversationInterpretation,
    self_model: SystemSelfModel | None,
) -> ConversationInterpretation:
    """Ground first/second-person system references without erasing real ambiguity."""
    if self_model is None or not _SELF_REFERENCE.search(message):
        return interpretation
    resolved_phrases: list[str] = []
    for reference in interpretation.references:
        if reference.target_id in self_model.legacy_identity_ids:
            reference.target_id = self_model.identity_id
            reference.target_kind = "SYSTEM_IDENTITY"
            reference.confidence = max(reference.confidence, .99)
            resolved_phrases.append(reference.phrase.casefold())
        if reference.target_id is None and _SELF_REFERENCE.search(reference.phrase):
            reference.target_id = self_model.identity_id
            reference.target_kind = "SYSTEM_IDENTITY"
            reference.confidence = max(reference.confidence, .98)
            resolved_phrases.append(reference.phrase.casefold())
    if not any(item.target_id == self_model.identity_id for item in interpretation.references):
        phrase = _SELF_REFERENCE.search(message).group(0)
        interpretation.references.append(ConversationReference(
            phrase=phrase,
            target_id=self_model.identity_id,
            target_kind="SYSTEM_IDENTITY",
            confidence=.99,
        ))
        resolved_phrases.append(phrase.casefold())
    remaining = []
    for ambiguity in interpretation.ambiguities:
        lowered = ambiguity.casefold()
        self_only = any(phrase in lowered for phrase in resolved_phrases) or (
            any(term in lowered for term in (
                "yourself", "the system", "the engine", "tgram", "rlmgraph", "you/your"
            ))
            and any(term in lowered for term in ("refer", "identity", "ambiguous", "unclear"))
        )
        if not self_only:
            remaining.append(ambiguity)
    interpretation.ambiguities = remaining
    interpretation.proposed_scope = "SYSTEM"
    if not remaining and all(
        reference.target_id is not None for reference in interpretation.references
    ):
        interpretation.needs_clarification = False
    if not any(item.name == self_model.name for item in interpretation.concept_bindings):
        interpretation.concept_bindings.append(ConversationConcept(
            name=self_model.name,
            meaning=self_model.purpose,
            architecture_scope="SYSTEM",
            source_ids=[self_model.identity_id],
            confidence=.99,
        ))
    return interpretation


def deterministic_interpretation(
    decision: IntentDecision, memory: ConversationMemoryProjection
) -> ConversationInterpretation:
    """Fail-safe semantic record used when the disposable model call is unavailable."""
    speech_act = {
        MessageIntent.CONVERSE: "SOCIAL",
        MessageIntent.VERIFY: "CHALLENGE",
        MessageIntent.REPLAY: "REPLAY_REQUEST",
        MessageIntent.CHANGE: "DIRECTIVE",
        MessageIntent.HELP: "CAPABILITY_QUESTION",
        MessageIntent.CLARIFY: "UNCLEAR",
    }.get(decision.intent, "QUESTION")
    normalized = decision.normalized_message.casefold().rstrip(".!?")
    if decision.intent == MessageIntent.CONVERSE:
        if IntentRouter.is_context_declaration(decision.normalized_message):
            speech_act = "CONTEXT"
        elif (
            IntentRouter.is_context_recall(decision.normalized_message)
            or IntentRouter.is_conversation_recall(decision.normalized_message)
            or IntentRouter.is_conversational_opinion(decision.normalized_message)
            or IntentRouter.is_self_memory_question(decision.normalized_message)
            or IntentRouter.is_self_identity_question(decision.normalized_message)
        ):
            speech_act = "QUESTION"
        elif normalized in {"hello", "hi", "hey", "hello there", "hi there", "hey there"}:
            speech_act = "GREETING"
        elif normalized in {"thanks", "thank you"}:
            speech_act = "THANKS"
        elif normalized in {"bye", "goodbye"}:
            speech_act = "FAREWELL"
        else:
            speech_act = "ACKNOWLEDGEMENT"
    references = []
    if re.search(
        r"\b(?:it|its|that|this|those|them|they)\b",
        decision.normalized_message,
        re.IGNORECASE,
    ):
        target = memory.relevant_turn_ids[-1] if memory.relevant_turn_ids else None
        references.append(ConversationReference(
            phrase="contextual reference", target_id=target,
            target_kind="CHAT_TURN" if target else "UNRESOLVED",
            confidence=.65 if target else 0.0,
        ))
    message_terms = MemoryInterpreter._terms(decision.normalized_message)
    concept_bindings: list[ConversationConcept] = []
    for architecture in memory.architecture_contexts:
        for component in architecture.components:
            if message_terms & MemoryInterpreter._terms(component.name):
                concept_bindings.append(ConversationConcept(
                    name=component.name,
                    meaning=component.role,
                    architecture_scope=architecture.scope,
                    source_ids=component.paths,
                    confidence=.72,
                ))
        for concept in architecture.concepts:
            if message_terms & MemoryInterpreter._terms(concept):
                concept_bindings.append(ConversationConcept(
                    name=concept,
                    meaning=f"Architecture vocabulary concept in {architecture.project_name}.",
                    architecture_scope=architecture.scope,
                    confidence=.62,
                ))
        if len(concept_bindings) >= 4:
            break
    return ConversationInterpretation(
        speech_act=speech_act,
        primary_intent=decision.intent.value,
        user_meaning=decision.normalized_message,
        concept_bindings=concept_bindings[:4],
        workflow_request=(
            decision.normalized_message if decision.intent == MessageIntent.CHANGE else None
        ),
        references=references,
        ambiguities=(
            ["A contextual reference could not be resolved."]
            if any(item.target_id is None for item in references) else []
        ),
        confidence=decision.confidence,
        needs_clarification=decision.intent == MessageIntent.CLARIFY or any(
            item.target_id is None for item in references
        ),
    )
