from __future__ import annotations

import json
import re
from pathlib import Path

from .models import SystemEvaluationMemory
from .tokenized_memory_store import TokenizationMode, TokenizedMemoryStore

_TERMS = re.compile(r"[a-z0-9_.%-]+", re.IGNORECASE)


class SystemEvaluationMemoryStore(TokenizedMemoryStore):
    """Append-only TGRAM evaluation memory with bounded evidence-aware retrieval."""

    tokenization_mode = TokenizationMode.SIDECAR_INDEX

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        self.token_index = TokenizedMemoryStore.token_index(self.path)

    def records(self) -> list[SystemEvaluationMemory]:
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(SystemEvaluationMemory.model_validate_json(line))
            except (ValueError, json.JSONDecodeError):
                continue
        return records

    def remember_credible_suite(
        self, result: dict, source_report_path: Path, *, models: list[str] | None = None,
        invalidates_evaluation_ids: list[str] | None = None,
    ) -> SystemEvaluationMemory:
        suite_id = str(result["id"])
        for record in self.records():
            if record.suite_id == suite_id:
                return record
        summary = result["summary"]
        verdict = str(summary["verdict"])
        evidence_eligible = bool(
            verdict == "VALID_SAVINGS_COMPARISON"
            and summary.get("quality_gate_passed")
            and summary.get("quality_gated_median_savings_percent") is not None
        )
        trial_count = int(result.get("trial_count", 0))
        project_count = int(result.get("project_count", 0))
        record = SystemEvaluationMemory(
            evaluation_type="CREDIBLE_PROJECT_BENCHMARK",
            suite_id=suite_id,
            title=f"{trial_count}-trial quality-gated autonomous coding comparison",
            summary=(
                f"TGRAM completed {trial_count} fresh paired trials across {project_count} "
                f"project families. Verdict: {verdict}."
            ),
            verdict=verdict,
            evidence_eligible=evidence_eligible,
            models=list(dict.fromkeys(models or ["gpt-5.4"])),
            methodology=[
                "fresh state and project copy for each arm",
                "randomized arm order",
                "identical hidden acceptance tests",
                "repair tokens included",
                f"minimum per-trial quality threshold {result.get('quality_threshold', 0):.0%}",
                "median provider-reported tokens compared only after both arms met quality",
            ],
            metrics={
                "trial_count": trial_count,
                "project_count": project_count,
                "repetitions": int(result.get("repetitions", 0)),
                "baseline_pass_rate": summary.get("baseline_pass_rate"),
                "tgram_pass_rate": summary.get("rlmgraph_pass_rate"),
                "baseline_median_tokens": summary.get("baseline_median_tokens"),
                "tgram_median_tokens": summary.get("rlmgraph_median_tokens"),
                "median_token_savings_percent": summary.get(
                    "quality_gated_median_savings_percent"
                ),
                "quality_gate_passed": bool(summary.get("quality_gate_passed")),
            },
            findings=[
                "Token savings are evidence-eligible only when every paired trial meets the quality gate.",
                "Cached input tokens are included in provider-reported totals.",
            ],
            limitations=[
                "The suite used small five-task projects rather than large production repositories.",
                "Provider-reported token reduction is not automatically identical to monetary savings.",
                "The result does not establish performance for models or workflows not tested.",
            ],
            source_report_path=str(source_report_path.resolve()),
            invalidates_evaluation_ids=list(dict.fromkeys(invalidates_evaluation_ids or [])),
        )
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(record.model_dump_json() + "\n")
        self.token_index.remember(
            record.id, self._searchable(record),
            importance=.95 if record.evidence_eligible else .35,
            protected=record.evidence_eligible,
        )
        return record

    def retrieve(self, query: str, *, limit: int = 4) -> list[SystemEvaluationMemory]:
        query_terms = set(_TERMS.findall(query.casefold()))
        asks_invalid = bool(re.search(
            r"\b(?:invalid|invalidated|unfair|broken|failed|inconclusive|previous|earlier)\b",
            query, re.IGNORECASE,
        ))
        scored = []
        records = self.records()
        for ordinal, record in enumerate(records):
            if not record.evidence_eligible and not asks_invalid:
                continue
            text = self._searchable(record)
            overlap = len(query_terms.intersection(self.token_index.terms(record.id, text)))
            evaluation_hint = bool(re.search(
                r"\b(?:test|trial|benchmark|evaluation|score|pass rate|tokens?|savings)\b",
                query, re.IGNORECASE,
            ))
            if not overlap and not evaluation_hint:
                continue
            score = 3 * overlap + (3 if evaluation_hint else 0) + (
                2 if record.evidence_eligible else 0
            ) + (ordinal + 1) / max(len(records), 1)
            scored.append((score, ordinal, record))
        return [item[2] for item in sorted(scored, key=lambda item: (-item[0], -item[1]))[:limit]]

    @staticmethod
    def _searchable(record: SystemEvaluationMemory) -> str:
        return " ".join((record.title, record.summary, record.verdict,
                         " ".join(record.models), " ".join(record.methodology),
                         " ".join(record.findings), " ".join(record.limitations),
                         json.dumps(record.metrics, sort_keys=True))).casefold()
