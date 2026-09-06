from __future__ import annotations

import json
import math
import random
import re
from hashlib import sha256
from pathlib import Path

from .memory_tokenization import (
    extract_memory_concepts,
    hashed_memory_vector,
    tokenize_memory,
)
from .models import ConversationFact, NeuralMemoryScore, NeuralMemoryState
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


class NeuralMemoryRanker(TokenizedMemoryStore):
    """Small persisted MLP trained in shadow mode from retrieval outcomes."""

    tokenization_mode = TokenizationMode.EMBEDDED_MODEL_STATE

    input_size = 68
    hidden_size = 12
    learning_rate = 0.025
    model_version = "memory-ranker-mlp-v1"
    minimum_training_examples = 200
    minimum_outcome_examples = 25
    minimum_agreement = .8
    rescue_threshold = .8

    def __init__(self, store) -> None:
        path = getattr(store, "path", None)
        self.state_path = Path(f"{path}.neural-memory.json") if path else None
        generator = random.Random(71)
        self.w1 = [
            [generator.uniform(-0.08, 0.08) for _ in range(self.input_size)]
            for _ in range(self.hidden_size)
        ]
        self.b1 = [0.0] * self.hidden_size
        self.w2 = [generator.uniform(-0.08, 0.08) for _ in range(self.hidden_size)]
        self.b2 = 0.0
        self.training_examples = 0
        self.outcome_examples = 0
        self.rolling_loss = 0.0
        self.top_k_agreement = 0.0
        self.token_cache: dict[str, dict] = {}
        self._load()

    def rank(
        self,
        query: str,
        candidates: list[tuple[ConversationFact, float]],
        selected_ids: set[str],
        current_session_id: str,
    ) -> list[NeuralMemoryScore]:
        if not candidates:
            return []
        maximum = max(score for _, score in candidates) or 1.0
        results = []
        predictions = []
        for fact, deterministic_score in candidates:
            features = self._features(query, fact, current_session_id)
            neural_score, hidden = self._forward(features)
            target = max(0.0, min(1.0, deterministic_score / maximum))
            self._record_loss(neural_score, target)
            self._train(features, hidden, neural_score, target)
            predictions.append((neural_score, fact.id))
            results.append(NeuralMemoryScore(
                memory_id=fact.id,
                memory_kind=fact.kind.value,
                deterministic_score=round(deterministic_score, 4),
                neural_score=round(neural_score, 4),
                selected=fact.id in selected_ids,
            ))
        neural_selected = {
            memory_id for _, memory_id in sorted(predictions, reverse=True)[:len(selected_ids)]
        }
        agreement = len(neural_selected & selected_ids) / max(len(selected_ids), 1)
        self.top_k_agreement = self._ema(self.top_k_agreement, agreement)
        self._save()
        return sorted(results, key=lambda item: (-item.neural_score, item.memory_id))[:24]

    def remember_text(self, memory_id: str, text: str, *, importance: float = .5,
                      protected: bool = False) -> None:
        """Tokenize a conversational memory once when it enters durable memory."""
        if memory_id in self.token_cache:
            return
        terms = tokenize_memory(text)
        self.token_cache[memory_id] = {
            "terms": list(terms),
            "concepts": list(extract_memory_concepts(text)),
            "vector": list(hashed_memory_vector(terms)),
            "importance": importance,
            "protected": protected,
            "access_count": 0,
        }
        self._release_unimportant()
        self._save()

    def terms(self, memory_id: str, text: str) -> set[str]:
        self.remember_text(memory_id, text)
        self.token_cache[memory_id]["access_count"] = (
            int(self.token_cache[memory_id].get("access_count", 0)) + 1
        )
        return set(self.token_cache[memory_id]["terms"])

    def _release_unimportant(self, max_entries: int = 5000) -> None:
        excess = len(self.token_cache) - max_entries
        if excess <= 0:
            return
        candidates = sorted(
            (float(value.get("importance", .5)), int(value.get("access_count", 0)), key)
            for key, value in self.token_cache.items() if not value.get("protected")
        )
        for _, _, memory_id in candidates[:excess]:
            self.token_cache.pop(memory_id, None)

    def reinforce(
        self, query: str, facts: list[ConversationFact], used_fact_ids: set[str],
        current_session_id: str,
    ) -> None:
        if not used_fact_ids:
            return
        for fact in facts:
            features = self._features(query, fact, current_session_id)
            prediction, hidden = self._forward(features)
            target = 1.0 if fact.id in used_fact_ids else 0.1
            self._record_loss(prediction, target)
            self._train(features, hidden, prediction, target)
            self.outcome_examples += 1
        self._save()

    def ready(self) -> bool:
        return (
            self.training_examples >= self.minimum_training_examples
            and self.outcome_examples >= self.minimum_outcome_examples
            and self.top_k_agreement >= self.minimum_agreement
        )

    def state(self, rescued_memory_ids: list[str] | None = None) -> NeuralMemoryState:
        rescued = list(rescued_memory_ids or [])[:2]
        return NeuralMemoryState(
            training_examples=self.training_examples,
            outcome_examples=self.outcome_examples,
            rolling_loss=round(self.rolling_loss, 6),
            top_k_agreement=round(self.top_k_agreement, 4),
            ready_for_evaluation=self.ready(),
            assisted_recall_enabled=self.ready(),
            rescued_memory_ids=rescued,
        )

    def _features(self, query: str, fact: ConversationFact, session_id: str) -> list[float]:
        query_vector = self._hash_vector(query)
        memory_text = f"{fact.subject} {fact.predicate} {fact.value}"
        self.remember_text(fact.id, memory_text)
        cached = self.token_cache[fact.id]
        memory_vector = cached["vector"]
        query_terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        memory_terms = set(cached["terms"])
        overlap = len(query_terms & memory_terms) / max(len(query_terms | memory_terms), 1)
        return [
            *query_vector,
            *memory_vector,
            overlap,
            fact.confidence,
            float(fact.kind.value == "IDENTITY"),
            float(fact.session_id == session_id),
        ]

    @staticmethod
    def _hash_vector(text: str, dimensions: int = 32) -> list[float]:
        vector = [0.0] * dimensions
        terms = re.findall(r"[a-z0-9_]+", text.casefold())
        for term in terms:
            digest = sha256(term.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % dimensions
            vector[index] += 1.0 if digest[2] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _forward(self, features: list[float]) -> tuple[float, list[float]]:
        hidden = [
            math.tanh(sum(weight * value for weight, value in zip(row, features)) + bias)
            for row, bias in zip(self.w1, self.b1)
        ]
        logit = sum(weight * value for weight, value in zip(self.w2, hidden)) + self.b2
        score = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, logit))))
        return score, hidden

    def _train(
        self, features: list[float], hidden: list[float], prediction: float, target: float
    ) -> None:
        output_delta = prediction - target
        old_w2 = list(self.w2)
        for index in range(self.hidden_size):
            self.w2[index] -= self.learning_rate * output_delta * hidden[index]
        self.b2 -= self.learning_rate * output_delta
        for hidden_index in range(self.hidden_size):
            delta = output_delta * old_w2[hidden_index] * (1.0 - hidden[hidden_index] ** 2)
            for input_index, value in enumerate(features):
                self.w1[hidden_index][input_index] -= self.learning_rate * delta * value
            self.b1[hidden_index] -= self.learning_rate * delta
        self.training_examples += 1

    def _record_loss(self, prediction: float, target: float) -> None:
        loss = (prediction - target) ** 2
        self.rolling_loss = self._ema(self.rolling_loss, loss)

    @staticmethod
    def _ema(previous: float, current: float, weight: float = .05) -> float:
        return current if previous == 0.0 else (1 - weight) * previous + weight * current

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("model_version") != self.model_version:
                return
            self.w1 = state["w1"]
            self.b1 = state["b1"]
            self.w2 = state["w2"]
            self.b2 = state["b2"]
            self.training_examples = int(state.get("training_examples", 0))
            self.outcome_examples = int(state.get("outcome_examples", 0))
            self.rolling_loss = float(state.get("rolling_loss", 0.0))
            self.top_k_agreement = float(state.get("top_k_agreement", 0.0))
            self.token_cache = dict(state.get("token_cache", {}))
        except (OSError, ValueError, KeyError, TypeError):
            return

    def _save(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "model_version": self.model_version,
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "training_examples": self.training_examples,
            "outcome_examples": self.outcome_examples,
            "rolling_loss": self.rolling_loss,
            "top_k_agreement": self.top_k_agreement,
            "token_cache": self.token_cache,
            "w1": self.w1,
            "b1": self.b1,
            "w2": self.w2,
            "b2": self.b2,
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            temporary.unlink(missing_ok=True)
