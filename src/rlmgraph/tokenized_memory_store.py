from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from .memory_tokenization import PersistentMemoryTokenIndex


class TokenizationMode(StrEnum):
    INLINE_RECORD = "INLINE_RECORD"
    SIDECAR_INDEX = "SIDECAR_INDEX"
    EMBEDDED_MODEL_STATE = "EMBEDDED_MODEL_STATE"


class TokenizedMemoryStore:
    """Required contract for every durable retrieval-memory implementation.

    Subclasses must explicitly declare where tokens, concepts, vectors, and lifecycle
    metadata persist. This makes omission visible at class creation and discoverable by CI.
    """

    tokenization_mode: ClassVar[TokenizationMode]
    tokenization_schema_version: ClassVar[int] = 1
    _registered_tokenized_stores: ClassVar[set[type]] = set()

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "tokenization_mode" not in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} must declare a tokenization_mode; durable memory cannot "
                "silently bypass tokenization and lifecycle policy."
            )
        mode = cls.__dict__["tokenization_mode"]
        if not isinstance(mode, TokenizationMode):
            raise TypeError(f"{cls.__name__}.tokenization_mode must be TokenizationMode.")
        TokenizedMemoryStore._registered_tokenized_stores.add(cls)

    @classmethod
    def tokenization_contract(cls) -> dict:
        return {
            "store": cls.__name__,
            "mode": cls.tokenization_mode.value,
            "schema_version": cls.tokenization_schema_version,
            "tokens": True,
            "concepts": True,
            "neural_vector": True,
            "importance": True,
            "access_tracking": True,
            "governed_release": True,
        }

    @staticmethod
    def token_index(memory_path: Path) -> PersistentMemoryTokenIndex:
        return PersistentMemoryTokenIndex(memory_path)

    @classmethod
    def registered_stores(cls) -> set[type]:
        return set(cls._registered_tokenized_stores)
