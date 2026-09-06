from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

from .adapters import CodexCliInvestigator
from .architecture_context import ArchitectureProjector
from .autonomous_deliberation import AutonomousDeliberationManager
from .autonomous_tasks import AutonomousTaskManager
from .conversation_interpreter import (
    MemoryInterpreter,
    deterministic_interpretation,
    resolve_system_self_reference,
)
from .conversation_memory import ConversationMemoryPipeline
from .conversation_work_bridge import ConversationWorkBridge
from .deductive_reasoning import DeductiveSelfAssessmentEngine
from .intent import IntentDecision, IntentRouter, MessageIntent
from .models import (
    ChatScope,
    ChatSession,
    ChatTurn,
    ClaimValidity,
    ConversationInterpretation,
    ConversationInterpretationRecord,
    ConversationMemoryProjection,
)
from .project_access import project_access_followup, project_access_question, project_access_reply
from .recursive_investigation import RecursiveInvestigationSupervisor
from .self_iteration import SelfIterationManager
from .supervisor import GraphGroundedSupervisor

DEFAULT_CHAT_INVESTIGATION_TIMEOUT_SECONDS = 300


class ObserverChat:
    """RLMGraph conversation boundary: measured telemetry or graph-grounded inquiry."""

    _TELEMETRY_TERMS = re.compile(
        r"\b(?:tokens?|token usage|usage|costs?|spend|spending|spent|model calls?|compute)\b"
    )
    _SAVINGS_TERMS = re.compile(r"\b(?:saving|savings|saved)\b")
    _PROJECT_REGISTRY_PATTERNS = (
        r"\bits projects\b",
        r"\bconnected projects\b",
        r"\blist (?:the |my |your )?projects\b",
        r"\bwhat projects\b",
        r"\bprojects (?:does|do|are|can) rlmgraph\b",
    )
    _SYSTEM_PATTERNS = (
        r"\btgram\b",
        r"\brlm\s*graph\b",
        r"\b(?:this|the) engine\b",
        r"\bthis (?:app|system|tool|product)\b",
        (
            r"\b(?:your|its) (?:architecture|memory|system|engine|identity|capabilities?|"
            r"weakness|router|routing|development|design|code|action memory)\b"
        ),
        r"\bhow (?:do|does) (?:you|the system)\b",
    )
    _PROPOSE_SELF_IMPROVEMENT = re.compile(
        r"^(?:create|draft|make|propose) (?:an? )?(?:self-)?improvement(?: proposal)? "
        r"(?:from|based on) (?:that|the (?:last|latest) investigation)[.!]?$",
        re.IGNORECASE,
    )
    _ACCEPT_SELF_IMPROVEMENT = re.compile(
        r"^accept (?:self-)?improvement proposal "
        r"(?P<proposal_id>SELF-IMPROVEMENT-PROPOSAL-[a-z0-9]+)[.!]?$",
        re.IGNORECASE,
    )
    _RUN_AUTONOMY = re.compile(
        r"^(?:(?:run|start|perform) (?:an? )?autonomous "
        r"(?:deliberation|inquiry|cycle)(?: now)?|"
        r"(?:think about|explore) (?:something|one of your ideas|what you(?:'ve| have) learned)|"
        r"investigate something you(?:'re| are) uncertain about)[.!?]?$",
        re.IGNORECASE,
    )
    _AUTONOMY_STATUS = re.compile(
        r"^(?:what are you thinking about|what are you exploring|"
        r"(?:show|what is|what's) (?:your )?(?:autonomy|deliberation) status)[.!?]?$",
        re.IGNORECASE,
    )
    _AUTONOMY_REPORT = re.compile(
        r"^(?:what did you (?:find|learn)|tell me what you (?:found|learned)|"
        r"(?:show|give me) (?:the )?(?:latest )?autonomous report)[.!?]?$",
        re.IGNORECASE,
    )
    _ENABLE_AUTONOMOUS_WORK = re.compile(
        r"^enable autonomous task preparation(?: for this session)?[.!?]?$",
        re.IGNORECASE,
    )
    _DISABLE_AUTONOMOUS_WORK = re.compile(
        r"^disable autonomous task preparation(?: for this session)?[.!?]?$",
        re.IGNORECASE,
    )
    _START_AUTONOMOUS_WORK = re.compile(
        r"^(?:start working on something useful|prepare (?:an? )?autonomous task|"
        r"turn (?:that|the latest insight) into a task)[.!?]?$",
        re.IGNORECASE,
    )
    _AUTONOMOUS_TASK_STATUS = re.compile(
        r"^(?:what task are you working on|why did you choose that task|"
        r"what is blocking you|what's blocking you|show me the plan)[.!?]?$",
        re.IGNORECASE,
    )

    def __init__(
        self, store, executable: str = "codex", model: str | None = None,
        system_root: str | Path | None = None, interpreter=None, task_controller=None,
    ) -> None:
        self.store = store
        self.task_controller = task_controller
        self.model = model
        self.system_root = Path(system_root or Path(__file__).resolve().parents[2]).resolve()
        investigator = CodexCliInvestigator(
            executable,
            model,
            "read-only",
            DEFAULT_CHAT_INVESTIGATION_TIMEOUT_SECONDS,
        )
        self.interpreter = interpreter or investigator
        self.memory_interpreter = MemoryInterpreter()
        self.conversation_memory = ConversationMemoryPipeline(
            store, self.memory_interpreter, self.interpreter, self.system_root
        )
        self.work_bridge = ConversationWorkBridge(store)
        self.self_iteration = SelfIterationManager(store, self.system_root)
        self.autonomous_deliberation = AutonomousDeliberationManager(store)
        self.autonomous_tasks = AutonomousTaskManager(store, self.system_root)
        self.deductive_self_assessment = DeductiveSelfAssessmentEngine(store)
        self._autonomy_threads: dict[str, threading.Thread] = {}
        self._autonomy_lock = threading.Lock()
        self.architecture_projector = ArchitectureProjector(store, self.system_root)
        self.supervisor = GraphGroundedSupervisor(store, investigator)
        self.recursive_supervisor = RecursiveInvestigationSupervisor(
            store, investigator,
            max_depth=4,
            max_branches=8,
            max_model_calls=32,
            max_wall_time_seconds=300,
        )

    def reply(
        self, message: str, history: list[dict[str, str]], project_id: str | None,
        ticket_id: str | None, session_id: str | None = None, scope: str = "AUTO",
        investigation_mode: str = "AUTO", progress=None,
        profile_id: str = "LOCAL-LEGACY", include_legacy_memory: bool = False,
    ) -> dict[str, object]:
        original_message = message.replace("\x00", " ") if isinstance(message, str) else message
        deterministic_intent = IntentRouter.classify(original_message)
        if deterministic_intent.intent == MessageIntent.CLARIFY:
            raise ValueError(
                "Chat messages must contain between 1 and 4,000 characters. "
                f"{deterministic_intent.rationale}"
            )
        message = original_message
        deterministic_intent = IntentDecision(
            intent=deterministic_intent.intent,
            confidence=deterministic_intent.confidence,
            rationale=deterministic_intent.rationale,
            normalized_message=message,
        )
        del history  # Untrusted browser history is never used as memory.
        session = self._session(session_id, project_id, ticket_id, message, profile_id)
        turns = self._turns(session.id)
        from .latency_memory import latency_observations, latency_question
        if latency_question(message) and re.match(r"(?:why|what|where|how|show|explain|analy[sz]e|tell me)\b", message, re.IGNORECASE):
            observed = latency_observations(profile_id)
            if not observed["sample_count"]:
                answer = "I don’t have measured chat-stage timings yet. After ordinary conversations, I can report where backend time was spent. I can’t identify a bottleneck from missing data."
            else:
                top = observed["stages"][0]
                answer = (f"Across {observed['sample_count']} recent responses, average backend time was {observed['mean_ms'] / 1000:.1f} seconds. "
                          f"The largest measured stage was {top['stage'].replace('_', ' ').lower()}, accounting for {top['share_percent']}% of the measured time. "
                          "That is the first place to investigate, not a proven root cause. "
                          "Compare slow and fast requests and inspect the calls within that stage before changing code. "
                          "These timings do not distinguish provider waiting from local work, or measure browser rendering.")
            return self._persist(session, message, {
                "answer": answer, "route": "RLM_LATENCY_OBSERVATION", "scope": "SYSTEM",
                "operation_route": "READ_ONLY_LATENCY_REPORT", "latency_observations": observed,
                "project_id": project_id, "ticket_id": ticket_id,
            })
        access_question = project_access_question(message)
        access_followup = project_access_followup(message, turns) if access_question is None else None
        access_question = access_question or access_followup
        if access_question is not None:
            if callable(progress):
                progress("PROJECT_ACCESS", "Checking the connected project and its local folder.")
            access_intent = IntentDecision(
                MessageIntent.PROJECTS, 1.0, "Question about access to a named or selected project.",
                message,
            )
            result = project_access_reply(self.store, access_question, project_id or session.project_id)
            if access_followup:
                result["answer"] = (
                    f"We were checking access to {access_question[1]}. I rechecked the live project registry. "
                    + str(result["answer"])
                )
            return self._persist(session, message, self._with_intent(result, access_intent))
        turns = self._turns(session.id)
        if self.task_controller is not None and not self._has_system_subject(message):
            prior_task = next((turn for turn in reversed(turns) if turn.ticket_id), None)
            recent_project = next((turn.project_id for turn in reversed(turns) if turn.project_id), None)
            task_project = project_id or session.project_id or recent_project
            task_ticket = ticket_id or (
                prior_task.ticket_id if prior_task and prior_task.project_id == task_project else None
            )
            if prior_task and self.task_controller.is_status_request(message):
                task_project, task_ticket = prior_task.project_id, prior_task.ticket_id
            result = self.task_controller.handle(message, task_project, task_ticket, profile_id)
            if result is not None:
                return self._persist(session, message, self._with_intent(result, deterministic_intent))
        if callable(progress):
            progress("MEMORY_RECALL", "Searching bounded global conversational memory.")
        interpretation_record, intent, memory = self._interpret(
            session.id, message, turns, deterministic_intent,
            project_id or session.project_id, progress, profile_id, include_legacy_memory,
        )
        if callable(progress):
            progress("ROUTING", f"Resolved intent {intent.intent.value}; selecting response route.")
        prior = turns[-1] if turns else None
        if (
            IntentRouter.is_self_assessment_question(message)
            and memory.recent_self_assessments
            and not re.search(
                r"\b(?:refresh|reinvestigate|re-investigate|reassess|re-assess|verify|"
                r"new evidence|investigate again)\b",
                message,
                re.IGNORECASE,
            )
        ):
            if callable(progress):
                progress(
                    "DEDUCTIVE_RECALL",
                    "Selecting the strongest persisted, evidence-derived self-assessment.",
                )
            result = self._recalled_self_assessment_reply(memory)
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            if callable(progress):
                progress("MEMORY_UPDATE", "Persisting the recalled assessment as a conversation turn.")
            return self._persist(session, message, result, prior.id if prior else None)
        if self._ENABLE_AUTONOMOUS_WORK.fullmatch(message.strip()):
            policy = self.autonomous_tasks.enable(session.id, "chat-user")
            result = self._autonomous_work_policy_reply(policy, enabled=True)
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if self._DISABLE_AUTONOMOUS_WORK.fullmatch(message.strip()):
            policy = self.autonomous_tasks.disable(session.id)
            result = self._autonomous_work_policy_reply(policy, enabled=False)
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if self._START_AUTONOMOUS_WORK.fullmatch(message.strip()):
            try:
                task, plan = self.autonomous_tasks.prepare_latest(session.id)
                result = self._autonomous_task_reply(task, plan)
            except ValueError as exc:
                result = self._autonomous_task_error(str(exc))
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if self._AUTONOMOUS_TASK_STATUS.fullmatch(message.strip()):
            result = self._autonomous_task_status_reply(session.id, message)
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if (
            self._AUTONOMY_STATUS.fullmatch(message.strip())
            or self._AUTONOMY_REPORT.fullmatch(message.strip())
        ):
            result = self._autonomy_conversation_reply(
                session.id, report=bool(self._AUTONOMY_REPORT.fullmatch(message.strip()))
            )
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if self._RUN_AUTONOMY.fullmatch(message.strip()):
            decision, inquiry = self.autonomous_deliberation.deliberate(session.id)
            if inquiry is None:
                result = {
                    "answer": decision.reason,
                    "route": "RLM_AUTONOMOUS_DELIBERATION",
                    "operation_route": decision.status,
                    "investigation_mode": "DIRECT",
                    "scope": ChatScope.SYSTEM.value,
                    "routing_confidence": 1.0,
                    "routing_reason": "A user-triggered bounded autonomy cycle found no work.",
                    "claim_confidence": None,
                    "authority": "READ_ONLY_AUTONOMY_NO_MUTATION_AUTHORITY",
                    "project_id": None, "ticket_id": None, "evidence": [],
                    "autonomous_decision": decision.model_dump(mode="json"),
                }
                result = self._with_interpretation(
                    self._with_intent(result, intent), interpretation_record, memory
                )
                return self._persist(session, message, result, prior.id if prior else None)
            branch = next(item for item in self.store.concept_branches(session.id)
                          if item.id == inquiry.branch_id)
            inquiry.status = "QUEUED"
            inquiry.updated_at = datetime.now(UTC)
            self.store.save_autonomous_inquiry(inquiry)
            self._launch_autonomous_inquiry(inquiry.id)
            result = {
                "answer": (
                    f"I chose to explore “{branch.concept}” because it had the strongest bounded "
                    f"novelty, uncertainty, relevance, and information-gain score. I queued this "
                    f"read-only question: {inquiry.question} You can ask “what are you thinking "
                    "about?” for its current status."
                ),
                "route": "RLM_AUTONOMOUS_DELIBERATION",
                "operation_route": "READ_ONLY_INQUIRY_QUEUED",
                "investigation_mode": "BACKGROUND_DIRECT",
                "scope": ChatScope.SYSTEM.value,
                "routing_confidence": 1.0,
                "routing_reason": "The conversational autonomy trigger started one bounded cycle.",
                "claim_confidence": None,
                "authority": "READ_ONLY_AUTONOMY_NO_MUTATION_AUTHORITY",
                "project_id": None, "ticket_id": None, "evidence": [],
                "autonomous_decision": decision.model_dump(mode="json"),
                "autonomous_inquiry": inquiry.model_dump(mode="json"),
            }
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if self._PROPOSE_SELF_IMPROVEMENT.fullmatch(message.strip()):
            proposal = self.self_iteration.propose_latest(session.id)
            result = {
                "answer": (
                    f"Drafted {proposal.id}. Objective: {proposal.objective} "
                    "Review its acceptance criteria, then explicitly accept the proposal to create "
                    "an ordinary draft ticket."
                ),
                "route": "RLM_SELF_IMPROVEMENT_PROPOSAL",
                "operation_route": "DRAFT_PROPOSAL_ONLY",
                "investigation_mode": "DIRECT",
                "scope": ChatScope.SYSTEM.value,
                "routing_confidence": 1.0,
                "routing_reason": "The user explicitly requested a proposal from the latest investigation.",
                "claim_confidence": None,
                "authority": "DRAFT_PROPOSAL_NO_EXECUTION_AUTHORITY",
                "project_id": None,
                "ticket_id": None,
                "evidence": [],
                "self_improvement_proposal": proposal.model_dump(mode="json"),
            }
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        acceptance = self._ACCEPT_SELF_IMPROVEMENT.fullmatch(message.strip())
        if acceptance:
            proposal, ticket = self.self_iteration.accept(
                acceptance.group("proposal_id"), "chat-user", message
            )
            result = {
                "answer": (
                    f"Accepted {proposal.id} and created ordinary draft ticket {ticket.id}. "
                    "No planning, implementation, approval, or promotion has started."
                ),
                "route": "RLM_SELF_IMPROVEMENT_ACCEPTED",
                "operation_route": "DRAFT_TICKET_CREATED",
                "investigation_mode": "DIRECT",
                "scope": ChatScope.SYSTEM.value,
                "routing_confidence": 1.0,
                "routing_reason": "The user explicitly accepted one identified proposal.",
                "claim_confidence": None,
                "authority": "DRAFT_TICKET_ONLY_NO_EXECUTION_AUTHORITY",
                "project_id": ticket.project_id,
                "ticket_id": ticket.id,
                "evidence": [],
                "self_improvement_proposal": proposal.model_dump(mode="json"),
            }
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if (
            interpretation_record.interpretation.needs_clarification
            and not interpretation_record.fallback_used
        ):
            ambiguity = next(
                iter(interpretation_record.interpretation.ambiguities),
                "The intended meaning could change which workflow is appropriate.",
            )
            result = {
                "answer": f"Before I continue, I need to resolve this: {ambiguity}",
                "route": "RLM_CONVERSATION_CLARIFICATION",
                "operation_route": "CLARIFICATION_REQUIRED",
                "investigation_mode": "DIRECT",
                "scope": ChatScope.SYSTEM.value,
                "routing_confidence": interpretation_record.interpretation.confidence,
                "routing_reason": "The semantic interpretation is materially ambiguous.",
                "claim_confidence": None,
                "authority": "READ_ONLY_CLARIFICATION_NO_WORKFLOW_AUTHORITY",
                "project_id": project_id,
                "ticket_id": ticket_id,
                "evidence": [],
            }
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if intent.intent == MessageIntent.CONVERSE:
            result = self._conversation_reply(
                interpretation_record.interpretation,
                project_id,
                ticket_id,
                message,
                memory,
                progress=progress,
            )
            if callable(progress):
                progress("MEMORY_SAVE", "Saving the checked response and supported memories.")
            self.conversation_memory.learn_from_usage(
                session.id,
                message,
                memory.relevant_facts,
                list(result.get("conversation_response_fact_ids", [])),
            )
            result = self._with_interpretation(
                self._with_intent(result, intent), interpretation_record, memory
            )
            return self._persist(session, message, result, prior.id if prior else None)
        if intent.intent == MessageIntent.CHANGE:
            task_project = project_id or session.project_id
            if self._has_system_subject(message):
                matches = [p for p in self.store.projects()
                           if Path(p.root).resolve() == self.system_root]
                task_project = matches[0].id if len(matches) == 1 else None
            if self.task_controller is None:
                result = {
                    "answer": "I understood this as a request to make changes, but the task executor is unavailable. No implementation has started.",
                    "route": "RLM_RECOVERY", "scope": "SYSTEM",
                }
            elif self._has_system_subject(message) and task_project is None:
                result = {
                    "answer": "To change TGRAM itself, connect its source folder in Projects and choose an execution mode that permits changes. No implementation has started.",
                    "route": "RLM_CONVERSATION_TASK", "scope": "SYSTEM",
                }
            else:
                result = self.task_controller.start_reviewed_request(message, task_project, profile_id)
            result = self._with_interpretation(self._with_intent(result, intent), interpretation_record, memory)
            return self._persist(session, message, result, prior.id if prior else None)
        if intent.intent == MessageIntent.VERIFY and prior is not None and prior.claim_id:
            result = self._verify_follow_up(message, prior)
            result = self._with_interpretation(self._with_intent(result, intent), interpretation_record, memory)
            return self._persist(session, message, result, prior.id)
        if intent.intent == MessageIntent.REPLAY and prior is not None:
            result = self._exact_follow_up(prior, project_id, ticket_id)
            result = self._with_interpretation(self._with_intent(result, intent), interpretation_record, memory)
            return self._persist(session, message, result, prior.id)
        if intent.intent == MessageIntent.TELEMETRY or self._is_telemetry_request(message):
            result = self._usage_reply(project_id, ticket_id)
            result = self._with_interpretation(self._with_intent(result, intent), interpretation_record, memory)
            return self._persist(session, message, result)
        if intent.intent == MessageIntent.PROJECTS or any(
            re.search(pattern, message.lower()) for pattern in self._PROJECT_REGISTRY_PATTERNS
        ):
            result = self._project_registry_reply(project_id, ticket_id)
            result = self._with_interpretation(self._with_intent(result, intent), interpretation_record, memory)
            return self._persist(session, message, result)
        semantic_reference = any(
            item.target_id for item in interpretation_record.interpretation.references
        )
        contextual = prior is not None and (
            self._is_contextual_follow_up(message) or semantic_reference
        )
        context_turns = turns[-4:] if contextual else []
        effective_project_id = prior.project_id if contextual else project_id
        effective_ticket_id = prior.ticket_id if contextual else ticket_id
        explicit_system_subject = self._has_system_subject(message)
        scope_decision, routing_confidence, routing_reason = self._scope(
            message, scope, effective_project_id
        )
        semantic_scope = interpretation_record.interpretation.proposed_scope.upper()
        if scope.strip().upper() == "AUTO" and semantic_scope in {
            ChatScope.SYSTEM.value, ChatScope.PROJECT.value,
        }:
            if semantic_scope == ChatScope.PROJECT.value and effective_project_id is None:
                raise ValueError(
                    "The message refers to a selected project, but no connected project is selected."
                )
            interpreted_scope = ChatScope(semantic_scope)
            if interpreted_scope != scope_decision:
                scope_decision = interpreted_scope
                routing_confidence = interpretation_record.interpretation.confidence
                routing_reason = "Scope was resolved by the ephemeral semantic interpreter."
        if contextual and scope.strip().upper() == "AUTO":
            scope_decision = prior.scope
            routing_confidence = .96
            routing_reason = "The question refers to persisted prior context, so its scope was inherited."
        if explicit_system_subject:
            scope_decision = ChatScope.SYSTEM
            routing_confidence = 1.0
            routing_reason = (
                "The subject is TGRAM's reserved system identity, outside loaded projects."
            )
        evidence_question, context_metadata = self._reconstruct_context(
            message, context_turns
        )
        effective_mode = investigation_mode
        if contextual and investigation_mode.strip().upper() == "AUTO":
            effective_mode = "RECURSIVE"
        bridge_project_id = None
        root = self.system_root
        if scope_decision == ChatScope.PROJECT:
            project = next(
                (item for item in self.store.projects() if item.id == effective_project_id), None
            )
            if project is None:
                raise ValueError("Select a connected project before asking a repository question.")
            root = Path(project.root)
            bridge_project_id = effective_project_id
        work_request = self.work_bridge.submit(
            session.id, message, interpretation_record, memory,
            scope_decision, bridge_project_id,
        )
        investigation_question = self._workflow_prompt(
            message, interpretation_record, memory, evidence_question, work_request
        )
        if callable(progress):
            progress(
                "EVIDENCE_INVESTIGATION",
                "The graph worker is gathering and evaluating current evidence.",
            )
        response = self._investigate(
            investigation_question, root, bridge_project_id, effective_ticket_id,
            scope_decision, routing_confidence, routing_reason, effective_mode, message,
            progress,
        )
        work_result = self.work_bridge.complete(work_request, response)
        if IntentRouter.is_self_assessment_question(message):
            assessment = self.deductive_self_assessment.assess(session.id, work_result)
            response["answer"] = (
                f"{assessment.conclusion}\n\nEvidence investigation: "
                f"{work_result.answer_summary}"
            )
            response["claim_confidence"] = assessment.confidence
            response["confidence"] = assessment.confidence
            response["self_assessment_report"] = assessment.model_dump(mode="json")
            response["deductive_theory_ids"] = [
                candidate.theory_id for candidate in assessment.candidates
            ]
        response["work_bridge_request_id"] = work_request.id
        response["work_bridge_result_id"] = work_result.id
        response["work_bridge_authorization"] = work_request.authorization
        response.update(context_metadata)
        response = self._with_intent(response, intent)
        response = self._with_interpretation(response, interpretation_record, memory)
        return self._persist(
            session, message, response, prior.id if contextual else None,
        )

    @staticmethod
    def _workflow_prompt(
        message, interpretation_record, memory, evidence_question, work_request
    ):
        selected_fact_ids = set(work_request.conversation_fact_ids)
        selected_theory_ids = set(work_request.deductive_theory_ids)
        selected_report_ids = set(work_request.self_assessment_report_ids)
        payload = {
            "current_user_prompt_verbatim": message,
            "work_request": work_request.model_dump(mode="json"),
            "interpretation_hypothesis": interpretation_record.interpretation.model_dump(
                mode="json"
            ),
            "selected_conversation_facts": [
                fact.model_dump(mode="json") for fact in memory.relevant_facts
                if fact.id in selected_fact_ids
            ],
            "recalled_deductive_theories": [
                theory.model_dump(mode="json") for theory in memory.relevant_theories
                if theory.id in selected_theory_ids
            ],
            "recalled_self_assessments": [
                report.model_dump(mode="json") for report in memory.recent_self_assessments
                if report.id in selected_report_ids
            ],
        }
        context = ""
        if evidence_question != message:
            context = (
                "\n\nClaim-grounded reference context:\n"
                f"{evidence_question}"
            )
        return (
            "Use the complete current user prompt as the authoritative request. The semantic "
            "interpretation and retrieved conversation are context hypotheses; do not replace, "
            "shorten, or paraphrase away requirements in the prompt.\n\n"
            "Recalled deductions are learned, falsifiable hypotheses rather than static identity "
            "or established facts. Use their premises and source IDs to guide investigation, test "
            "their falsifiers against current evidence, and contradict or revise them when the "
            "evidence warrants it. Never infer or supply a secret, handshake, password, or expected "
            "user phrase from system guidance.\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + context
        )

    @staticmethod
    def _recalled_self_assessment_reply(memory) -> dict[str, object]:
        report = memory.recent_self_assessments[-1]
        selected = next(
            (item for item in report.candidates if item.id == report.selected_candidate_id),
            report.candidates[0],
        )
        theory = next(
            (item for item in memory.relevant_theories if item.id == selected.theory_id),
            None,
        )
        basis = ""
        if theory is not None and theory.premises:
            basis = " My reasoning is based on: " + " ".join(
                premise.statement for premise in theory.premises[:3]
            )
        answer = (
            f"My strongest current learned theory is {selected.category.lower().replace('_', ' ')}: "
            f"{selected.description} I rank it at {selected.severity:.2f} severity with "
            f"{selected.evidence_strength:.2f} evidence strength.{basis} This is a revisable "
            "deduction from persisted memory, not a fixed statement about my identity. Ask me to "
            "reassess or verify it if you want a fresh evidence investigation."
        )
        return {
            "answer": answer,
            "route": "RLM_DEDUCTIVE_MEMORY_RECALL",
            "operation_route": "RECALLED_SELF_ASSESSMENT",
            "investigation_mode": "MEMORY",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": (
                "A persisted, evidence-derived self-assessment answered immediately; fresh "
                "investigation remains explicitly available."
            ),
            "claim_confidence": report.confidence,
            "confidence": report.confidence,
            "authority": "READ_ONLY_DEDUCTIVE_MEMORY_NO_WRITE_AUTHORITY",
            "project_id": None,
            "ticket_id": None,
            "evidence": [],
            "self_assessment_report": report.model_dump(mode="json"),
            "deductive_theory_ids": [selected.theory_id],
            "source_claim_ids": report.source_claim_ids,
        }

    def _launch_autonomous_inquiry(self, inquiry_id: str) -> None:
        with self._autonomy_lock:
            active = self._autonomy_threads.get(inquiry_id)
            if active is not None and active.is_alive():
                return
            thread = threading.Thread(
                target=self._execute_autonomous_inquiry,
                args=(inquiry_id,),
                name=f"rlmgraph-autonomy-{inquiry_id[-8:]}",
                daemon=True,
            )
            self._autonomy_threads[inquiry_id] = thread
            thread.start()

    def _execute_autonomous_inquiry(self, inquiry_id: str) -> None:
        inquiry = None
        try:
            inquiry = next(
                item for session in self.store.chat_sessions()
                for item in self.store.autonomous_inquiries(session.id)
                if item.id == inquiry_id
            )
            branch = next(
                item for item in self.store.concept_branches(inquiry.session_id)
                if item.id == inquiry.branch_id
            )
            fact_ids = set(branch.supporting_fact_ids)
            memory = ConversationMemoryProjection(
                session_id=inquiry.session_id,
                relevant_facts=[
                    fact for fact in self.store.conversation_facts(inquiry.session_id)
                    if fact.id in fact_ids
                ],
                system_self=self.architecture_projector.self_model(),
                architecture_contexts=self.architecture_projector.contexts(None),
            )
            record = ConversationInterpretationRecord(
                session_id=inquiry.session_id,
                message=inquiry.question,
                interpretation=ConversationInterpretation(
                    speech_act="AUTONOMOUS_INQUIRY",
                    primary_intent="INVESTIGATE",
                    user_meaning=inquiry.question,
                    workflow_request=inquiry.question,
                    proposed_scope=ChatScope.SYSTEM.value,
                    confidence=1.0,
                ),
                interpreter="AutonomousDeliberationManager",
            )
            self.store.save_conversation_interpretation(record)
            request = self.work_bridge.submit(
                inquiry.session_id, inquiry.question, record, memory,
                ChatScope.SYSTEM, None,
            )
            inquiry.work_request_id = request.id
            inquiry.status = "RUNNING"
            inquiry.updated_at = datetime.now(UTC)
            self.store.save_autonomous_inquiry(inquiry)
            prompt = self._workflow_prompt(
                inquiry.question, record, memory, inquiry.question, request
            )
            response = self._investigate(
                prompt, self.system_root, None, None, ChatScope.SYSTEM, 1.0,
                "Autonomy policy selected an open concept branch.",
                "DIRECT", inquiry.question,
            )
            result = self.work_bridge.complete(request, response)
            self.autonomous_deliberation.complete(inquiry, result)
            if self.autonomous_tasks.policy(inquiry.session_id).enabled:
                try:
                    self.autonomous_tasks.prepare_latest(inquiry.session_id)
                except ValueError:
                    pass  # The durable outcome remains available for later preparation.
        except Exception as exc:  # noqa: BLE001 - background worker boundary
            if inquiry is not None:
                self.autonomous_deliberation.fail(inquiry, type(exc).__name__)
        finally:
            with self._autonomy_lock:
                self._autonomy_threads.pop(inquiry_id, None)

    def _autonomy_conversation_reply(self, session_id: str, *, report: bool) -> dict[str, object]:
        inquiries = list(self.store.autonomous_inquiries(session_id))
        if not inquiries:
            answer = (
                "I do not have an autonomous inquiry yet. Ask me to explore one of my ideas or "
                "run an autonomous cycle."
            )
            payload = None
            operation = "NO_AUTONOMOUS_INQUIRY"
        else:
            inquiry = inquiries[-1]
            branch = next(
                (item for item in self.store.concept_branches(session_id)
                 if item.id == inquiry.branch_id),
                None,
            )
            outcomes = [
                item for item in self.store.concept_branch_outcomes(session_id)
                if item.inquiry_id == inquiry.id
            ]
            outcome = outcomes[-1] if outcomes else None
            decisions = [
                item for item in self.store.autonomous_decisions(session_id)
                if item.id == inquiry.decision_id
            ]
            decision = decisions[-1] if decisions else None
            score = next(
                (item for item in decision.candidates if item.branch_id == inquiry.branch_id),
                None,
            ) if decision else None
            concept = branch.concept if branch else inquiry.branch_id
            if outcome:
                answer = (
                    f"I explored “{concept}.” The evidence-linked outcome is {outcome.status} "
                    f"at confidence {outcome.confidence:.2f}. {outcome.summary}"
                )
                operation = "AUTONOMOUS_REPORT_COMPLETED"
            else:
                score_text = f" Its selection score was {score.total:.2f}." if score else ""
                answer = (
                    f"I’m exploring “{concept}.” Status: {inquiry.status}.{score_text} "
                    f"The question I formed is: {inquiry.question}"
                )
                operation = "AUTONOMOUS_STATUS"
            if report and not outcome:
                answer += " There is no completed evidence report yet."
            payload = inquiry.model_dump(mode="json")
        return {
            "answer": answer,
            "route": "RLM_AUTONOMY_CONVERSATION",
            "operation_route": operation,
            "investigation_mode": "MEMORY_STATUS",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "The reply is rendered from durable autonomy records.",
            "claim_confidence": None,
            "authority": "READ_ONLY_AUTONOMY_REPORT_NO_WORKFLOW_AUTHORITY",
            "project_id": None, "ticket_id": None, "evidence": [],
            "autonomous_inquiry": payload,
        }

    @staticmethod
    def _autonomous_work_policy_reply(policy, *, enabled: bool) -> dict[str, object]:
        answer = (
            "Autonomous task preparation is enabled for this session. Evidence-linked outcomes "
            "may now create ordinary draft tickets and proposed plans. Source writes, plan "
            "approval, sandbox execution, promotion, restart, and self-approval remain disabled."
            if enabled else
            "Autonomous task preparation is disabled. Existing draft tickets and plans remain "
            "durable, but no new autonomous task preparation will start."
        )
        return {
            "answer": answer,
            "route": "RLM_AUTONOMOUS_TASK_POLICY",
            "operation_route": "ENABLED" if enabled else "DISABLED",
            "investigation_mode": "POLICY_UPDATE",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "The user explicitly changed the session autonomy policy.",
            "claim_confidence": None,
            "authority": "SESSION_TASK_PREPARATION_POLICY_NO_MUTATION_AUTHORITY",
            "project_id": None, "ticket_id": None, "evidence": [],
            "autonomous_work_policy": policy.model_dump(mode="json"),
        }

    @staticmethod
    def _autonomous_task_reply(task, plan) -> dict[str, object]:
        if plan is None:
            answer = f"Prepared {task.id}, but it is blocked: {task.blocker}"
            operation = "AUTONOMOUS_TASK_BLOCKED"
        else:
            answer = (
                f"Prepared {task.id} and ordinary draft ticket {task.ticket_id}. I also drafted "
                f"proposed plan {plan.id}. It is waiting for user plan approval; no source write "
                "or sandbox implementation has started."
            )
            operation = "WAITING_FOR_USER_PLAN_APPROVAL"
        return {
            "answer": answer,
            "route": "RLM_AUTONOMOUS_TASK_PREPARATION",
            "operation_route": operation,
            "investigation_mode": "TASK_PREPARATION",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "An evidence-linked outcome entered the opted-in task workflow.",
            "claim_confidence": None,
            "authority": "DRAFT_TICKET_AND_PROPOSED_PLAN_ONLY",
            "project_id": None, "ticket_id": task.ticket_id, "evidence": [],
            "autonomous_task": task.model_dump(mode="json"),
            "autonomous_task_plan": plan.model_dump(mode="json") if plan else None,
        }

    @staticmethod
    def _autonomous_task_error(reason: str) -> dict[str, object]:
        return {
            "answer": reason,
            "route": "RLM_AUTONOMOUS_TASK_PREPARATION",
            "operation_route": "NO_TASK_PREPARED",
            "investigation_mode": "TASK_PREPARATION",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "The governed task-preparation preconditions were not met.",
            "claim_confidence": None,
            "authority": "NO_TASK_AUTHORITY",
            "project_id": None, "ticket_id": None, "evidence": [],
        }

    def _autonomous_task_status_reply(self, session_id: str, message: str) -> dict[str, object]:
        tasks = list(self.store.autonomous_tasks(session_id))
        if not tasks:
            return self._autonomous_task_error(
                "I do not have an autonomous task in this session yet."
            )
        task = tasks[-1]
        plans = [
            item for item in self.store.autonomous_task_plans(session_id)
            if item.autonomous_task_id == task.id
        ]
        plan = plans[-1] if plans else None
        normalized = message.casefold()
        if "plan" in normalized and plan:
            answer = (
                f"Proposed plan {plan.id}: " + " ".join(
                    f"{index}. {step}" for index, step in enumerate(plan.steps, 1)
                ) + " It remains unapproved."
            )
        elif "why" in normalized:
            answer = (
                f"I chose {task.id} because autonomous outcome {task.outcome_id} contained "
                "evidence-linked claims and had not already produced a task."
            )
        elif "blocking" in normalized:
            answer = (
                f"{task.id} is blocked by: {task.blocker}"
                if task.blocker else
                f"{task.id} is waiting at the user plan-approval boundary."
            )
        else:
            answer = f"I’m preparing {task.id}: {task.title}. Status: {task.status}."
        result = self._autonomous_task_reply(task, plan)
        result["answer"] = answer
        result["route"] = "RLM_AUTONOMOUS_TASK_CONVERSATION"
        result["operation_route"] = "AUTONOMOUS_TASK_STATUS"
        return result

    def _interpret(
        self, session_id, message, turns, deterministic_intent, selected_project_id=None,
        progress=None, profile_id="LOCAL-LEGACY", include_legacy_memory=False,
    ):
        reader = getattr(self.store, "conversation_interpretations", None)
        records = list(reader(session_id)) if callable(reader) else []
        memory = self.conversation_memory.reconstruct(
            session_id, message, turns, records, selected_project_id,
            profile_id=profile_id, include_legacy_memory=include_legacy_memory,
        )
        memory.architecture_contexts = self.architecture_projector.contexts(
            selected_project_id
        )
        memory.system_self = self.architecture_projector.self_model()
        memory.system_workspace = self.architecture_projector.system_workspace()
        self.conversation_memory.enrich_operational_memory(
            memory, message, selected_project_id
        )
        if callable(progress):
            neural_state = memory.neural_memory_state
            progress(
                "NEURAL_MEMORY_RANKING",
                f"The shadow MLP scored {len(memory.neural_memory_scores)} memory candidate(s); "
                f"agreement {neural_state.top_k_agreement:.0%}, "
                f"outcome examples {neural_state.outcome_examples}. "
                + (
                    f"Assisted recall added {len(neural_state.rescued_memory_ids)} memory candidate(s)."
                    if neural_state.assisted_recall_enabled else
                    "Deterministic retrieval remains authoritative while the model matures."
                ),
            )
            progress(
                "INTERPRETING",
                "Resolving the complete prompt against the retrieved typed memory.",
            )
        fallback = False
        reflection_steps = []
        routing_review = None
        retry_query = None
        interpreter_name = type(self.interpreter).__name__
        try:
            memory_core_query = (
                IntentRouter.is_self_identity_question(message)
                or IntentRouter.is_self_memory_question(message)
                or IntentRouter.is_self_assessment_question(message)
            )
            if memory_core_query:
                interpretation = deterministic_interpretation(deterministic_intent, memory)
                interpreter_name = "RLMGraphMemoryCore"
            else:
                method = self.interpreter.interpret_conversation
                interpretation = method(message, memory)
            initial_uncertainty = interpretation.needs_clarification
            if deterministic_intent.intent == MessageIntent.CONVERSE:
                # A model may describe the speech act with open-ended vocabulary, but it may
                # not promote a deterministic no-action social/context turn into workflow work.
                interpretation.primary_intent = MessageIntent.CONVERSE.value
                interpretation.needs_clarification = False
                if IntentRouter.is_context_declaration(message):
                    interpretation.speech_act = "CONTEXT"
                elif (
                    IntentRouter.is_conversational_opinion(message)
                    or IntentRouter.is_conversation_recall(message)
                    or IntentRouter.is_self_memory_question(message)
                ):
                    interpretation.speech_act = "QUESTION"
            if IntentRouter.is_self_assessment_question(message):
                interpretation.primary_intent = MessageIntent.INVESTIGATE.value
                interpretation.speech_act = "EVIDENCE_SEEKING_SELF_ASSESSMENT"
                interpretation.proposed_scope = ChatScope.SYSTEM.value
                interpretation.workflow_request = message
                interpretation.needs_clarification = False
            if str(interpretation.primary_intent).upper() == MessageIntent.CONVERSE.value:
                # Conversational uncertainty can be expressed in the answer; it cannot change a
                # worker route because no worker route is available to a CONVERSE turn.
                interpretation.needs_clarification = False
            # Review all routes that can reuse or evaluate a prior repository answer,
            # even when the first interpretation claims certainty.
            interpretation = resolve_system_self_reference(
                message, interpretation, memory.system_self
            )
            reviewer = getattr(self.interpreter, "review_conversation_route", None)
            if (not memory_core_query and callable(reviewer) and (
                initial_uncertainty or interpretation.primary_intent in {
                    "INVESTIGATE", "CHANGE", "CLARIFY", "VERIFY", "REPLAY"
                }
            )):
                retry_query = interpretation.memory_query or message
                if callable(progress):
                    progress("CONVERSATION_MEMORY_RETRY", "Looking for original dialogue before deciding whether project work is needed.")
                self.conversation_memory.retry_dialogue(
                    memory, f"{message} {retry_query}", profile_id, include_legacy_memory
                )
                dialogue = type(memory)(
                    session_id=session_id, relevant_facts=memory.relevant_facts,
                    relevant_profile_memories=memory.relevant_profile_memories,
                    verbatim_turns=memory.verbatim_turns,
                    relevant_turn_ids=memory.relevant_turn_ids,
                )
                try:
                    if callable(progress):
                        progress("ROUTE_REVIEW", "Reviewing whether the request needs conversation or project work.")
                    routing_review = reviewer(message, dialogue, interpretation)
                    available = {item.turn_id for item in dialogue.verbatim_turns}
                    if not set(routing_review.source_turn_ids).issubset(available):
                        raise ValueError("Routing review cited unavailable conversation.")
                    if routing_review.intent in {"INVESTIGATE", "CHANGE", "VERIFY", "REPLAY"} and (
                        not routing_review.requested_work_quote
                        or routing_review.requested_work_quote not in message
                    ):
                        raise ValueError("Routing review did not identify a current work request.")
                    interpretation.primary_intent = routing_review.intent
                    interpretation.user_meaning = routing_review.user_meaning
                    interpretation.speech_act = "QUESTION"
                    interpretation.needs_clarification = routing_review.intent == "CLARIFY"
                    interpretation.ambiguities = [routing_review.clarification or "What would you like me to do with that?"] if interpretation.needs_clarification else []
                    if routing_review.intent in {"CONVERSE", "CLARIFY"}:
                        interpretation.workflow_request = None
                        interpretation.proposed_scope = "AUTO"
                        # Don't pass rejected repository framing into the conversational responder.
                        memory = dialogue
                except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.SubprocessError):
                    interpretation.primary_intent = "CLARIFY"
                    interpretation.speech_act = "QUESTION"
                    interpretation.needs_clarification = True
                    interpretation.workflow_request = None
                    interpretation.ambiguities = ["I couldn’t resolve that from our conversation. Could you remind me what you mean?"]
            speech_act = interpretation.speech_act.upper()
            intent_kind = (
                MessageIntent.CONVERSE
                if speech_act in {
                    "GREETING", "SALUTATION", "THANKS", "GRATITUDE", "APPRECIATION",
                    "ACKNOWLEDGEMENT", "ACKNOWLEDGMENT", "FAREWELL", "SOCIAL",
                }
                else MessageIntent(str(interpretation.primary_intent).upper())
            )
            intent = IntentDecision(
                intent=intent_kind,
                confidence=interpretation.confidence,
                rationale=(
                    f"Ephemeral semantic interpreter: {interpretation.speech_act}; "
                    f"{interpretation.user_meaning}"
                ),
                normalized_message=message,
            )
        except (
            AttributeError, ValueError, RuntimeError, OSError, TimeoutError,
            subprocess.SubprocessError,
        ):
            fallback = True
            interpretation = deterministic_interpretation(deterministic_intent, memory)
            interpretation = resolve_system_self_reference(
                message, interpretation, memory.system_self
            )
            intent = deterministic_intent
            if not memory_core_query and callable(getattr(self.interpreter, "review_conversation_route", None)):
                interpretation.primary_intent = "CLARIFY"
                interpretation.needs_clarification = True
                interpretation.workflow_request = None
                interpretation.ambiguities = ["I couldn’t resolve the conversational context. Could you clarify what you want me to do?"]
                intent = IntentDecision(MessageIntent.CLARIFY, 1.0, "Conversation interpretation was unavailable; no work was dispatched.", message)
        supersedes = None
        if interpretation.speech_act.upper() == "CORRECTION" and records:
            supersedes = records[-1].id
        record = ConversationInterpretationRecord(
            routing_review=routing_review, memory_retry_query=retry_query,
            session_id=session_id,
            message=message,
            interpretation=interpretation,
            interpreter=(
                interpreter_name if not fallback else "IntentRouterFallback"
            ),
            fallback_used=fallback,
            reflection_steps=reflection_steps,
            supersedes_interpretation_id=supersedes,
        )
        writer = getattr(self.store, "save_conversation_interpretation", None)
        if callable(writer):
            writer(record)
        return record, intent, memory

    def _conversation_reply(
        self, interpretation, project_id, ticket_id, message="", memory=None, progress=None
    ):
        speech_act = interpretation.speech_act.upper()
        normalized_message = " ".join(message.casefold().split()).rstrip(".!?")
        if normalized_message in {"thanks", "thank you"}:
            speech_act = "THANKS"
        elif normalized_message in {"hello", "hi", "hey", "hello there", "hi there"}:
            speech_act = "GREETING"
        elif normalized_message in {"bye", "goodbye"}:
            speech_act = "FAREWELL"
        elif normalized_message in {"ok", "okay", "got it"}:
            speech_act = "ACKNOWLEDGEMENT"
        recalled_fact = next((
            fact for fact in (memory.relevant_facts if memory else [])
            if fact.subject == "conversation.current_project" and fact.predicate == "is"
        ), None)
        recalled_project = recalled_fact.value if recalled_fact else None
        identity_question = normalized_message in {"what are you", "who are you"}
        deterministic_answer = (
            memory.memory_system.identity_statement
            if identity_question and memory and memory.memory_system
            else f"We’re discussing {recalled_project}."
            if IntentRouter.is_context_recall(message) and recalled_project
            else {
            "GREETING": "Hello! What would you like to talk about?",
            "SALUTATION": "Hello! What would you like to talk about?",
            "THANKS": "You’re welcome.",
            "GRATITUDE": "You’re welcome.",
            "APPRECIATION": "You’re welcome.",
            "ACKNOWLEDGEMENT": "Got it.",
            "ACKNOWLEDGMENT": "Got it.",
            "ASSERTION": "Got it.",
            "ASSERT": "Got it.",
            "CONTEXT": "Got it.",
            "CONTEXT_SETTING": "Got it.",
            "DECLARATION": "Got it.",
            "IDENTIFICATION": "Got it.",
            "IDENTITY_CONTEXT": "Got it.",
            "INFORM": "Got it.",
            "INFORMATION": "Got it.",
            "STATEMENT": "Got it.",
            "FAREWELL": "Goodbye.",
            "SOCIAL": "I’m here. What’s on your mind?",
            }.get(speech_act)
        )
        generated = False
        response_confidence = None
        used_fact_ids = []
        used_action_memory_ids = []
        used_evaluation_memory_ids = []
        used_operational_memory_ids = []
        answer = deterministic_answer
        review_failed = False
        answer_reviewed = False
        if IntentRouter.is_context_recall(message) and recalled_fact:
            used_fact_ids = [recalled_fact.id]
        if answer is None:
            responder = getattr(self.interpreter, "respond_conversation", None)
            if callable(responder):
                try:
                    if callable(progress):
                        progress("ANSWER_GENERATION", "Forming a response from the retrieved context.")
                    response = responder(message, memory, interpretation)
                    reviewer = getattr(self.interpreter, "review_conversation_answer", None)
                    if callable(reviewer):
                        if callable(progress):
                            progress("ANSWER_REVIEW", "Checking the draft against conversation evidence.")
                        review_failed = True
                        response = reviewer(message, memory, interpretation, response)
                        review_failed = False
                        answer_reviewed = True
                    answer = response.answer
                    response_confidence = response.confidence
                    available_fact_ids = {
                        fact.id for fact in (memory.relevant_facts if memory else [])
                    }
                    available_action_ids = {
                        item.memory_id
                        for item in (memory.relevant_action_memories if memory else [])
                    }
                    available_evaluation_ids = {
                        item.id
                        for item in (memory.relevant_evaluation_memories if memory else [])
                    }
                    available_operational_ids = {
                        item.memory_id
                        for item in (memory.relevant_operational_memories if memory else [])
                    }
                    used_fact_ids = [
                        item for item in response.used_fact_ids if item in available_fact_ids
                    ]
                    used_action_memory_ids = [
                        item for item in response.used_action_memory_ids
                        if item in available_action_ids
                    ]
                    used_evaluation_memory_ids = [
                        item for item in response.used_evaluation_memory_ids
                        if item in available_evaluation_ids
                    ]
                    used_operational_memory_ids = [
                        item for item in response.used_operational_memory_ids
                        if item in available_operational_ids
                    ]
                    generated = True
                except (
                    ValueError, RuntimeError, OSError, TimeoutError,
                    subprocess.SubprocessError,
                ):
                    answer = None
                    review_failed = True
        if answer is None:
            normalized = " ".join(message.casefold().split()).rstrip(".!?")
            if IntentRouter.is_self_memory_question(message) and memory.memory_system:
                layers = ", ".join(item.name for item in memory.memory_system.layers)
                answer = (
                    f"{memory.memory_system.identity_statement} Its active memory layers are: "
                    f"{layers}."
                )
            elif normalized in {"what are you", "who are you"} and memory.memory_system:
                answer = memory.memory_system.identity_statement
            elif speech_act in {
                "ASSERT", "ASSERTION", "CONTEXT", "CONTEXT_SETTING", "DECLARATION",
                "IDENTIFICATION", "IDENTITY_CONTEXT", "INFORM", "INFORMATION", "STATEMENT",
            }:
                answer = "Got it."
            else:
                answer = "I understood this as conversation, but I couldn’t form a useful response."
        if review_failed:
            answer = "I couldn’t finish checking that answer. Please retry."
        return {
            "answer": answer,
            "route": "RLM_RECOVERY" if review_failed else "RLM_CONVERSATION",
            "conversation_answer_reviewed": answer_reviewed,
            "operation_route": "CONVERSATIONAL_RESPONSE",
            "investigation_mode": "DIRECT",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "The interpreted message is conversational and requests no workflow.",
            "claim_confidence": None,
            "authority": "READ_ONLY_CONVERSATION_NO_WORKFLOW_AUTHORITY",
            "project_id": project_id,
            "ticket_id": ticket_id,
            "evidence": [],
            "conversation_response_generated": generated,
            "conversation_response_confidence": response_confidence,
            "conversation_response_fact_ids": used_fact_ids,
            "conversation_response_action_memory_ids": used_action_memory_ids,
            "conversation_response_evaluation_memory_ids": used_evaluation_memory_ids,
            "conversation_response_operational_memory_ids": used_operational_memory_ids,
        }

    @staticmethod
    def _with_interpretation(result, record, memory):
        return {
            **result,
            "interpretation_id": record.id,
            "interpretation": record.interpretation.model_dump(mode="json"),
            "interpretation_fallback": record.fallback_used,
            "reflection_steps": [
                item.model_dump(mode="json") for item in record.reflection_steps
            ],
            "memory_projection": memory.model_dump(mode="json"),
            "conversation_routing_review": record.routing_review.model_dump(mode="json") if record.routing_review else None,
            "_interpretation_record": record,
        }

    def retry_answer(self, session_id, turn_id, *, profile_id="LOCAL-LEGACY", progress=None, include_legacy_memory=False):
        session = next((s for s in self.store.chat_sessions() if s.id == session_id), None)
        allowed_profiles = {profile_id, "LOCAL-LEGACY"} if include_legacy_memory else {profile_id}
        if session is None or session.profile_id not in allowed_profiles:
            raise ValueError("Conversation is unavailable for this profile.")
        turns = self._turns(session_id)
        if not turns or turns[-1].id != turn_id:
            raise ValueError("Only the latest answer can be retried. Refresh the conversation.")
        previous = turns[-1]
        if previous.route == "RLM_CONVERSATION_TASK" or previous.intent == "CHANGE":
            raise ValueError("Use task controls to continue project work.")
        result = self.safe_reply(
            previous.user_message, [], previous.project_id, previous.ticket_id, session_id,
            profile_id=profile_id, progress=progress, include_legacy_memory=include_legacy_memory,
        )
        if result.get("route") not in {"RLM_RECOVERY", "RLM_CONVERSATION_CLARIFICATION"}:
            previous.superseded_by_turn_id = result["turn_id"]
            self.store.save_chat_turn(previous)
            result["replaces_turn_id"] = previous.id
            # Re-extract after supersession so deduplication against the old turn
            # cannot discard facts independently supported by the new interpretation.
            replacement = next(turn for turn in self.store.chat_turns(session_id) if turn.id == result["turn_id"])
            record = next((item for item in self.store.conversation_interpretations(session_id)
                           if item.id == replacement.interpretation_id), None)
            if record is not None:
                self.conversation_memory.commit_with_associations(replacement, record)
        elif result.get("turn_id"):
            failed = next(turn for turn in self.store.chat_turns(session_id) if turn.id == result["turn_id"])
            failed.superseded_by_turn_id = previous.id
            self.store.save_chat_turn(failed)
        return result

    def safe_reply(self, *args, **kwargs) -> dict[str, object]:
        """Never let malformed input or a worker outage tear down the chat transport."""
        raw_message = args[0] if args else kwargs.get("message")
        intent = IntentRouter.classify(raw_message)
        if intent.intent == MessageIntent.CLARIFY:
            return self._recovery_response(intent.rationale, intent)
        import sqlite3

        from .latency_memory import ChatTiming, record_latency
        from .model_call_ledger import model_call_ledger
        timing = ChatTiming()
        positional = list(args)
        original_progress = positional[7] if len(positional) > 7 else kwargs.get("progress")
        def measured_progress(stage, detail):
            timing.mark(stage)
            if callable(original_progress):
                original_progress(stage, detail)
        if len(positional) > 7:
            positional[7] = measured_progress
        else:
            kwargs["progress"] = measured_progress
        try:
            result = self.reply(*positional, **kwargs)
        except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
            result = self._recovery_response(str(exc), intent)
        measurement = timing.finish()
        result["latency_measurement"] = measurement
        ledger = model_call_ledger()
        if ledger is not None and result.get("route") != "RLM_LATENCY_OBSERVATION":
            try:
                record_latency(ledger, positional[8] if len(positional) > 8 else kwargs.get("profile_id", "LOCAL-LEGACY"),
                               result.get("session_id"), str(result.get("route")), measurement)
            except sqlite3.Error:
                result["latency_measurement_saved"] = False
        return result

    @staticmethod
    def _with_intent(result: dict[str, object], intent: IntentDecision) -> dict[str, object]:
        return {
            **result,
            "intent": intent.intent.value,
            "intent_confidence": intent.confidence,
            "intent_rationale": intent.rationale,
        }

    @classmethod
    def _recovery_response(
        cls, reason: str, intent: IntentDecision
    ) -> dict[str, object]:
        provider_failure = "not supported when using Codex" in reason or "model_not_found" in reason
        answer = (
            "The configured model is unavailable for this account. "
            "Choose a supported model in Account → model settings, then retry the same request. "
            "Rephrasing your request will not fix this configuration problem."
            if provider_failure else
            f"I could not safely complete that request: {reason} "
            "You can rephrase it, select a project, or split it into a smaller request."
        )
        return cls._with_intent({
            "answer": answer,
            "route": "RLM_RECOVERY",
            "operation_route": "MODEL_CONFIGURATION_ERROR" if provider_failure else "RECOVERABLE_INPUT",
            "investigation_mode": "DIRECT",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 1.0,
            "routing_reason": "A bounded recovery response replaced an uncaught chat failure.",
            "claim_confidence": None,
            "authority": "READ_ONLY_RECOVERY_NO_MODEL_CALL_NO_WRITE_AUTHORITY",
            "project_id": None,
            "ticket_id": None,
            "evidence": [],
            "recoverable": True,
            "error": reason,
        }, intent)

    @classmethod
    def _is_telemetry_request(cls, message: str) -> bool:
        lowered = message.casefold()
        if not cls._TELEMETRY_TERMS.search(lowered):
            return False
        if cls._SAVINGS_TERMS.search(lowered):
            return True
        return bool(
            re.search(
                r"\b(?:what|how many|how much|show|report|measure|measured|total|current|my|our)\b",
                lowered,
            )
        )

    def _scope(self, message: str, requested: str, project_id: str | None):
        requested = requested.strip().upper()
        if self._has_system_subject(message):
            return (
                ChatScope.SYSTEM, 1.0,
                "The subject is TGRAM's reserved system identity, outside loaded projects.",
            )
        if requested in {ChatScope.SYSTEM.value, ChatScope.PROJECT.value}:
            decision = ChatScope(requested)
            if decision == ChatScope.PROJECT and project_id is None:
                raise ValueError("Select a connected project for selected-project scope.")
            return decision, 1.0, "Scope was explicitly selected by the user."
        if requested != "AUTO":
            raise ValueError("Chat scope must be AUTO, SYSTEM, or PROJECT.")
        if IntentRouter.is_self_assessment_question(message):
            return (
                ChatScope.SYSTEM, 1.0,
                "Current RLMGraph self-assessment requires system evidence.",
            )
        if project_id is not None:
            return ChatScope.PROJECT, .82, "No system subject was named; using the selected project."
        return ChatScope.SYSTEM, .7, "No project is selected; using TGRAM system scope."

    @classmethod
    def _has_system_subject(cls, message: str) -> bool:
        lowered = message.casefold()
        project_subject = re.search(
            r"\b(?:this|the|selected|current|loaded) (?:project|repository|repo)\b",
            lowered,
        )
        tgram_as_object = re.search(
            r"\b(?:integrate|connect|interact|work|communicate)s?\s+(?:with|to)\s+"
            r"(?:tgram|rlm\s*graph)\b",
            lowered,
        )
        if project_subject and tgram_as_object:
            return False
        return any(re.search(pattern, lowered) for pattern in cls._SYSTEM_PATTERNS)

    def _investigate(
        self, message, root, project_id, ticket_id, scope,
        routing_confidence, routing_reason, investigation_mode, routing_message=None,
        progress=None,
    ):
        recursive = self._should_recurse(
            routing_message if routing_message is not None else message,
            scope,
            investigation_mode,
        )
        if recursive:
            options = {"force_investigation": True}
            if callable(progress):
                options["progress"] = progress
            result = self.recursive_supervisor.run(message, root, **options)
        else:
            result = self.supervisor.run(message, root)
        claim = result.claim
        reuse_type = getattr(result.task, "reuse_type", None)
        operation_route = (
            "EXACT_REPLAY" if reuse_type == "exact" else
            "SEMANTIC_REUSE" if reuse_type == "semantic" else "NEW_INVESTIGATION"
        )
        response = {
            "answer": claim.conclusion,
            "route": (
                "RLM_SYSTEM_INVESTIGATION" if scope == ChatScope.SYSTEM
                else "RLM_GRAPH_SUPERVISOR"
            ),
            "authority": "READ_ONLY_GRAPH_INVESTIGATION_NO_WRITE_AUTHORITY",
            "project_id": project_id,
            "ticket_id": ticket_id,
            "claim_id": claim.id,
            "task_id": result.task.id,
            "cache_hit": result.cache_hit,
            "confidence": claim.confidence,
            "claim_confidence": claim.confidence,
            "routing_confidence": routing_confidence,
            "routing_reason": routing_reason,
            "investigation_mode": "RECURSIVE" if recursive else "DIRECT",
            "scope": scope.value,
            "operation_route": operation_route,
            "evidence": [item.model_dump(mode="json") for item in claim.evidence],
            "unresolved_questions": claim.unresolved_questions,
        }
        sub_tasks = list(getattr(result, "sub_tasks", []))
        if sub_tasks:
            response["recursive"] = True
            response["planning_questions"] = list(result.planning_questions)
            response["task_tree"] = [
                {
                    "id": item.id, "parent_task_id": item.parent_task_id,
                    "question": item.question, "depth": item.depth,
                    "status": item.status.value, "route": item.route.value if item.route else None,
                    "reused_claim_id": item.reused_claim_id,
                    "output_claim_id": item.output_claim_id,
                    "stopping_reason": (
                        item.stopping_reason.value if item.stopping_reason else None
                    ),
                }
                for item in [result.task, *sub_tasks]
            ]
            response["contradictions"] = [
                item.model_dump(mode="json") for item in result.conflicts
            ]
            response["investigation_calls"] = result.investigation_calls
            response["budget_exhausted"] = result.budget_exhausted
        work_project = next(
            (
                item for item in self._items("projects")
                if Path(item.root).resolve() == Path(root).resolve()
            ),
            None,
        )
        response["work_project_id"] = work_project.id if work_project else project_id
        return response

    @staticmethod
    def _should_recurse(message: str, scope: ChatScope, requested: str) -> bool:
        requested = requested.strip().upper()
        if requested == "RECURSIVE":
            return True
        if requested == "DIRECT":
            return False
        if requested != "AUTO":
            raise ValueError("Investigation mode must be AUTO, DIRECT, or RECURSIVE.")
        if scope == ChatScope.SYSTEM:
            return True
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "why", "how", "root cause", "compare", "trace", "architecture",
                "relationship", "depend", "contradict", "investigate",
            )
        )

    def _session(
        self, session_id, project_id, ticket_id, message, profile_id="LOCAL-LEGACY"
    ) -> ChatSession:
        sessions = self._items("chat_sessions")
        existing = next((item for item in sessions if item.id == session_id), None)
        if existing is not None:
            if existing.profile_id not in {profile_id, "LOCAL-LEGACY"}:
                raise ValueError("That conversation belongs to a different local profile.")
            return existing
        session = ChatSession(
            project_id=project_id, ticket_id=ticket_id,
            profile_id=profile_id,
            title=" ".join(message.split())[:80],
        )
        writer = getattr(self.store, "save_chat_session", None)
        if callable(writer):
            writer(session)
        return session

    def _turns(self, session_id: str) -> list[ChatTurn]:
        reader = getattr(self.store, "chat_turns", None)
        return [turn for turn in reader(session_id) if not turn.superseded_by_turn_id] if callable(reader) else []

    @staticmethod
    def _is_follow_up(message: str) -> bool:
        normalized = re.sub(r"[^a-z0-9 ]", "", message.lower()).strip()
        return normalized in {
            "repeat that", "repeat that exactly", "what did you say",
            "why", "why is that", "what do you mean",
        }

    @staticmethod
    def _is_verification_follow_up(message: str) -> bool:
        normalized = re.sub(r"[^a-z0-9 ]", "", message.lower()).strip()
        return normalized in {
            "are you sure", "are you certain", "really", "can you verify that",
            "verify that", "prove it",
        }

    @staticmethod
    def _is_contextual_follow_up(message: str) -> bool:
        normalized = message.lower()
        return bool(re.search(
            r"\b(it|its|that|this|those|them|they|previous|earlier)\b|"
            r"\bwhat about\b|\bcompared? (?:to|with)\b|\bactually\b|\bbut\b",
            normalized,
        ))

    def _reconstruct_context(self, message: str, turns: list[ChatTurn]):
        if not turns:
            return message, {
                "context_turn_ids": [], "context_claim_ids": [],
                "context_token_estimate": 0,
            }
        records = []
        claim_ids = []
        turn_ids = []
        characters = 0
        for turn in reversed(turns):
            record = None
            if turn.claim_id:
                claim = self.store.get_claim(turn.claim_id)
                if claim is None or claim.validity_status != ClaimValidity.CURRENT:
                    continue
                record = (
                    f"Turn {turn.id}; prior claim {claim.id} (hypothesis, not assumed true): "
                    f"{claim.conclusion}; evidence paths: "
                    + ", ".join(item.path for item in claim.evidence)
                )
            elif "NO_MODEL_CALL" in turn.authority:
                record = (
                    f"Turn {turn.id}; deterministic prior response ({turn.route}): {turn.answer}"
                )
            if record is None:
                continue
            if characters + len(record) > 6_000:
                break
            characters += len(record)
            records.append(record)
            turn_ids.append(turn.id)
            if turn.claim_id:
                claim_ids.append(turn.claim_id)
        if not records:
            return message, {
                "context_turn_ids": [], "context_claim_ids": [],
                "context_token_estimate": 0,
            }
        context = "\n".join(reversed(records))
        contextualized = (
            f"Current user question: {message}\n\nPersisted conversation context follows. "
            "Use it only to resolve references. Re-check every prior claim against current "
            f"repository evidence and seek contradictions.\n{context}"
        )
        return contextualized, {
            "context_turn_ids": list(reversed(turn_ids)),
            "context_claim_ids": list(reversed(claim_ids)),
            "context_token_estimate": (len(contextualized) + 3) // 4,
        }

    def _verify_follow_up(self, message: str, prior: ChatTurn) -> dict[str, object]:
        prior_claim = self.store.get_claim(prior.claim_id)
        if prior_claim is None or prior_claim.validity_status != ClaimValidity.CURRENT:
            return {
                "answer": "I cannot verify that response because its exact supporting claim is missing or invalidated.",
                "route": "RLM_MEMORY_REJECTED", "operation_route": "REJECTED_MEMORY",
                "investigation_mode": prior.investigation_mode,
                "routing_confidence": 1.0, "claim_confidence": None,
                "routing_reason": "The verification request was bound to the exact prior turn and claim.",
                "scope": prior.scope.value, "project_id": prior.project_id,
                "ticket_id": prior.ticket_id, "rejected_claim_id": prior.claim_id,
                "evidence": [],
                "authority": "READ_ONLY_MEMORY_VALIDATION_NO_MODEL_CALL",
            }
        if prior.scope == ChatScope.SYSTEM:
            root = self.system_root
        else:
            project = next(
                (item for item in self._items("projects") if item.id == prior.project_id), None
            )
            if project is None:
                raise ValueError("The project used by the prior claim is no longer registered.")
            root = Path(project.root)
        verification_question = (
            f"{message} Independently test the following prior claim as a hypothesis; do not "
            f"assume it is correct, and seek contradictory evidence. Prior claim ID "
            f"{prior_claim.id}: {prior_claim.conclusion}"
        )
        result = self.recursive_supervisor.run(
            verification_question, root, force_investigation=True
        )
        claim = result.claim
        return {
                "answer": claim.conclusion, "route": "RLM_CLAIM_VERIFICATION",
                "operation_route": "CLAIM_VERIFICATION", "routing_confidence": 1.0,
                "investigation_mode": "RECURSIVE",
            "routing_reason": "The verification was bound to the exact prior turn and claim.",
            "claim_confidence": claim.confidence, "confidence": claim.confidence,
            "scope": prior.scope.value, "project_id": prior.project_id,
            "ticket_id": prior.ticket_id, "task_id": result.task.id, "claim_id": claim.id,
            "challenged_claim_id": prior_claim.id,
            "evidence": [item.model_dump(mode="json") for item in claim.evidence],
            "unresolved_questions": claim.unresolved_questions,
            "authority": "READ_ONLY_FRESH_CLAIM_VERIFICATION_NO_WRITE_AUTHORITY",
        }

    def _exact_follow_up(self, prior: ChatTurn, project_id, ticket_id) -> dict[str, object]:
        if prior.claim_id:
            claim = self.store.get_claim(prior.claim_id)
            current_fingerprint = None
            project = next((p for p in self._items("projects") if p.id == prior.project_id), None)
            if project and project.latest_scan_id:
                scan = next(
                    (s for s in self._items("project_scans") if s.id == project.latest_scan_id), None
                )
                current_fingerprint = getattr(scan, "project_fingerprint", None)
            stale = (
                claim is None or claim.validity_status != ClaimValidity.CURRENT
                or (current_fingerprint and claim.project_fingerprint != current_fingerprint)
            )
            if stale:
                return {
                    "answer": "I cannot replay that answer: its supporting claim is stale, invalidated, or no longer matches the selected repository state.",
                    "route": "RLM_MEMORY_REJECTED", "operation_route": "REJECTED_MEMORY",
                    "investigation_mode": prior.investigation_mode,
                    "routing_confidence": 1.0, "claim_confidence": None,
                    "authority": "READ_ONLY_MEMORY_VALIDATION_NO_MODEL_CALL",
                    "project_id": prior.project_id, "ticket_id": prior.ticket_id,
                    "scope": prior.scope.value,
                    "rejected_claim_id": prior.claim_id, "evidence": [],
                }
            return {
                "answer": f"Yes—replaying the exact claim from the prior turn: {claim.conclusion}",
                "route": "RLM_EXACT_REPLAY", "operation_route": "EXACT_REPLAY",
                "investigation_mode": prior.investigation_mode,
                "routing_confidence": 1.0, "claim_confidence": claim.confidence,
                "confidence": claim.confidence,
                "authority": "READ_ONLY_EXACT_CLAIM_REPLAY_NO_MODEL_CALL",
                "project_id": prior.project_id, "ticket_id": prior.ticket_id,
                "scope": prior.scope.value, "claim_id": claim.id,
                "task_id": prior.task_id,
                "evidence": [item.model_dump(mode="json") for item in claim.evidence],
            }
        return {
            "answer": f"Yes—this is the exact prior RLMGraph response: {prior.answer}",
            "route": "RLM_EXACT_REPLAY", "operation_route": "EXACT_REPLAY",
            "investigation_mode": prior.investigation_mode,
            "routing_confidence": 1.0, "claim_confidence": prior.claim_confidence,
            "confidence": prior.claim_confidence,
            "authority": "READ_ONLY_EXACT_TURN_REPLAY_NO_MODEL_CALL",
            "project_id": prior.project_id, "ticket_id": prior.ticket_id,
            "scope": prior.scope.value, "evidence": prior.evidence,
        }

    def _persist(self, session, message, result, parent_turn_id=None):
        interpretation_record = result.pop("_interpretation_record", None)
        projection = result.get("memory_projection")
        memory_receipt = None
        if isinstance(projection, dict):
            fact_ids = list(dict.fromkeys(
                fact["id"]
                for key in ("relevant_facts", "relevant_profile_memories")
                for fact in projection.get(key, [])
            ))
            memory_receipt = {
                "fact_ids": fact_ids,
                "cited_fact_ids": [
                    fact_id for fact_id in result.get("conversation_response_fact_ids", [])
                    if fact_id in fact_ids
                ],
                "turn_ids": projection.get("relevant_turn_ids", []),
                "token_estimate": projection.get("token_estimate", 0),
            }
        memory_updates = []
        association_updates = []
        relationship_updates = []
        cluster_updates = []
        branch_updates = []
        turn_reader = getattr(self.store, "chat_turns", None)
        turns = list(turn_reader(session.id)) if callable(turn_reader) else []
        claim_reader = getattr(self.store, "get_claim", None)
        persisted_claim = (
            claim_reader(result["claim_id"])
            if result.get("claim_id") and callable(claim_reader) else None
        )
        turn = ChatTurn(
            session_id=session.id, ordinal=max((turn.ordinal for turn in turns), default=0) + 1, user_message=message,
            answer=str(result["answer"]),
            scope=ChatScope(str(result.get("scope", ChatScope.SYSTEM.value))),
            route=str(result["route"]),
            intent=str(result.get("intent", MessageIntent.INVESTIGATE.value)),
            intent_confidence=float(result.get("intent_confidence", 1.0)),
            intent_rationale=str(result.get("intent_rationale", "")),
            interpretation_id=result.get("interpretation_id"),
            interpretation_fallback=bool(result.get("interpretation_fallback", False)),
            routing_confidence=float(result.get("routing_confidence", 1.0)),
            routing_reason=str(result.get("routing_reason", "")),
            investigation_mode=str(result.get("investigation_mode", "DIRECT")),
            claim_confidence=result.get("claim_confidence"), project_id=result.get("project_id"),
            ticket_id=result.get("ticket_id"), task_id=result.get("task_id"),
            claim_id=result.get("claim_id"),
            project_fingerprint=(persisted_claim.project_fingerprint if persisted_claim else None),
            parent_turn_id=parent_turn_id, reuse_kind=result.get("operation_route"),
            context_turn_ids=list(result.get("context_turn_ids", [])),
            context_claim_ids=list(result.get("context_claim_ids", [])),
            context_token_estimate=int(result.get("context_token_estimate", 0)),
            conversation_memory_receipt=memory_receipt,
            authority=str(result.get("authority", "READ_ONLY_CHAT_NO_WRITE_AUTHORITY")),
            evidence=list(result.get("evidence", [])),
        )
        writer = getattr(self.store, "save_chat_turn", None)
        if callable(writer):
            writer(turn)
            interpretation_writer = getattr(
                self.store, "save_conversation_interpretation", None
            )
            if interpretation_record is not None and callable(interpretation_writer) and result["route"] != "RLM_RECOVERY":
                interpretation_record.turn_id = turn.id
                interpretation_writer(interpretation_record)
                memory_updates, association_updates = (
                    self.conversation_memory.commit_with_associations(turn, interpretation_record)
                )
                association_ids = {item.id for item in association_updates}
                relationship_reader = getattr(
                    self.store, "memory_relationship_interpretations", None
                )
                if callable(relationship_reader):
                    relationship_updates = [
                        item for item in relationship_reader(session.id)
                        if item.association_id in association_ids
                    ]
                memory_ids = {item.id for item in memory_updates}
                cluster_reader = getattr(self.store, "memory_clusters", None)
                if callable(cluster_reader):
                    cluster_updates = [
                        item for item in cluster_reader(session.id)
                        if memory_ids.intersection(item.supporting_fact_ids)
                    ][:12]
                branch_reader = getattr(self.store, "concept_branches", None)
                if callable(branch_reader):
                    branch_updates = [
                        item for item in branch_reader(session.id)
                        if memory_ids.intersection(item.supporting_fact_ids)
                    ][:12]
            session.updated_at = datetime.now(UTC)
            self.store.save_chat_session(session)
        return {
            **result,
            "session_id": session.id,
            "turn_id": turn.id,
            "conversation_memory_receipt": memory_receipt,
            "conversation_memory_updates": [
                fact.model_dump(mode="json") for fact in memory_updates
            ],
            "memory_association_updates": [
                association.model_dump(mode="json") for association in association_updates
            ],
            "memory_relationship_interpretation_updates": [
                interpretation.model_dump(mode="json")
                for interpretation in relationship_updates
            ],
            "memory_cluster_updates": [
                cluster.model_dump(mode="json") for cluster in cluster_updates
            ],
            "concept_branch_updates": [
                branch.model_dump(mode="json") for branch in branch_updates
            ],
        }

    def _items(self, method: str) -> list:
        reader = getattr(self.store, method, None)
        return list(reader()) if callable(reader) else []

    def _project_registry_reply(
        self, project_id: str | None, ticket_id: str | None
    ) -> dict[str, object]:
        projects = self._items("projects")
        tickets = self._items("project_tickets")
        records = []
        for project in projects:
            project_tickets = [item for item in tickets if item.project_id == project.id]
            statuses = {
                status: sum(item.status == status for item in project_tickets)
                for status in sorted({item.status for item in project_tickets})
            }
            records.append({
                "id": project.id,
                "name": Path(project.root).name,
                "root": project.root,
                "organization": project.organization,
                "read_only_index": project.read_only,
                "latest_scan_id": project.latest_scan_id,
                "ticket_count": len(project_tickets),
                "ticket_statuses": statuses,
                "selected": project.id == project_id,
            })
        if not records:
            answer = "RLMGraph has no connected projects yet."
        else:
            descriptions = []
            for item in records:
                status = ", ".join(
                    f"{count} {name.lower()}" for name, count in item["ticket_statuses"].items()
                ) or "no tickets"
                selected = " (selected)" if item["selected"] else ""
                descriptions.append(
                    f"{item['name']}{selected}: {item['root']} — {status}"
                )
            answer = f"RLMGraph has {len(records)} connected project(s): " + "; ".join(descriptions) + "."
        return {
            "answer": answer,
            "route": "RLM_PROJECT_REGISTRY",
            "operation_route": "REGISTRY",
            "investigation_mode": "DIRECT",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 0.99,
            "claim_confidence": None,
            "authority": "READ_ONLY_REGISTRY_QUERY_NO_MODEL_CALL",
            "project_id": project_id,
            "ticket_id": ticket_id,
            "projects": records,
            "evidence": [{"source": "project_registry", "records": len(records)}],
        }

    def _usage_reply(self, project_id: str | None, ticket_id: str | None) -> dict[str, object]:
        executions = self._items("execution_attempts")
        planning = self._items("planning_runs")
        benchmarks = self._items("benchmark_runs")
        pathways = self._items("pathway_benchmarks")
        proofs = self._items("codex_readonly_proofs")
        evaluations = self._items("generic_codex_evaluations")
        sessions = self._items("resumable_session_evaluations")
        workspaces = self._items("project_workspace_records")
        sandboxes = self._items("implementation_sandboxes")
        execution_tokens = sum(item.total_tokens for item in executions)
        retrieval_tokens = sum(item.retrieval_tokens_used for item in planning)
        measured_usage = execution_tokens + retrieval_tokens
        workspace_tokens = sum(item.tokens_used for item in workspaces)
        measured_usage += workspace_tokens
        unmetered_calls = sum(item.model_calls for item in sandboxes)
        baseline = sum(item.fixed.total_tokens for item in benchmarks)
        rlm = sum(item.active.total_tokens for item in benchmarks)
        baseline += sum(item.active_input_tokens for item in pathways)
        rlm += sum(item.token_input_tokens for item in pathways)
        baseline += sum(item.fresh_baseline_input_tokens + item.fresh_baseline_output_tokens for item in proofs)
        rlm += sum(item.input_tokens + item.output_tokens for item in proofs)
        baseline += sum(item.fresh_input_tokens for item in evaluations)
        rlm += sum(item.reuse_input_tokens for item in evaluations)
        avoided = sum(item.avoided_input_tokens for item in sessions)
        baseline += avoided
        savings = max(0, baseline - rlm)
        savings_percent = round((savings / baseline) * 100, 1) if baseline else None
        comparisons = len(benchmarks) + len(pathways) + len(proofs) + len(evaluations) + len(sessions)
        metrics = {
            "observed_usage_tokens": measured_usage,
            "execution_tokens": execution_tokens,
            "retrieval_context_tokens": retrieval_tokens,
            "workspace_tokens": workspace_tokens,
            "measured_baseline_tokens": baseline,
            "measured_rlm_tokens": rlm,
            "measured_savings_tokens": savings,
            "measured_savings_percent": savings_percent,
            "comparison_count": comparisons,
            "unmetered_model_calls": unmetered_calls,
        }
        answer = (
            f"RLMGraph has directly recorded {measured_usage:,} runtime tokens. "
            + (f"Controlled comparisons measured {baseline:,} baseline tokens versus {rlm:,} "
               f"RLM/reuse tokens: {savings:,} saved ({savings_percent}%)."
               if baseline else
               "There are no controlled baseline comparisons yet, so it cannot honestly claim a savings amount or percentage.")
        )
        if unmetered_calls:
            answer += f" {unmetered_calls} implementation model call(s) were not token-metered, so actual usage is higher."
        return {
            "answer": answer,
            "route": "RLM_TELEMETRY_LEDGER",
            "operation_route": "TELEMETRY",
            "investigation_mode": "DIRECT",
            "scope": ChatScope.SYSTEM.value,
            "routing_confidence": 0.99,
            "claim_confidence": None,
            "authority": "READ_ONLY_MEASUREMENT_NO_MODEL_CALL",
            "project_id": project_id,
            "ticket_id": ticket_id,
            "metrics": metrics,
            "evidence": [
                {"source": "execution_attempts", "records": len(executions)},
                {"source": "planning_runs", "records": len(planning)},
                {"source": "controlled_comparisons", "records": comparisons},
                {"source": "implementation_sandboxes", "records": len(sandboxes)},
            ],
            "limitations": [
                "Runtime usage and controlled-comparison savings are separate measurements.",
                "Account-level ChatGPT/Codex usage is unavailable unless the provider exposes it.",
                "Savings are reported only from persisted baseline-versus-RLM comparisons.",
            ],
        }
