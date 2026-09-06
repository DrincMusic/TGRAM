from types import SimpleNamespace

from rlmgraph.model_call_ledger import ModelCallLedger
from rlmgraph.project_goal_benchmark import (
    PairedProjectGoalBenchmark,
    ProjectGoalBenchmarkStore,
)


class FakeProjectWorker:
    def __init__(self, ledger: ModelCallLedger) -> None:
        self.ledger = ledger
        self.requests: list[str] = []
        self.adapter = self
        self.session_ids: list[str | None] = []
        self.forgotten_session_id: str | None = None

    def implement(self, request, evidence, sandbox_root):
        del evidence
        self.requests.append(request)
        baseline = "persistent Codex GPT-5.4 control session" in request
        self.ledger.record(
            role="implementation", operation="ProjectMilestone", provider="fixture",
            model="fixture", status="SUCCEEDED", latency_ms=1,
            input_tokens=100 if baseline else 50, output_tokens=10,
            token_source="PROVIDER",
        )
        (sandbox_root / "ledger.py").write_text(
            "import json, math\n"
            "class TransactionLedger:\n"
            "    def __init__(self): self.items=[]; self.refunded=set()\n"
            "    def __len__(self): return len(self.items)\n"
            "    def record(self, amount, category='general', note=''):\n"
            "        amount=float(amount); category=category.strip().lower()\n"
            "        if amount<=0 or not math.isfinite(amount) or not category: raise ValueError('invalid')\n"
            "        self.items.append({'id':len(self.items)+1,'amount':amount,'category':category,'note':note}); return len(self.items)\n"
            "    def refund(self, transaction_id):\n"
            "        if transaction_id<1 or transaction_id>len(self.items) or transaction_id in self.refunded: raise ValueError('invalid')\n"
            "        self.refunded.add(transaction_id); return len(self.refunded)\n"
            "    def total(self): return sum(x['amount'] for x in self.items if x['id'] not in self.refunded)\n"
            "    def get(self, transaction_id):\n"
            "        x=dict(self.items[transaction_id-1]); x['status']='REFUNDED' if transaction_id in self.refunded else 'ACTIVE'; return x\n"
            "    def transactions(self, include_refunded=True): return [self.get(x['id']) for x in self.items if include_refunded or x['id'] not in self.refunded]\n"
            "    def category_total(self, category): return sum(x['amount'] for x in self.items if x['category']==category.strip().lower() and x['id'] not in self.refunded)\n"
            "    def category_summary(self): return {c:self.category_total(c) for c in {x['category'] for x in self.items}}\n"
            "    def search(self, query): return [self.get(x['id']) for x in self.items if query.lower() in x['note'].lower()]\n"
            "    def summary(self): return {'transaction_count':len(self.items),'refund_count':len(self.refunded),'active_count':len(self.items)-len(self.refunded),'net_total':self.total()}\n"
            "    def export_data(self): return {'items':self.items,'refunded':list(self.refunded)}\n"
            "    @classmethod\n"
            "    def from_data(cls, data): obj=cls(); obj.items=data['items']; obj.refunded=set(data['refunded']); return obj\n"
            "    def to_json(self): return json.dumps(self.export_data())\n"
            "    @classmethod\n"
            "    def from_json(cls, payload): return cls.from_data(json.loads(payload))\n",
            encoding="utf-8",
        )
        (sandbox_root / "README.md").write_text(
            "record refund summary json category search\n", encoding="utf-8"
        )
        return SimpleNamespace(
            rationale="implemented", files_changed=["ledger.py"], confidence=1.0
        )

    def persistent_project_turn(self, request, project_root, session_id):
        self.session_ids.append(session_id)
        outcome = self.implement(request, [], project_root)
        return outcome, session_id or "persistent-session"

    def forget_persistent_session(self, session_id):
        self.forgotten_session_id = session_id


