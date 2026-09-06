from __future__ import annotations

import json
from dataclasses import dataclass

from .project_task_graph import TaskLease


@dataclass(frozen=True)
class CompiledTaskContext:
    prompt: str
    characters: int
    estimated_tokens: int
    memory_count: int


class ProjectContextCompiler:
    """Builds minimal task packets; raw archive payloads are deliberately unsupported."""

    def __init__(
        self,
        *,
        char_budget: int = 5000,
        memory_char_budget: int = 1800,
        compact_instructions: bool = False,
        compact_packet: bool = False,
    ) -> None:
        self.char_budget = char_budget
        self.memory_char_budget = memory_char_budget
        self.compact_instructions = compact_instructions
        self.compact_packet = compact_packet

    def compile(
        self, *, lease: TaskLease, project_intent: str, phase: str,
        memories: list[dict], pass_index: int, pass_count: int,
    ) -> CompiledTaskContext:
        compact_memories: list[dict] = []
        used = 2
        for memory in memories:
            allowed = {
                key: memory[key]
                for key in (
                    "memory_id", "milestone", "phase", "action", "invariant", "concepts", "files",
                    "symbols", "confidence", "relevance", "archive_ref",
                    "project_scope", "origin_task_id", "claim_type",
                    "semantic_rule", "field_order", "run_canary",
                    "verification_status", "content_sha256",
                )
                if key in memory
            }
            encoded = json.dumps(allowed, separators=(",", ":"), ensure_ascii=False)
            if used + len(encoded) > self.memory_char_budget:
                continue
            compact_memories.append(allowed)
            used += len(encoded)

        packet = (
            {
                "task": {
                    "id": lease.task_id,
                    "attempt": lease.attempt,
                    "objective": lease.objective,
                    "acceptance": lease.acceptance,
                    "dependencies": lease.dependencies,
                },
                "relevant_memory": compact_memories,
            }
            if self.compact_packet
            else {
                "project_intent": " ".join(project_intent.split())[:500],
                "task": {
                    "id": lease.task_id,
                    "attempt": lease.attempt,
                    "objective": lease.objective,
                    "acceptance": lease.acceptance,
                    "dependencies": lease.dependencies,
                    "prior_failure": lease.prior_failure[:500],
                },
                "worker": {"phase": phase, "pass": pass_index, "pass_count": pass_count},
                "relevant_memory": compact_memories,
            }
        )
        if phase == "IMPLEMENT":
            phase_instruction = (
                "Make the smallest complete change, or make no edit when the contract already passes. "
                "Run a focused check and report evidence."
            )
        elif phase == "REPAIR":
            phase_instruction = (
                "The prior implementation failed deterministic acceptance. Diagnose the supplied "
                "failure evidence, inspect only relevant live symbols, and apply the smallest repair. "
                "Preserve all previously verified behavior and report the repair evidence."
            )
        else:
            phase_instruction = (
                "Remain read-only. Diagnose the failed acceptance check and propose the smallest repair."
            )
        instructions = (
            "Bounded worker. Apply TASK_PACKET exactly to supplied symbols; preserve other "
            "behavior. Return one surgical edit.\nTASK_PACKET="
            if self.compact_instructions
            else (
                "You are a fresh bounded worker controlled by a durable task graph. Use only this "
                "task packet plus live files you inspect. Preserve verified behavior. Do not perform "
                f"later tasks. {phase_instruction} Return rationale, changed files, and confidence."
                "\nTASK_PACKET="
            )
        )
        body = json.dumps(packet, separators=(",", ":"), ensure_ascii=False)
        while compact_memories and len(instructions) + len(body) > self.char_budget:
            compact_memories.pop()
            body = json.dumps(packet, separators=(",", ":"), ensure_ascii=False)
        if len(instructions) + len(body) > self.char_budget:
            raise ValueError(
                "Task context cannot fit the character budget as complete JSON."
            )
        prompt = instructions + body
        return CompiledTaskContext(
            prompt=prompt, characters=len(prompt), estimated_tokens=max(1, (len(prompt) + 3) // 4),
            memory_count=len(compact_memories),
        )
