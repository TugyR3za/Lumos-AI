# Lumos v0.1

Lumos is a Python-first, private personal AI foundation. Version 0.1 focuses on a small, dependable core rather than an oversized framework:

- Clean local web chat UI
- Swappable provider router
- Ollama-first local inference
- OpenAI-compatible cloud fallback
- SQLite conversation memory
- Notes-folder ingestion and SQLite FTS5 retrieval
- Optional web search through DDGS or SearXNG
- Explicit, allowlisted tool-calling foundation
- No arbitrary shell, filesystem-write, or computer-control tools

## Architecture principles

1. **Local-first, cloud-capable.** Auto routing tries Ollama first and falls back to the configured cloud provider only if local inference fails.
2. **Small interfaces.** Providers, search engines, retrieval, and tools are adapters that can be replaced independently.
3. **Low-resource defaults.** The core uses standard `sqlite3`, character-based chunking, FTS5 retrieval, and a dependency-free frontend.
4. **Private by default.** The server binds to `127.0.0.1`. Cloud and web features are opt-in per configuration/request.
5. **Safe extension path.** Models can invoke only functions registered in the tool allowlist.

## Requirements

- Python 3.11 or newer
- Optional: Ollama for local inference
- Optional: an OpenAI-compatible API key for cloud fallback

## Quick start on Windows

```powershell
cd lumos
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Install Ollama, then pull a small model appropriate for your hardware:

```powershell
ollama pull qwen3:1.7b
```

Start Lumos:

```powershell
python -m lumos
```

Open `http://127.0.0.1:8000`.

## Quick start on macOS/Linux

```bash
cd lumos
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
cp .env.example .env
ollama pull qwen3:1.7b
python -m lumos
```

## Cloud fallback

Set these values in `.env`:

```dotenv
LUMOS_CLOUD_API_KEY=your-key
LUMOS_CLOUD_BASE_URL=https://api.openai.com/v1
LUMOS_CLOUD_MODEL=gpt-4.1-mini
```

The cloud adapter deliberately targets the common `/chat/completions` interface so it can be replaced by another compatible host. No cloud provider is created when the key is blank.

Routing modes:

- `auto`: local first, cloud only after a local provider error
- `local`: never use the cloud
- `cloud`: skip the local model

Lumos v0.1 does not judge answer quality and silently resend a successful local answer to the cloud. That would increase privacy exposure and cost. A future router can add explicit task classification and user-approved escalation.

## Notes and retrieval

Put supported text or source files under `notes/`. Lumos indexes them on startup and when you click **Reindex notes folder**.

The current retrieval stack is:

```text
file -> UTF-8 text -> paragraph-aware chunks -> SQLite -> FTS5/BM25 search
```

This is intentionally lightweight. A future embedding retriever can implement the same retrieval interface without changing the chat agent or UI.

## Web search

The default `auto` mode uses:

1. A configured SearXNG instance, or
2. The `ddgs` metasearch package.

Configure a private SearXNG instance with:

```dotenv
LUMOS_WEB_SEARCH_PROVIDER=searxng
LUMOS_SEARXNG_BASE_URL=http://127.0.0.1:8080
```

Web results are reference data, not trusted instructions. The system prompt explicitly tells the model to ignore instructions embedded in retrieved content.

## Tool calling

Current tools:

- `search_notes`
- `search_web`
- Optional `save_memory` when `LUMOS_ALLOW_MODEL_MEMORY_WRITES=true`

Durable model-written memory is disabled by default until Lumos has an approval and review interface. Conversation history is always stored locally in SQLite.

## API endpoints

- `GET /api/health`
- `POST /api/chat`
- `GET /api/conversations/{conversation_id}`
- `POST /api/notes/reindex`
- `POST /api/search/notes`
- `POST /api/search/web`
- `GET /docs` for generated OpenAPI documentation

## Development

```bash
pytest -q
ruff check .
ruff format .
```

See:

- `docs/architecture.md`
- `docs/extending.md`
- `docs/security.md`

## v0.1 boundaries

Not included yet:

- Authentication or separate family profiles
- Voice recognition or speech synthesis
- Embedding/vector retrieval
- Coding sandbox or terminal execution
- Browser/computer control
- Image/video/3D models
- Autonomous self-training
- Mobile/on-device client

Those are intentionally future modules. The v0.1 core establishes the interfaces they will plug into.
