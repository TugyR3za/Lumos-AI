"""Turn a folder of notes into searchable chunks.

Walks `data/notes/` for text files, splits them into overlapping chunks, embeds
each chunk, and stores it. A manifest of file hashes lets re-ingestion skip
unchanged files, so `/reindex` is cheap to run often.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import Embedder, VectorStore

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".text"}


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """Character-based chunking with overlap — simple and language-agnostic
    (works fine for English, Farsi, and Turkish alike)."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, start = [], 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def _file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class NotesIngestor:
    def __init__(
        self,
        notes_dir: str | Path,
        embedder: Embedder,
        store: VectorStore,
        manifest_path: str | Path | None = None,
    ) -> None:
        self.notes_dir = Path(notes_dir)
        self.embedder = embedder
        self.store = store
        self.manifest_path = Path(manifest_path) if manifest_path else (
            self.notes_dir.parent / "notes_manifest.json"
        )

    def _load_manifest(self) -> dict:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {}

    def _save_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2))

    def ingest(self, force: bool = False) -> dict:
        """Index new/changed notes. Returns a small summary dict."""
        manifest = {} if force else self._load_manifest()
        if force:
            self.store.clear()

        files = [
            p for p in self.notes_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS
        ]
        added_files = 0
        added_chunks = 0

        for path in files:
            rel = str(path.relative_to(self.notes_dir))
            h = _file_hash(path)
            if manifest.get(rel) == h:
                continue  # unchanged since last run

            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks = chunk_text(text)
            if not chunks:
                manifest[rel] = h
                continue

            vectors = self.embedder.embed(chunks)
            ids = [f"{rel}::{i}" for i in range(len(chunks))]
            metas = [
                {"text": c, "source": rel, "chunk": i}
                for i, c in enumerate(chunks)
            ]
            self.store.add(ids, vectors, metas)
            manifest[rel] = h
            added_files += 1
            added_chunks += len(chunks)

        self._save_manifest(manifest)
        return {
            "files_scanned": len(files),
            "files_indexed": added_files,
            "chunks_added": added_chunks,
            "total_chunks": self.store.count(),
            "embedder": self.embedder.__class__.__name__,
        }
