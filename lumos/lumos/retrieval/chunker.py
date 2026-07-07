from __future__ import annotations

import re


def chunk_text(text: str, target_size: int = 1_200, overlap: int = 160) -> list[str]:
    """Chunk text by paragraphs, with a bounded character overlap.

    Character-based chunking is intentionally dependency-free and predictable on
    low-resource machines. A tokenizer-aware strategy can replace this module later.
    """

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > target_size:
            if current:
                chunks.append(current.strip())
                current = ""
            step = max(1, target_size - overlap)
            for start in range(0, len(paragraph), step):
                piece = paragraph[start : start + target_size].strip()
                if piece:
                    chunks.append(piece)
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target_size:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
            tail = current[-overlap:].strip() if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
        else:
            current = paragraph

    if current:
        chunks.append(current.strip())

    return chunks
