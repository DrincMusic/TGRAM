from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


@dataclass(frozen=True)
class WorldMemoryScore:
    memory_id: str
    memory_kind: str
    deterministic_score: float
    neural_score: float


class WorldMemoryRanker(TokenizedMemoryStore):
    """A persisted learned ranker for non-conversational, verified world memories.

    The network may order provenance-approved candidates, but it never creates records,
    changes invariants, or admits submission-derived data. Until outcome feedback makes
    it ready, ranking remains deterministic and the MLP learns in shadow mode.
    """

    tokenization_mode = TokenizationMode.EMBEDDED_MODEL_STATE

    dimensions = 32
    input_size = 71
    hidden_size = 16
    learning_rate = .018
    model_version = "world-memory-ranker-mlp-v1"
    minimum_training_examples = 250
    minimum_outcome_examples = 40
    minimum_agreement = .8

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        generator = random.Random(113)
        self.w1 = [[generator.uniform(-.08, .08) for _ in range(self.input_size)]
                   for _ in range(self.hidden_size)]
        self.b1 = [0.0] * self.hidden_size
        self.w2 = [generator.uniform(-.08, .08) for _ in range(self.hidden_size)]
        self.b2 = 0.0
        self.training_examples = 0
        self.outcome_examples = 0
        self.rolling_loss = 0.0
        self.top_k_agreement = 0.0
        self._load()

    def rank(self, query: str, candidates: list[tuple]) -> tuple[list[str], dict]:
        """Rank ``(id, text, deterministic score, kind, confidence)`` candidates."""
        if not candidates:
            return [], self.state()
        maximum = max(item[2] for item in candidates) or 1.0
        predictions: list[tuple[float, str]] = []
        deterministic_ids = [item[0] for item in sorted(candidates, key=lambda x: (-x[2], x[0]))]
        scores = []
        for candidate in candidates:
            memory_id, memory_text, deterministic_score, kind, confidence = candidate[:5]
            cached_vector = candidate[5] if len(candidate) > 5 else None
            cached_terms = candidate[6] if len(candidate) > 6 else None
            features = self._features(
                query, memory_text, deterministic_score / maximum, kind, confidence,
                cached_vector, cached_terms,
            )
            prediction, hidden = self._forward(features)
            target = max(0.0, min(1.0, deterministic_score / maximum))
            self._train(features, hidden, prediction, target)
            self._record_loss(prediction, target)
            predictions.append((prediction, memory_id))
            scores.append(WorldMemoryScore(memory_id, kind, deterministic_score, prediction))
        neural_ids = [item[1] for item in sorted(predictions, key=lambda x: (-x[0], x[1]))]
        cutoff = min(8, len(deterministic_ids))
        agreement = len(set(neural_ids[:cutoff]) & set(deterministic_ids[:cutoff])) / max(cutoff, 1)
        self.top_k_agreement = self._ema(self.top_k_agreement, agreement)
        self._save()
        # Learning cannot suppress deterministic recall. Once ready it only breaks ties
        # within equal deterministic relevance bands.
        neural_by_id = {memory_id: score for score, memory_id in predictions}
        tie_score = (lambda item: -neural_by_id[item[0]]) if self.ready() else (lambda item: item[0])
        ordered = [item[0] for item in sorted(
            candidates, key=lambda item: (-item[2], tie_score(item), item[0]),
        )]
        return ordered, {
            **self.state(),
            "scores": [vars(item) for item in sorted(scores, key=lambda x: (-x.neural_score, x.memory_id))[:24]],
        }

    def reinforce(self, query: str, candidates: list[tuple], used_ids: set[str],
                  *, rejected_ids: set[str] | None = None) -> None:
        if not used_ids and not rejected_ids:
            return
        maximum = max((item[2] for item in candidates), default=1.0) or 1.0
        for candidate in candidates:
            memory_id, text, score, kind, confidence = candidate[:5]
            cached_vector = candidate[5] if len(candidate) > 5 else None
            cached_terms = candidate[6] if len(candidate) > 6 else None
            features = self._features(
                query, text, score / maximum, kind, confidence, cached_vector, cached_terms,
            )
            prediction, hidden = self._forward(features)
            target = 1.0 if memory_id in used_ids else .1
            self._train(features, hidden, prediction, target)
            self._record_loss(prediction, target)
            self.outcome_examples += 1
        self._save()

    def ready(self) -> bool:
        return (self.training_examples >= self.minimum_training_examples
                and self.outcome_examples >= self.minimum_outcome_examples
                and self.top_k_agreement >= self.minimum_agreement)

    def state(self) -> dict:
        return {
            "model_version": self.model_version,
            "mode": "ASSISTED_TIE_BREAK" if self.ready() else "SHADOW",
            "training_examples": self.training_examples,
            "outcome_examples": self.outcome_examples,
            "rolling_loss": round(self.rolling_loss, 6),
            "top_k_agreement": round(self.top_k_agreement, 4),
            "ready_for_evaluation": self.ready(),
            "parameter_count": self.hidden_size * self.input_size + self.hidden_size * 2 + 1,
        }

    def _features(self, query: str, text: str, relevance: float, kind: str,
                  confidence: float, cached_vector=None, cached_terms=None) -> list[float]:
        query_terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
        memory_terms = set(cached_terms or re.findall(r"[a-z0-9_]+", text.casefold()))
        overlap = len(query_terms & memory_terms) / max(len(query_terms | memory_terms), 1)
        kinds = ("geometry", "object", "spatial", "physics")
        memory_vector = list(cached_vector) if cached_vector else self._hash_vector(text)
        return [*self._hash_vector(query), *memory_vector, overlap,
                max(0.0, min(1.0, relevance)), max(0.0, min(1.0, confidence)),
                *(float(kind == item) for item in kinds)]

    @classmethod
    def _hash_vector(cls, text: str) -> list[float]:
        vector = [0.0] * cls.dimensions
        for term in re.findall(r"[a-z0-9_]+", text.casefold()):
            digest = sha256(term.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % cls.dimensions
            vector[index] += 1.0 if digest[2] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _forward(self, features: list[float]) -> tuple[float, list[float]]:
        hidden = [math.tanh(sum(w * x for w, x in zip(row, features)) + bias)
                  for row, bias in zip(self.w1, self.b1)]
        logit = sum(w * x for w, x in zip(self.w2, hidden)) + self.b2
        return 1 / (1 + math.exp(-max(-30.0, min(30.0, logit)))), hidden

    def _train(self, features: list[float], hidden: list[float], prediction: float, target: float) -> None:
        delta_out = prediction - target
        old_w2 = list(self.w2)
        for index in range(self.hidden_size):
            self.w2[index] -= self.learning_rate * delta_out * hidden[index]
        self.b2 -= self.learning_rate * delta_out
        for h in range(self.hidden_size):
            delta = delta_out * old_w2[h] * (1 - hidden[h] ** 2)
            for index, value in enumerate(features):
                self.w1[h][index] -= self.learning_rate * delta * value
            self.b1[h] -= self.learning_rate * delta
        self.training_examples += 1

    def _record_loss(self, prediction: float, target: float) -> None:
        self.rolling_loss = self._ema(self.rolling_loss, (prediction - target) ** 2)

    @staticmethod
    def _ema(previous: float, current: float, weight: float = .05) -> float:
        return current if previous == 0 else (1 - weight) * previous + weight * current

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("model_version") != self.model_version:
                return
            for name in ("w1", "b1", "w2", "b2", "training_examples", "outcome_examples", "rolling_loss", "top_k_agreement"):
                setattr(self, name, state[name])
        except (OSError, ValueError, KeyError, TypeError):
            return

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: getattr(self, name) for name in (
            "model_version", "w1", "b1", "w2", "b2", "training_examples",
            "outcome_examples", "rolling_loss", "top_k_agreement",
        )}
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            temporary.unlink(missing_ok=True)
