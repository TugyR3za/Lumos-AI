# Lumos v0.1 architecture

## Request path

```text
Browser UI
   |
FastAPI route
   |
AgentOrchestrator
   |-- SQLite conversation history
   |-- Notes retrieval (SQLite FTS5)
   |-- Optional proactive web search
   |-- ProviderRouter
   |      |-- OllamaProvider
   |      `-- OpenAICompatibleProvider
   `-- ToolRegistry
          |-- search_notes
          |-- search_web
          `-- optional save_memory
```

## Module boundaries

### `lumos/providers`

Normalizes model-specific request and response formats into `ProviderResponse` and `ToolCall`. The agent does not know whether a response came from Ollama or a cloud service.

### `lumos/memory`

Owns durable SQLite data: conversations, messages, indexed documents, chunks, and future long-term memories. It deliberately uses the standard library rather than an ORM to reduce startup cost and hidden behavior.

### `lumos/retrieval`

Owns chunking and retrieval. The current implementation is lexical FTS5/BM25. A future hybrid or embedding retriever should preserve the `search_notes(query, limit)` contract.

### `lumos/notes`

Scans a configured root, rejects unsupported or oversized files, hashes content, and incrementally replaces changed documents. It never indexes outside the configured notes root.

### `lumos/web`

Provides a tiny `search(query, limit)` interface. DDGS and SearXNG are current adapters. Search failures are isolated from normal chat unless the model critically depends on a search tool result.

### `lumos/tools`

Provides an explicit allowlist. A model can request only registered functions. New tools should have narrow schemas, bounded inputs, structured outputs, timeouts, and an approval policy for side effects.

### `lumos/agent`

Coordinates history, context, provider calls, and bounded tool loops. It does not directly query databases, HTTP endpoints, or the operating system except through injected services.

### `lumos/static`

A zero-build vanilla HTML/CSS/JavaScript client. It can later be replaced by a desktop, mobile, React, or native client because all behavior is exposed through JSON APIs.

## Storage model

- `conversations`: conversation identity and timestamps
- `messages`: user/assistant history and provider metadata
- `documents`: indexed note-file metadata and hashes
- `chunks`: source chunks
- `chunks_fts`: FTS5 search index
- `memories`: future durable personal facts
- `memories_fts`: future memory retrieval index

## Provider routing

`auto` is deliberately predictable:

1. Try local.
2. If the local request raises a provider error, try cloud.
3. Never resend a successful local request merely because the result might be lower quality.

Future routing can add explicit user-approved quality escalation, model capability metadata, token budgets, and task classifiers.
