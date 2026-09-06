import importlib
import inspect
import pkgutil

import pytest

import rlmgraph
from rlmgraph.tokenized_memory_store import TokenizationMode, TokenizedMemoryStore


def _durable_memory_classes():
    methods = {"remember", "records", "retrieve", "rank", "_save"}
    excluded_modules = {"memory_tokenization", "tokenized_memory_store"}
    found = []
    for module_info in pkgutil.iter_modules(rlmgraph.__path__):
        if "memory" not in module_info.name or module_info.name in excluded_modules:
            continue
        module = importlib.import_module(f"rlmgraph.{module_info.name}")
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module.__name__:
                continue
            if methods.intersection(candidate.__dict__):
                found.append(candidate)
    return found


def test_every_durable_memory_implementation_uses_tokenization_contract() -> None:
    discovered = _durable_memory_classes()

    assert discovered
    assert all(issubclass(store, TokenizedMemoryStore) for store in discovered), [
        store.__name__ for store in discovered
        if not issubclass(store, TokenizedMemoryStore)
    ]
    assert all(store.tokenization_contract()["concepts"] for store in discovered)
    assert all(store.tokenization_contract()["governed_release"] for store in discovered)


def test_new_store_cannot_omit_explicit_tokenization_mode() -> None:
    with pytest.raises(TypeError, match="must declare a tokenization_mode"):
        class InvalidMemoryStore(TokenizedMemoryStore):
            pass


def test_contract_rejects_untyped_mode() -> None:
    with pytest.raises(TypeError, match="must be TokenizationMode"):
        class InvalidModeMemoryStore(TokenizedMemoryStore):
            tokenization_mode = "SIDECAR_INDEX"


def test_valid_future_store_registers_automatically() -> None:
    class FutureMemoryStore(TokenizedMemoryStore):
        tokenization_mode = TokenizationMode.SIDECAR_INDEX

    assert FutureMemoryStore in TokenizedMemoryStore.registered_stores()
