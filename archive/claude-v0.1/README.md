# Lumos

A private, modular personal AI system. Version 0.1 is the foundation: a chat
assistant with a provider router, SQLite memory, notes ingestion + retrieval
(RAG), web search, and a clean tool-calling loop. Every subsystem sits behind a
small interface so you can swap or extend it without touching the rest.

Built to run on modest hardware (tested against an 8GB-RAM / 4GB-VRAM target)
and to grow later into voice, a coding agent, computer use, and on-device models.

## What works in v0.1

- **Chat** via a terminal UI (`rich`) and a minimal web UI (`FastAPI`).
- **Provider router** — prefers a local model (Ollama), falls back to a cloud
  model (Groq), and finally to a built-in echo stub so it *always* runs.
- **Memory** — conversation history and long-term facts in a single SQLite file.
- **Notes / RAG** — drop `.md`/`.txt` files in `data/notes/`; they're chunked,
  embedded, and searchable. Real embeddings via Ollama's `nomic-embed-text`,
  with a zero-model hashing fallback so retrieval works before you install one.
- **Web search** — a `web_search` tool (Tavily) the model can call.
- **Tool-calling foundation** — a registry + loop that any provider can drive;
  adding a tool is one small class.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (optional) add keys for real answers + web search
cp .env.example .env        # then edit it

# 3. Run
python run.py               # terminal chat
python run.py web           # web UI at http://127.0.0.1:8000
python run.py reindex       # re-scan notes and exit
```

It runs with **zero setup** (echo provider + hashing embedder). To get real
answers, do either or both:

- **Local model (fully private):**
  ```bash
  # install Ollama from https://ollama.com, then:
  ollama pull qwen2.5:3b        # the assistant brain (try qwen2.5:1.5b if slow)
  ollama pull nomic-embed-text  # better note retrieval
  ```
- **Cloud fallback (higher quality):** set `GROQ_API_KEY` in `.env`
  (free tier at console.groq.com).

For web search, set `TAVILY_API_KEY` in `.env` (free tier at tavily.com).

## CLI commands

`/help` · `/status` · `/reindex [force]` · `/remember <text>` ·
`/model <ollama|groq|echo|auto>` · `/reset` · `/quit`

## Architecture

```text
run.py ─ launches CLI or web
   │
lumos/app.py ─ build_app(): wires everything from config (the one assembly point)
   │
   ├── core/assistant.py   the turn loop: context → model → tools → answer → memory
   ├── providers/          router + ollama / groq / echo  (interface: base.py)
   ├── memory/             sqlite_store                    (interface: base.py)
   ├── rag/                embedder · store · ingest · retriever (interfaces: base.py)
   ├── tools/              registry + web_search · search_notes  (interface: base.py)
   └── ui/                 cli (rich) · web (fastapi + static/index.html)
```

Design rules: each subsystem exposes an abstract base class; concrete
implementations are chosen in `app.py`; the `Assistant` depends only on the
interfaces. That's what makes pieces swappable.

## Extending it

- **New model backend** → subclass `providers.base.ChatProvider`, register it in
  `Router._build`.
- **New tool** → subclass `tools.base.Tool`, register it in `app.build_app`.
- **Swap the vector store** (e.g. Chroma) → implement `rag.base.VectorStore`.
- **Swap memory** (e.g. Postgres) → implement `memory.base.MemoryStore`.

## Roadmap (next versions)

- **0.2** — RAG improvements, project memory, source/citation tracking, streaming.
- **0.3** — family profiles + safety rules, fine-tuning pipeline.
- **0.4** — voice (STT/TTS, wake word), coding agent, MCP bridge.
- **1.0** — the full private family assistant with a safe self-improvement loop.

## Notes on privacy

Everything runs locally by default. The only data that leaves your machine is
what you explicitly send to a cloud provider (Groq) or search API (Tavily) —
and both are optional. Your notes, memory, and conversations stay in `data/`.
