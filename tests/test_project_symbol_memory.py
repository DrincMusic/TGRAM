from rlmgraph.project_symbol_memory import ProjectSymbolMemory


def test_symbol_memory_stores_addresses_not_bodies_and_retrieves_live_slice(tmp_path) -> None:
    canary = "SECRET_CANARY_OUTSIDE_TARGET"
    (tmp_path / "pricing.py").write_text(
        "import decimal\n\n"
        "def unrelated():\n"
        f"    return '{canary}'\n\n"
        "def calculate_total(items):\n"
        "    return sum(items)\n",
        encoding="utf-8",
    )
    memory = ProjectSymbolMemory(tmp_path / "symbol-memory.json")
    records = memory.refresh(tmp_path)

    stored = (tmp_path / "symbol-memory.json").read_text(encoding="utf-8")
    recalled = memory.retrieve("change calculate total", project_root=tmp_path, max_symbols=1)

    assert len(records) == 2
    assert "return sum(items)" not in stored
    assert recalled[0]["symbol"] == "calculate_total"
    assert "return sum(items)" in recalled[0]["source"]
    assert canary not in recalled[0]["source"]
