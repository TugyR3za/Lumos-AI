# Archive

Nothing here is part of the running Lumos project. Kept for reference; safe to consult, not imported by anything.

- `claude-v0.1/` — the Claude-generated Lumos implementation, archived whole after the
  2026-07-06 merge audit. The canonical project (in `../lumos/`) is based on the other
  implementation; selected ideas from this tree (rich CLI, echo provider, graceful
  tool-round exhaustion, memory fact-injection) are planned to be ported in Phase 2.
  Its `rag/` package (Embedder/VectorStore interfaces, numpy store) is the reference
  design for semantic retrieval in v0.2.
- `build-artifacts/` — a stale wheel and checksum file built from the pre-merge source.
  Rebuild from `../lumos/` if a distributable package is ever needed.
