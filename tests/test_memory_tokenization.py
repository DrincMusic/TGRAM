import json

from rlmgraph.memory_tokenization import (
    PersistentMemoryTokenIndex,
    extract_memory_concepts,
    hashed_memory_vector,
    tokenize_memory,
)


def test_tokenization_extracts_concepts_and_stable_vector() -> None:
    text = "Walls support the upper floor; walls also support the roof."
    terms = tokenize_memory(text)
    concepts = extract_memory_concepts(text)

    assert {"walls", "support", "floor", "roof"}.issubset(terms)
    assert concepts[:2] == ("walls", "support")
    assert hashed_memory_vector(terms) == hashed_memory_vector(terms)


def test_index_persists_tokens_concepts_vector_and_lifecycle_metadata(tmp_path) -> None:
    source = tmp_path / "memory.jsonl"
    index = PersistentMemoryTokenIndex(source)
    index.remember("important", "verified physics support rule", importance=1, protected=True)
    index.remember("noise-a", "temporary irrelevant observation", importance=.1)
    index.remember("noise-b", "another disposable episode", importance=.2)

    released = index.release_unimportant(max_entries=2)
    persisted = json.loads(index.path.read_text(encoding="utf-8"))["entries"]

    assert released == ["noise-a"]
    assert "important" in persisted
    assert persisted["important"]["concepts"]
    assert len(persisted["important"]["vector"]) == 32
    assert persisted["important"]["protected"] is True
