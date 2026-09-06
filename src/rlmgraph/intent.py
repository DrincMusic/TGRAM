from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MessageIntent(StrEnum):
    CONVERSE = "CONVERSE"
    INVESTIGATE = "INVESTIGATE"
    CHANGE = "CHANGE"
    VERIFY = "VERIFY"
    REPLAY = "REPLAY"
    TELEMETRY = "TELEMETRY"
    PROJECTS = "PROJECTS"
    HELP = "HELP"
    CLARIFY = "CLARIFY"


@dataclass(frozen=True)
class IntentDecision:
    intent: MessageIntent
    confidence: float
    rationale: str
    normalized_message: str
    recoverable: bool = True


class IntentRouter:
    """Deterministic, inspectable first-pass intent router.

    This deliberately does not grant authority. It identifies what the user appears to want;
    scope and mutation authorization remain separate decisions at their existing boundaries.
    """

    MAX_MESSAGE_LENGTH = 4_000
    _VERIFY = re.compile(
        r"^(?:are you sure|verify (?:that|this)|check (?:that|this) again|prove it|really)\??$",
        re.IGNORECASE,
    )
    _REPLAY = re.compile(
        r"^(?:repeat (?:that|this|your answer)(?: exactly)?|say that again|what did you say)\??$",
        re.IGNORECASE,
    )
    _CHANGE = re.compile(
        r"\b(?:fix|change|edit|implement|build|add|remove|upgrade|refactor|deploy|run|execute|"
        r"update|make (?:it|this|the) better)\b",
        re.IGNORECASE,
    )
    _HELP = re.compile(
        r"^(?:help|what can you do|how do i use (?:this|rlmgraph)|show commands)\??$",
        re.IGNORECASE,
    )
    _CONVERSATIONAL = re.compile(
        r"^(?:(?:hello|hi|hey|good (?:morning|afternoon|evening))(?: there)?[!.]?|"
        r"(?:thanks|thank you|got it|okay|ok|bye|goodbye)[!.]?)$",
        re.IGNORECASE,
    )
    _CONTEXT_DECLARATION = re.compile(
        r"^(?:this|the|my|our)\s+"
        r"(?:project|system|app|application|graph|repository|repo)\s+"
        r"(?:is|is called|is named|means|refers to)\s+\S.+$",
        re.IGNORECASE,
    )
    _CONTEXT_RECALL = re.compile(
        r"^(?:what|which)\s+(?:project|repository|repo)\s+"
        r"(?:are we discussing|are we (?:working|focused) on|is this|is current)\??$",
        re.IGNORECASE,
    )
    _CONVERSATIONAL_OPINION = re.compile(
        r"^(?:what (?:are )?your thoughts|what do you think|how do you feel)\s+"
        r"(?:about|on)\s+(?:this|the|our|my)\s+"
        r"(?:project|system|app|application|graph|repository|repo)\??$",
        re.IGNORECASE,
    )
    _SELF_MEMORY = re.compile(
        r"^(?:how does your memory (?:work|system work)|what is your memory system|"
        r"what do you remember|do you understand your (?:own )?memory(?: system)?)\??$",
        re.IGNORECASE,
    )
    _CONVERSATION_RECALL = re.compile(
        r"\b(?:do you remember|can you remember|what was my|what did i (?:say|tell you)|"
        r"remind me (?:what|about)|have i told you about|recall my)\b",
        re.IGNORECASE,
    )
    _SELF_IDENTITY = re.compile(
        r"^(?:what|who) are you\??$",
        re.IGNORECASE,
    )
    _SELF_ASSESSMENT = re.compile(
        r"^(?:what (?:is|are) your (?:biggest |main |current )?"
        r"(?:weakness|weaknesses|limitation|limitations|failure mode|failure modes)"
        r"(?: right now| currently)?|"
        r"what do you (?:see|consider) as your (?:biggest |main )?"
        r"(?:weakness|limitation|failure mode)(?: right now)?|"
        r"what do you think your (?:biggest |main |current )?"
        r"(?:weakness|limitation|failure mode) is(?: right now| currently)?|"
        r"what (?:can you not|can't you) (?:do|reliably do)|"
        r"where do you (?:fail|struggle)|"
        r"how (?:capable|reliable|autonomous) are you|"
        r"can you actually .+|are you actually able to .+)\??$",
        re.IGNORECASE,
    )

    @classmethod
    def normalize(cls, value: Any) -> tuple[str, str | None]:
        if value is None:
            return "", "The message was null."
        if not isinstance(value, str):
            return "", f"Expected a text message, but received {type(value).__name__}."
        message = " ".join(value.replace("\x00", " ").split())
        if not message:
            return "", "The message did not contain any readable text."
        if len(message) > cls.MAX_MESSAGE_LENGTH:
            return "", (
                f"The message is {len(message):,} characters; the safe limit is "
                f"{cls.MAX_MESSAGE_LENGTH:,}. Split it into smaller requests."
            )
        return message, None

    @classmethod
    def is_context_declaration(cls, value: str) -> bool:
        return bool(cls._CONTEXT_DECLARATION.fullmatch(value))

    @classmethod
    def is_context_recall(cls, value: str) -> bool:
        return bool(cls._CONTEXT_RECALL.fullmatch(value))

    @classmethod
    def is_conversational_opinion(cls, value: str) -> bool:
        return bool(cls._CONVERSATIONAL_OPINION.fullmatch(value))

    @classmethod
    def is_self_memory_question(cls, value: str) -> bool:
        return bool(cls._SELF_MEMORY.fullmatch(value))

    @classmethod
    def is_conversation_recall(cls, value: str) -> bool:
        return bool(cls._CONVERSATION_RECALL.search(value))

    @classmethod
    def is_self_identity_question(cls, value: str) -> bool:
        return bool(cls._SELF_IDENTITY.fullmatch(value))

    @classmethod
    def is_self_assessment_question(cls, value: str) -> bool:
        return bool(cls._SELF_ASSESSMENT.fullmatch(value))

    @classmethod
    def classify(cls, value: Any) -> IntentDecision:
        message, error = cls.normalize(value)
        if error:
            return IntentDecision(MessageIntent.CLARIFY, 1.0, error, "")
        lowered = message.casefold()
        if cls._VERIFY.fullmatch(message):
            return IntentDecision(MessageIntent.VERIFY, .99, "Explicit verification follow-up.", message)
        if cls._REPLAY.fullmatch(message):
            return IntentDecision(MessageIntent.REPLAY, .99, "Explicit replay follow-up.", message)
        if cls._CONVERSATIONAL.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .99,
                "The message is a conversational social act, not a workflow request.", message,
            )
        if cls._CONTEXT_DECLARATION.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .98,
                "The message supplies conversational identity or project context and requests no action.",
                message,
            )
        if cls._CONTEXT_RECALL.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .98,
                "The message asks to recall conversational context, not investigate a repository.",
                message,
            )
        if cls._CONVERSATION_RECALL.search(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .98,
                "The message asks to recall user conversation memory, not inspect a repository.",
                message,
            )
        if cls._CONVERSATIONAL_OPINION.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .96,
                "The message requests conversational discussion, not repository investigation.",
                message,
            )
        if cls._SELF_MEMORY.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .98,
                "The message asks RLMGraph to explain its typed memory state conversationally.",
                message,
            )
        if cls._SELF_IDENTITY.fullmatch(message):
            return IntentDecision(
                MessageIntent.CONVERSE, .99,
                "The message asks for RLMGraph's typed identity, not a worker investigation.",
                message,
            )
        if cls._SELF_ASSESSMENT.fullmatch(message):
            return IntentDecision(
                MessageIntent.INVESTIGATE, .99,
                "Current self-assessment requires source, test, or runtime evidence.", message,
            )
        if cls._HELP.fullmatch(message):
            return IntentDecision(MessageIntent.HELP, .98, "Explicit capability/help request.", message)
        if re.search(r"\b(?:connected projects|list (?:my |the )?projects|what projects)\b", lowered):
            return IntentDecision(MessageIntent.PROJECTS, .96, "Project registry request.", message)
        if re.search(r"\b(?:token usage|tokens used|cost|spend|savings|model calls)\b", lowered) and re.search(
            r"\b(?:what|how many|how much|show|report|measure|total|current|my|our)\b",
            lowered,
        ):
            return IntentDecision(MessageIntent.TELEMETRY, .91, "Usage or cost measurement request.", message)
        if cls._CHANGE.search(message):
            return IntentDecision(
                MessageIntent.CHANGE, .86,
                "The message asks for a real-world state or source change.", message,
            )
        return IntentDecision(
            MessageIntent.INVESTIGATE, .74,
            "No command intent matched; treating the text as a question to investigate.", message,
        )
