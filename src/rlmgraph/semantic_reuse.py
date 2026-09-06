from __future__ import annotations

import re

_STOP_WORDS = {
    "a", "an", "and", "are", "does", "for", "how", "in", "is", "of", "the",
    "this", "to", "what", "when", "where", "which", "why", "with", "guaranteed",
    "establish", "establishes", "explain", "behavior", "contract",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9_]+", text.casefold())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def semantic_question_score(left: str, right: str) -> float:
    """Deterministic, inspectable lexical similarity for diagnostic questions."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
