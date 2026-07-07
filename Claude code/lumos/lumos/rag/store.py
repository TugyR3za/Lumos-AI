"""A tiny, file-based vector store.

Holds vectors in a NumPy array and does exact cosine search. No server, no extra
service — ideal for a few thousand note chunks on a low-RAM machine. When your
corpus outgrows it, implement `VectorStore` with Chroma or pgvector and swap it
in via config; nothing else changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .base import Hit, VectorStore


class NumpyVectorStore(VectorStore):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._ids: list[str] = []
        self._meta: list[dict] = []
        self._vecs: np.ndarray | None = None
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = np.load(self.path, allow_pickle=True)
            self._vecs = data["vectors"]
            self._ids = list(data["ids"])
            self._meta = list(json.loads(str(data["meta"])))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.path,
            vectors=self._vecs if self._vecs is not None else np.zeros((0, 0)),
            ids=np.array(self._ids, dtype=object),
            meta=json.dumps(self._meta),
        )

    def add(self, ids, vectors, metadatas) -> None:
        arr = np.asarray(vectors, dtype=np.float32)
        # L2-normalize so dot product == cosine similarity.
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        arr = arr / norms
        self._vecs = arr if self._vecs is None else np.vstack([self._vecs, arr])
        self._ids.extend(ids)
        self._meta.extend(metadatas)
        self._save()

    def search(self, vector, k: int = 4) -> list[Hit]:
        if self._vecs is None or len(self._ids) == 0:
            return []
        q = np.asarray(vector, dtype=np.float32)
        n = np.linalg.norm(q) or 1.0
        q = q / n
        sims = self._vecs @ q
        top = np.argsort(-sims)[:k]
        return [
            Hit(
                id=self._ids[i],
                score=float(sims[i]),
                text=self._meta[i].get("text", ""),
                metadata=self._meta[i],
            )
            for i in top
        ]

    def clear(self) -> None:
        self._ids, self._meta, self._vecs = [], [], None
        if self.path.exists():
            self.path.unlink()

    def count(self) -> int:
        return len(self._ids)
