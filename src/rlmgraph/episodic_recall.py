"""Bounded original-dialogue retrieval, independent of interpretation records."""

from __future__ import annotations

import math
import re
from collections import Counter

from .models import ConversationExcerpt

_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "i",
        "you",
        "me",
        "my",
        "your",
        "it",
        "is",
        "are",
        "was",
        "were",
        "if",
        "would",
        "could",
        "be",
        "to",
        "of",
        "and",
        "or",
        "that",
        "this",
        "in",
        "on",
        "for",
        "do",
        "what",
        "how",
    ]
)


def terms(text):
    return set(re.findall(r"[\w]+", text.casefold())) - _STOP


def retrieve_episodes(turns, query, session_id, max_characters=12000):
    """Search user utterances; include neighboring exchanges to recover shared meaning.

    Caller must supply only authorized profile history. Assistant text is returned as
    attributed dialogue, never promoted to a verified fact or used as a search anchor.
    """
    turns = [turn for turn in turns if not turn.superseded_by_turn_id]
    query_terms = terms(query)
    documents = [terms(turn.user_message) for turn in turns]
    frequencies = Counter(term for document in documents for term in document)
    ranked = sorted(
        (
            (
                sum(math.log(1 + len(turns) / frequencies[word]) for word in query_terms & document)
                + min(0.75, math.log1p(len(document)) / 10),
                index,
            )
            for index, document in enumerate(documents)
            if query_terms & document
        ),
        reverse=True,
    )
    indexes = []
    anchors, seen_text = [], set()
    for _, index in ranked:
        signature = " ".join(turns[index].user_message.casefold().split())
        if signature not in seen_text:
            seen_text.add(signature)
            anchors.append(index)
        if len(anchors) == 4:
            break
    for index in anchors:
        indexes.append(index)
        # Neighbors must belong to the same original conversation.
        for neighbor in (index - 1, index + 1):
            if 0 <= neighbor < len(turns) and turns[neighbor].session_id == turns[index].session_id:
                indexes.append(neighbor)
    indexes.extend(
        index for index, turn in reversed(list(enumerate(turns))) if turn.session_id == session_id
    )
    selected, used = [], 0
    for index in dict.fromkeys(indexes):
        if len(selected) >= 12 or used >= max_characters:
            break
        turn = turns[index]
        remaining = max_characters - used
        if len(turn.user_message) > remaining:
            continue
        answer = turn.answer[: remaining - len(turn.user_message)]
        selected.append(
            (
                index,
                ConversationExcerpt(
                    turn_id=turn.id,
                    user_message=turn.user_message,
                    assistant_answer=answer,
                    interpretation_id=turn.interpretation_id,
                ),
            )
        )
        used += len(turn.user_message) + len(answer)
    return [excerpt for _, excerpt in sorted(selected)]