def test_project_goal_benchmark_compares_identical_copies_and_quality(tmp_path) -> None:
    ledger = ModelCallLedger(tmp_path / "calls.db")
    store = ProjectGoalBenchmarkStore(tmp_path / "project-runs.db")
    worker = FakeProjectWorker(ledger)
    benchmark = PairedProjectGoalBenchmark(worker, ledger, store, tmp_path / "runs")
    benchmark._validate = lambda root: {  # type: ignore[method-assign]
        f"criterion_{index}": True for index in range(1, 101)
    }

    result = benchmark.run()

    assert result["baseline_tokens"] == 11_000
    assert result["rlmgraph_tokens"] == 6_000
    assert result["tokens_saved"] == 5_000
    assert result["baseline"]["model_call_count"] == 100
    assert worker.session_ids[0] is None
    assert all(item == "persistent-session" for item in worker.session_ids[1:])
    assert worker.forgotten_session_id == "persistent-session"
    assert result["rlmgraph"]["model_call_count"] == 100
    assert len(result["rlmgraph"]["steps"]) == 100
    assert result["rlmgraph"]["steps"][0]["phase"] == "IMPLEMENT"
    assert result["memory_continuity"]["rlmgraph_workers_per_milestone"] == 1
    assert "TASK_PACKET=" in worker.requests[101]
    assert '"action":"implemented"' in worker.requests[101]
    assert "REQUIRED MILESTONES" not in worker.requests[101]
    memory_path = tmp_path / "runs" / result["id"] / "rlmgraph-action-memory.jsonl"
    assert len(memory_path.read_text(encoding="utf-8").splitlines()) == 100
    assert result["rlmgraph_archive"]["event_count"] == 300
    assert result["rlmgraph_archive"]["implicit_context_access"] is False
    assert max(
        step["compiled_context_characters"] for step in result["rlmgraph"]["steps"]
    ) <= 5000
    assert result["rlmgraph_task_control"]["progress"]["DONE"] == 100
    assert result["criteria_total"] == 100
    assert result["baseline"]["criteria_passed"] == 100
    assert result["rlmgraph"]["criteria_passed"] == 100
    assert result["quality_preserved"] is True
    assert result["project_roots"]["baseline"] != result["project_roots"]["rlmgraph"]
    assert store.latest()["id"] == result["id"]


def test_rlmgraph_autonomously_repairs_failed_acceptance(tmp_path) -> None:
    ledger = ModelCallLedger(tmp_path / "calls.db")
    store = ProjectGoalBenchmarkStore(tmp_path / "project-runs.db")

    class RepairingWorker:
        def __init__(self) -> None:
            self.requests: list[str] = []

        def implement(self, request, evidence, sandbox_root):
            del evidence
            self.requests.append(request)
            is_repair = '"phase":"REPAIR"' in request
            ledger.record(
                role="implementation", operation="ProjectMilestone", provider="fixture",
                model="fixture", status="SUCCEEDED", latency_ms=1,
                input_tokens=20, output_tokens=5, token_source="PROVIDER",
            )
            if is_repair:
                (sandbox_root / "repair-proof.txt").write_text(
                    "repaired", encoding="utf-8"
                )
            return SimpleNamespace(
                rationale="repaired failed acceptance" if is_repair else "initial attempt",
                files_changed=["repair-proof.txt"] if is_repair else [],
                confidence=1.0,
            )

    worker = RepairingWorker()
    benchmark = PairedProjectGoalBenchmark(worker, ledger, store, tmp_path / "runs")
    benchmark.arm_mode = "rlmgraph"
    benchmark.milestone_limit = 1
    benchmark._validate = lambda root: {  # type: ignore[method-assign]
        "mutated_contract": (root / "repair-proof.txt").exists()
    }

    result = benchmark.run()

    assert result["rlmgraph"]["criteria_passed"] == 1
    assert result["rlmgraph"]["model_call_count"] == 2
    assert [step["phase"] for step in result["rlmgraph"]["steps"]] == [
        "IMPLEMENT", "REPAIR",
    ]
    assert '"phase":"REPAIR"' in worker.requests[1]
    task = result["rlmgraph_task_control"]["tasks"][0]
    assert task["status"] == "DONE"
    assert task["evidence"][-1]["kind"] == "autonomous_repair"
    assert task["evidence"][-1]["passed"] is True
    repair_memory = (
        tmp_path / "runs" / result["id"] / "rlmgraph-repair-memory.jsonl"
    )
    persisted_repair = repair_memory.read_text(encoding="utf-8")
    assert '"verified": true' in persisted_repair
    assert '"criterion": "mutated_contract"' in persisted_repair
    assert result["rlmgraph_autonomous_repair"] == {
        "enabled": True,
        "max_attempts_per_failed_task": 2,
        "repair_model_calls": 1,
        "repaired_tasks": 1,
        "blocked_tasks": 0,
        "requires_deterministic_failure_evidence": True,
        "full_regression_validation_after_each_repair": True,
    }
