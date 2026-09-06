import json
import subprocess
from pathlib import Path

import pytest

from rlmgraph.adapters import (
    CodexCliInvestigator,
    CodexCliResolver,
    CodexProjectIdeaSuggester,
    _stdout_event_trace,
    _usage_delta,
)
from rlmgraph.models import Assertion, Claim, Evidence, Task


def test_codex_jsonl_trace_exposes_command_activity_without_output_bodies() -> None:
    stdout = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
        json.dumps({"type": "item.completed", "item": {
            "type": "command_execution", "command": "Get-Content pricing.py",
            "status": "completed", "aggregated_output": "secret source body",
        }}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 10, "output_tokens": 2,
        }}),
    ])

    trace = _stdout_event_trace(stdout)

    assert trace["codex_command_count"] == 1
    assert trace["codex_thread_id"] == "thread-123"
    assert trace["codex_commands"] == ["Get-Content pricing.py"]
    assert trace["codex_exposed_tool_activity"] is True
    assert trace["codex_reported_usage_breakdown"] == {
        "input_tokens": 10, "output_tokens": 2,
    }
    assert "secret source body" not in json.dumps(trace)


def test_persistent_usage_delta_removes_prior_session_totals() -> None:
    assert _usage_delta(
        {"input_tokens": 199_513, "cached_input_tokens": 186_112, "output_tokens": 2_570},
        {"input_tokens": 122_141, "cached_input_tokens": 113_536, "output_tokens": 1_703},
    ) == {
        "input_tokens": 77_372,
        "cached_input_tokens": 72_576,
        "output_tokens": 867,
    }


def test_codex_cli_adapter_uses_read_only_structured_exec(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "conclusion": "The implementation subtracts a percentage as an amount.",
                    "evidence": [],
                    "confidence": 0.98,
                    "files_examined": ["widget.py"],
                    "files_changed": [],
                    "unresolved_questions": [],
                    "assertions": [
                        {
                            "key": "discounted_price.discount_percent.interpretation",
                            "value": "fixed amount",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)

    result = CodexCliInvestigator(sandbox="read-only").investigate("Why does it fail?", project)

    command = captured["command"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in command
    assert captured["kwargs"]["timeout"] == 900
    assert "Why does it fail?" in captured["kwargs"]["input"]
    assert "self-description is true" in captured["kwargs"]["input"]
    assert "evidence of stated intent, not proof" in captured["kwargs"]["input"]
    assert "contradicts the likely conclusion" in captured["kwargs"]["input"]
    assert command[-1] == "-"
    assert "assertions" in captured["schema"]["required"]
    assert result.assertions[0].value == "fixed amount"
    assert result.confidence == 0.98


def test_persistent_project_resume_preserves_unelevated_workspace_sandbox(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "rationale": "Updated the requested task.",
                    "confidence": 0.9,
                    "files_read": ["widget.py"],
                    "files_changed": ["widget.py"],
                    "model_calls": 1,
                }
            ),
            encoding="utf-8",
        )
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "session-123"}),
            json.dumps({
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }),
        ])
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)

    result, session_id = CodexCliInvestigator().persistent_project_turn(
        "Implement task two.", project, "session-123"
    )

    command = captured["command"]
    assert command[:3] == ["codex.cmd", "exec", "resume"]
    config_values = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--config"
    ]
    assert 'sandbox_mode="workspace-write"' in config_values
    assert "windows.sandbox=unelevated" in config_values
    assert "--sandbox" not in command
    assert command[-2:] == ["session-123", "-"]
    assert captured["kwargs"]["cwd"] == project
    assert result.files_changed == ["widget.py"]
    assert session_id == "session-123"


def test_codex_timeout_becomes_recoverable_timeout_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")
    monkeypatch.setattr(
        "rlmgraph.adapters.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("codex", kwargs["timeout"])
        ),
    )

    with pytest.raises(TimeoutError, match="12-second deadline"):
        CodexCliInvestigator(
            sandbox="read-only", investigation_timeout_seconds=12
        ).investigate("Why?", tmp_path)


