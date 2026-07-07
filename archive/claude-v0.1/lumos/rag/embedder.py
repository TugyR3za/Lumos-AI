"""Two embedders.

OllamaEmbedder  — real semantic vectors via `nomic-embed-text` (~275MB, CPU-ok).
HashingEmbedder — no model at all: a deterministic bag-of-words hashing vector.
                  Lower quality, but means retrieval *always* works, even before
                  you've pulled an embedding model. Great for first-run + tests.

`get_embedder(config)` returns the best one available.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import requests

from .base import Embedder

_WORD = re.compile(r"[a-z0-9]+")


class OllamaEmbedder(Embedder):
    dim = 768  # nomic-embed-text

    def __init__(
        self,
        model: str = "nomic-embed-text",
        host: str = "http://localhost:11434",
        timeout: int = 60,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            if r.status_code != 200:
                return False
            names = [m.get("name", "") for m in r.json().get("models", [])]
            return any(self.model in n for n in names)
        except requests.RequestException:
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": t},
                timeout=self.timeout,
            )
            r.raise_for_status()
            out.append(r.json()["embedding"])
        return out


class HashingEmbedder(Embedder):
    """Feature-hashing bag of words. Zero dependencies beyond stdlib + math."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def is_available(self) -> bool:
        return True

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if (h >> 8) & 1 else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_embedder(config: Any) -> Embedder:
    """Prefer the real model; fall back to hashing so RAG never fully breaks."""
    host = config.get("providers.ollama.host", "http://localhost:11434")
    model = config.get("rag.embed_model", "nomic-embed-text")
    ollama = OllamaEmbedder(model=model, host=host)
    if ollama.is_available():
        return ollama
    return HashingEmbedder(dim=config.get("rag.hash_dim", 512))
