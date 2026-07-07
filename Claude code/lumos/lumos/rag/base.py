"""RAG contracts: an Embedder turns text into vectors, a VectorStore holds them.

Both are swappable. Default embedder is Ollama's nomic-embed-text with a
no-model hashing fallback; default store is a small NumPy file. Upgrade to
Chroma/pgvector or a hosted embedding API by implementing these.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class Embedder(ABC):
    dim: int = 0

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


@dataclass
class Hit:
    """One retrieval result."""

    id: str
    score: float
    text: str
    metadata: dict


class VectorStore(ABC):
    @abstractmethod
    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        ...

    @abstractmethod
    def search(self, vector: list[float], k: int = 4) -> list[Hit]:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    @abstractmethod
    def count(self) -> int:
        ...
