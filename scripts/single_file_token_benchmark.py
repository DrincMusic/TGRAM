from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rlmgraph.adapters import _strict_output_schema
from rlmgraph.implementation_sandbox import CodexPlanImplementationWorker
from rlmgraph.model_call_ledger import (
    configure_model_call_ledger,
    estimate_tokens,
    model_call_scope,
)
from rlmgraph.models import SingleCallSurgicalResult
from rlmgraph.project_symbol_memory import ProjectSymbolMemory

ITERATIONS = [
    (
        "In pricing.py, change calculate_total so it returns subtotal * (1 + tax_rate).",
        lambda fn: abs(fn(100, 0.1) - 110) < 1e-9,
    ),
    (
        "In pricing.py, change calculate_total so its result is rounded to two decimal places.",
        lambda fn: fn(10.01, 0.075) == 10.76,
    ),
    (
        "In pricing.py, change calculate_total to raise ValueError when subtotal is negative.",
        lambda fn: _raises_value_error(fn, -1, 0.1),
    ),
    (
        "In pricing.py, change calculate_total to raise ValueError when tax_rate is negative.",
        lambda fn: _raises_value_error(fn, 1, -0.1),
    ),
    (
        "In pricing.py, add a return type annotation of float to calculate_total without changing its behavior.",
        lambda fn: fn.__annotations__.get("return") in {float, "float"},
    ),
]


def _raises_value_error(function, *arguments) -> bool:
    try:
        function(*arguments)
    except ValueError:
        return True
    return False


def _load_function(path: Path):
    name = f"single_file_benchmark_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.calculate_total


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    result_dir = workspace / ".rlmgraph" / "single-file-token-benchmark"
    result_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    ledger_path = Path(os.environ.get(
        "RLMGRAPH_MODEL_CALL_LEDGER", result_dir / f"{run_id}.db"
    ))
    configure_model_call_ledger(ledger_path)
    rows: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="rlmgraph-single-file-benchmark-") as directory:
        root = Path(directory)
        target = root / "pricing.py"
        canary = "SECRET_FULL_FILE_CANARY_" + ("X" * 24_000)
        target.write_text(
            "def unrelated_reference_data():\n"
            f"    return {canary!r}\n\n"
            "def calculate_total(subtotal, tax_rate):\n"
            "    return subtotal\n",
            encoding="utf-8",
        )
        worker = CodexPlanImplementationWorker()

        iteration_limit = max(1, min(
            len(ITERATIONS), int(os.environ.get("RLMGRAPH_BENCHMARK_ITERATIONS", len(ITERATIONS)))
        ))
        for sequence, (task, acceptance) in enumerate(ITERATIONS[:iteration_limit], 1):
            full_source_before = target.read_text(encoding="utf-8")
            memory = ProjectSymbolMemory(root / "measurement-symbols.json")
            memory.refresh(root)
            context = memory.retrieve(task, project_root=root)
            context_json = json.dumps(context, separators=(",", ":"))
            if os.environ.get("RLMGRAPH_DUMP_PROMPT_ONLY") == "1":
                prompt, _ = worker.adapter.surgical_prompt(task, context)
                schema = json.dumps(_strict_output_schema(
                    SingleCallSurgicalResult.model_json_schema()
                ))
                print("--- EXACT CODEX STDIN BEGIN ---")
                print(prompt)
                print("--- EXACT CODEX STDIN END ---")
                print("--- EXACT OUTPUT SCHEMA BEGIN ---")
                print(schema)
                print("--- EXACT OUTPUT SCHEMA END ---")
                return 0
            canary_excluded = canary not in context_json
            with model_call_scope(
                benchmark_run_id=run_id,
                benchmark_arm="RLMGRAPH_SINGLE_FILE_SURGICAL",
                iteration=str(sequence),
            ):
                outcome = worker.implement(task, [], root)
            passed = bool(acceptance(_load_function(target)))
            rows.append({
                "iteration": sequence,
                "task": task,
                "passed": passed,
                "model_calls": outcome.model_calls,
                "files_changed": outcome.files_changed,
                "full_file_characters": len(full_source_before),
                "retrieved_symbol_characters": len(context_json),
                "estimated_full_file_tokens": estimate_tokens(full_source_before),
                "estimated_symbol_context_tokens": estimate_tokens(context_json),
                "canary_excluded": canary_excluded,
            })
            print(f"iteration {sequence}/{len(ITERATIONS)}: {'PASS' if passed else 'FAIL'}")

    with sqlite3.connect(ledger_path) as connection:
        calls = connection.execute(
            "SELECT input_tokens, output_tokens, token_source, latency_ms, status "
            "FROM model_calls WHERE json_extract(metadata, '$.benchmark_run_id') = ? "
            "ORDER BY occurred_at", (run_id,),
        ).fetchall()
    for row, call in zip(rows, calls, strict=True):
        row.update({
            "input_tokens": call[0], "output_tokens": call[1],
            "total_tokens": call[0] + call[1], "token_source": call[2],
            "latency_ms": round(call[3], 1), "call_status": call[4],
        })

    total_actual = sum(row["total_tokens"] for row in rows)
    full_file_floor = sum(row["estimated_full_file_tokens"] for row in rows)
    report = {
        "schema": "rlmgraph-single-file-token-benchmark-v1",
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "iterations": rows,
        "summary": {
            "iterations": len(rows),
            "passed": sum(row["passed"] for row in rows),
            "model_calls": len(calls),
            "provider_measured_calls": sum(row["token_source"] == "PROVIDER" for row in rows),
            "total_actual_tokens": total_actual,
            "average_actual_tokens": round(total_actual / len(rows), 1),
            "estimated_full_file_source_tokens_only": full_file_floor,
            "all_canaries_excluded": all(row["canary_excluded"] for row in rows),
        },
    }
    output = result_dir / f"{run_id}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (result_dir / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"report={output}")
    return 0 if report["summary"]["passed"] == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