def test_codex_resolver_receives_both_claims_and_evidence(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    captured: dict[str, object] = {}
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        captured["prompt"] = kwargs["input"]
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "selected_claim": "left",
                    "resolved_assertion": {"key": "widget.mode", "value": "percentage"},
                    "rationale": "The implementation multiplies by 0.01.",
                    "evidence": [
                        {"path": "widget.py", "detail": "Multiplies by 0.01", "line": 4}
                    ],
                    "confidence": 0.97,
                    "unresolved_questions": [],
                }
            ),
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)
    task = Task(
        question="Resolve widget.mode",
        fingerprint="task-fingerprint",
        project_fingerprint="project-fingerprint",
        project_root=str(project),
        disputed_assertion_key="widget.mode",
        conflicting_claim_ids=["CLAIM-left", "CLAIM-right"],
    )
    left = Claim(
        id="CLAIM-left",
        fingerprint="left",
        subject="left",
        producer="agent-left",
        conclusion="percentage",
        confidence=0.8,
        assertions=[Assertion(key="widget.mode", value="percentage")],
        evidence=[Evidence(path="widget.py", detail="multiplies", line=4)],
    )
    right = Claim(
        id="CLAIM-right",
        fingerprint="right",
        subject="right",
        producer="agent-right",
        conclusion="fixed amount",
        confidence=0.8,
        assertions=[Assertion(key="widget.mode", value="fixed amount")],
        evidence=[Evidence(path="test_widget.py", detail="returns 40", line=9)],
    )

    result = CodexCliResolver(sandbox="read-only").resolve(task, left, right, project)

    prompt = captured["prompt"]
    assert "CLAIM-left" in prompt and "CLAIM-right" in prompt
    assert "multiplies" in prompt and "returns 40" in prompt
    assert "widget.mode" in prompt
    assert "selected_claim" in captured["schema"]["required"]
    assert result.selected_claim == "left"


def test_evidence_gated_resolver_can_disable_repository_inspection(monkeypatch) -> None:
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    resolver = CodexCliResolver(sandbox="read-only", inspect_repository=False)

    assert resolver.inspect_repository is False


def test_codex_idea_suggester_uses_a_disposable_read_only_structured_mirror(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pricing.py").write_text(
        "def free_shipping(total):\n    return total >= 50\n", encoding="utf-8"
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr("rlmgraph.adapters.shutil.which", lambda executable: "codex.cmd")

    def fake_run(command, **kwargs):
        mirror = Path(command[command.index("--cd") + 1])
        captured["command"] = command
        captured["prompt"] = kwargs["input"]
        captured["mirror"] = mirror
        captured["source"] = (mirror / "pricing.py").read_text(encoding="utf-8")
        schema_path = Path(command[command.index("--output-schema") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "suggestions": [
                        {
                            "title": "Explain the shipping threshold",
                            "detail": "Expose the threshold in product language.",
                            "rationale": "The boundary currently exists only in code.",
                            "evidence": [
                                {
                                    "path": "pricing.py",
                                    "line": 2,
                                    "detail": "return total >= 50",
                                }
                            ],
                        }
                    ],
                    "files_examined": ["pricing.py"],
                    "confidence": 0.92,
                }
            ),
            encoding="utf-8",
        )
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("rlmgraph.adapters.subprocess.run", fake_run)
    worker = CodexProjectIdeaSuggester(model="fixture-model")
    result = worker.suggest(project, ["pricing.py"])

    command = captured["command"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command and "--ignore-rules" in command
    assert command[command.index("--model") + 1] == "fixture-model"
    assert Path(captured["mirror"]) != project
    assert captured["source"] == (project / "pricing.py").read_text(encoding="utf-8")
    assert "suggestions" in captured["schema"]["required"]
    assert "authorize no work" in captured["prompt"]
    assert result.suggestions[0].title == "Explain the shipping threshold"
    assert worker.last_authorized_paths == ["pricing.py"]
