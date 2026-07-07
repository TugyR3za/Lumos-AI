from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.memory.database import Database
from app.retrieval.chunker import chunk_text

SUPPORTED_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".rs",
}


@dataclass(slots=True)
class IngestStats:
    scanned: int = 0
    indexed: int = 0
    skipped: int = 0
    removed: int = 0
    chunks: int = 0


class NotesIngestor:
    def __init__(
        self,
        database: Database,
        notes_root: Path,
        *,
        max_file_bytes: int,
        chunk_size_chars: int,
        chunk_overlap_chars: int,
    ) -> None:
        self.database = database
        self.notes_root = notes_root.resolve()
        self.max_file_bytes = max_file_bytes
        self.chunk_size_chars = chunk_size_chars
        self.chunk_overlap_chars = chunk_overlap_chars

    def ingest_all(self) -> IngestStats:
        stats = IngestStats()
        active_paths: set[str] = set()

        for path in self._iter_files():
            stats.scanned += 1
            relative = path.relative_to(self.notes_root).as_posix()

            try:
                file_stat = path.stat()
                if file_stat.st_size > self.max_file_bytes:
                    stats.skipped += 1
                    continue
                raw = path.read_bytes()
            except OSError:
                stats.skipped += 1
                continue

            digest = hashlib.sha256(raw).hexdigest()
            current = self.database.get_document_state(relative)
            if current and current["sha256"] == digest:
                active_paths.add(relative)
                stats.skipped += 1
                continue

            text = raw.decode("utf-8", errors="replace")
            chunks = chunk_text(
                text,
                target_size=self.chunk_size_chars,
                overlap=self.chunk_overlap_chars,
            )
            if not chunks:
                stats.skipped += 1
                continue

            active_paths.add(relative)
            count = self.database.replace_document(
                path=relative,
                title=path.stem.replace("_", " ").replace("-", " ").title(),
                sha256=digest,
                mtime_ns=file_stat.st_mtime_ns,
                chunks=chunks,
                metadata={"suffix": path.suffix.lower(), "size_bytes": file_stat.st_size},
            )
            stats.indexed += 1
            stats.chunks += count

        stats.removed = self.database.remove_documents_not_in(active_paths)
        return stats

    def _iter_files(self):
        for path in sorted(self.notes_root.rglob("*")):
            if not path.is_file():
                continue
            relative_parts = path.relative_to(self.notes_root).parts
            if any(part.startswith(".") for part in relative_parts):
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            yield path
