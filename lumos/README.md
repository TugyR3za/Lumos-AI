# Lumos v0.1

Lumos is a Python-first, private personal AI foundation. Version 0.1 focuses on a small, dependable core rather than an oversized framework:

- Clean local web chat UI
- Terminal CLI chat — the lightest option for weak machines
- Swappable provider router
- Ollama-first inference: Ollama Cloud by default (zero downloads), fully-local mode by config
- OpenRouter fallback (any OpenAI-compatible endpoint)
- Echo fallback so a fresh install always answers, even with no model yet
- SQLite conversation memory, plus saved personal memories injected as context
- Notes-folder ingestion and SQLite FTS5 retrieval
- Optional web search through DDGS or SearXNG
- Explicit, allowlisted tool-calling foundation
- No arbitrary shell, filesystem-write, or computer-control tools

## Architecture principles

1. **Ollama-first, light by default.** Auto routing tries the Ollama provider first — Ollama Cloud in the default configuration (no model downloads, minimal RAM), or a local Ollama when `LUMOS_OLLAMA_MODE=local` — and falls back to OpenRouter only on failure. Fully-private operation is one config switch away.
2. **Small interfaces.** Providers, search engines, retrieval, and tools are adapters that can be replaced independently.
3. **Low-resource defaults.** The core uses standard `sqlite3`, character-based chunking, FTS5 retrieval, and a dependency-free frontend.
4. **Private by default.** The server binds to `127.0.0.1`. Cloud and web features are opt-in per configuration/request.
5. **Safe extension path.** Models can invoke only functions registered in the tool allowlist.

## Requirements

- Python 3.11 or newer
- Optional: an ollama.com API key for Ollama Cloud (the default, download-free mode)
- Optional: an Ollama install for fully-local inference (`LUMOS_OLLAMA_MODE=local`)
- Optional: an OpenRouter (or other OpenAI-compatible) API key for fallback

## Quick start on Windows

```powershell
cd lumos
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add your Ollama Cloud key to `.env` (`LUMOS_OLLAMA_API_KEY=...`) — no model
downloads needed. Prefer everything on-device? See **Providers** below for
local mode instead.

Start Lumos (web UI):

```powershell
python -m lumos
```

Open `http://127.0.0.1:8000`. Or chat in the terminal instead — the lightest
option on a weak machine:

```powershell
python -m lumos cli
```

Both work before any key or model exists: the echo fallback answers with setup
instructions until a provider is configured.

## Quick start on macOS/Linux

```bash
cd lumos
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
cp .env.example .env     # then add LUMOS_OLLAMA_API_KEY (or configure local mode)
python -m lumos          # web UI
python -m lumos cli      # or terminal chat
```

## Terminal CLI

`python -m lumos cli` starts a chat in your terminal — no browser, no web
server, the lowest-RAM way to use Lumos. Slash commands:

| Command | Effect |
| --- | --- |
| `/help` | show all commands |
| `/status` | providers, web search, notes index, graph, and database |
| `/reindex` | rescan the notes folder |
| `/graph <note>` | links, tags, and related notes for a note path or slug |
| `/remember <text>` | save a durable personal memory |
| `/model auto\|local\|cloud` | provider route for this session |
| `/notes on\|off`, `/web on\|off` | toggle notes / web context |
| `/reset` | start a new conversation |
| `/quit` | exit |

`python -m lumos reindex` rebuilds the notes index and exits.

## Providers

**Primary — Ollama, in cloud or local mode.** All secrets come from `.env`;
nothing is hardcoded.

Cloud mode (default): zero downloads, near-zero local RAM. Create an API key in
your [ollama.com](https://ollama.com) account settings:

```dotenv
LUMOS_OLLAMA_MODE=cloud
LUMOS_OLLAMA_API_KEY=your-ollama-com-key
```

Local mode: fully private, everything on-device. Install Ollama, then:

```dotenv
LUMOS_OLLAMA_MODE=local
```

```powershell
ollama pull qwen3:1.7b
```

Blank `LUMOS_OLLAMA_MODEL` resolves per mode — `gpt-oss:20b` (cloud) or
`qwen3:1.7b` (local). `LUMOS_OLLAMA_BASE_URL` overrides the endpoint for
advanced setups (e.g. an Ollama server on your LAN).

**Fallback — OpenRouter, or any OpenAI-compatible endpoint.** Used in `auto`
routing only when the primary provider fails. No provider is created when the
key is blank:

```dotenv
LUMOS_CLOUD_API_KEY=your-openrouter-key
LUMOS_CLOUD_BASE_URL=https://openrouter.ai/api/v1
LUMOS_CLOUD_MODEL=openai/gpt-4o-mini
```

The adapter targets the common `/chat/completions` interface, so pointing
`LUMOS_CLOUD_BASE_URL` at OpenAI, Groq, or another compatible host also works.

Routing modes:

- `auto`: Ollama first, OpenRouter after an Ollama failure, echo fallback last
- `local`: force the Ollama provider (cloud or local mode); fails loudly
- `cloud`: force the OpenRouter fallback; fails loudly

Lumos v0.1 does not judge answer quality and silently resend a successful local answer to the cloud. That would increase privacy exposure and cost. A future router can add explicit task classification and user-approved escalation.

## Notes and retrieval

Put supported text or source files under `notes/`. Lumos indexes them on startup and when you click **Reindex notes folder**.

The current retrieval stack is:

```text
file -> UTF-8 text -> paragraph-aware chunks -> SQLite -> FTS5/BM25 search
```

This is intentionally lightweight. A future embedding retriever can implement the same retrieval interface without changing the chat agent or UI.

## Knowledge graph

Ingest also derives a graph from your notes: a node per note, per `#tag`, and per `[[wikilink]]` target that no note backs yet, joined by `links_to`, `tagged`, and `mentions` edges. It is written on every ingest, so it is always as current as the index.

Reading it is off by default:

```dotenv
LUMOS_GRAPH_ENABLED=true
```

With reads on, **◈ Graph** in the web header opens an ego view: find a note, then see what it links to, what links back, its tags, and the people or places it mentions. Every node is a link, so you can walk out from one note through a tag and into another. When an answer cites more than one note, **◈ Related notes** under its sources shows the notes one link away from all of them, ranked by how many of the cited notes reach each one — the expansion BM25 cannot make, since a linked note need not repeat the query's words.

The graph is read-only and answers-only for now: it changes what you can *see*, never what the model is *told*. Retrieval and prompts are untouched. `/graph <note>` gives the same one-hop view in the terminal, and `GET /api/graph` serves both.

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

Durable model-written memory is disabled by default until Lumos has an approval and review interface. Memories you save yourself (CLI `/remember`) are searched with FTS5 and injected into the model's context on every turn. Conversation history is always stored locally in SQLite.

## API endpoints

- `GET /api/health`
- `POST /api/chat`
- `GET /api/conversations/{conversation_id}`
- `POST /api/notes/reindex`
- `POST /api/search/notes`
- `POST /api/search/web`
- `GET /api/graph?slug=<node>` or `?path=<note>` (repeat `path` to seed related notes)
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
