# Lumos Project Recovery Audit

**Audit date:** 2026-09-16. **Repository:** `D:\Projects\Lumos AI` (git). **Branch inspected:** `feature/graph-v1` (13 commits ahead of `main`, fully pushed to `origin` — nothing local is unpushed). **Working tree:** clean, no uncommitted changes. **Last commit:** `12543ee`, 2026-07-13. **Development window:** 2026-07-06 → 2026-07-13 (one intense week), then roughly two months of no activity up to today.

## 1. Executive summary

**What Lumos currently is.** A small, working, single-user/family FastAPI + SQLite Python application (package `lumos`, ~3,800 lines of source under `lumos/lumos/`) that provides: a web chat UI, a terminal CLI, a provider router (Ollama Cloud/local → OpenRouter/OpenAI-compatible → built-in "echo" fallback), SQLite-backed conversation memory and durable "remembered" facts, FTS5 keyword search over a local notes folder, a derived knowledge graph (wikilinks/tags) with a read-only browsing UI and an opt-in retrieval-expansion feature, optional web search (DDGS/SearXNG), and a narrow, explicit tool-calling allowlist (`search_notes`, `search_web`, optional `save_memory`). It has **165 passing automated tests** and a custom evaluation harness that measures its own retrieval and answer quality rather than just asserting success.

**What it appears to have been intended to become**, per the project vision supplied for this audit and per the archived `claude-v0.1` tree and `docs/*.md`: a private, local-first "second brain" with its own trained language model, continual controlled learning, a visual knowledge/work graph, versioned datasets/checkpoints, and a broader agent framework with planning and approval gates. The current repository is explicit and self-aware about this gap — its own README lists "Not included yet" (`lumos/README.md:276-289`) and `docs/extending.md` sketches future modules rather than implementing them.

**Maturity level: a working single-user prototype / small MVP for the "chat + notes + provider routing" slice only.** It is not a scaffold in the pejorative sense — the code that exists is tested, disciplined, and runs — but it covers a small fraction of the long-term vision. There is **zero code anywhere in the repository** for tokenization, transformer architectures, training loops, checkpoints, embeddings/vector search, task/work-graph visualization, authentication, or multi-user access. These are entirely unimplemented, not partially implemented.

**The most important truth about the current state:** Lumos today is a well-engineered **API-routing chat application with lexical (BM25) notes retrieval and a lightweight knowledge graph** — not yet a personal AI with any owned model, not yet a second brain with editing/versioning, and not yet an agent framework with planning/approval. Every "intelligence" behavior currently comes from Ollama Cloud, a local Ollama model, or OpenRouter — i.e., from other people's models. That is explicitly acknowledged in the code/docs and must not be described otherwise.

**The three most valuable next actions** (elaborated in §14–15):
1. **Give the existing tool/agent loop real teeth and visibility** — surface `tool_events` in both UIs (currently computed but not shown, §12), and treat this as the seed of the "auditable agent" vision rather than starting a new framework from scratch.
2. **Start the first training-lab milestone as an isolated module** (tokenizer + ~1M-parameter decoder-only transformer + tiny dataset + train/eval loop), deliberately kept separate from the FastAPI app, so "Lumos's own brain" work can begin without destabilizing the working chat product.
3. **Decide and record the memory/second-brain roadmap** (embeddings vs. staying lexical, note-editing in-app vs. external-vault-only, versioning strategy) before adding more surface area — several of the biggest open questions (§ "Questions/Unknowns") are architectural forks that get more expensive to change the longer they're deferred.

---

## 2. Repository map

Legend for **Status**: `WORKING` (runs, is exercised by passing tests, and/or I executed it this session), `PARTIAL` (real code, but incomplete relative to its own stated goal), `SCAFFOLD` (interface/shape exists, no real behavior), `UNVERIFIED` (plausible from reading, not executed), `OBSOLETE` (superseded, kept for reference only), `MISSING` (not present).

| Path | Purpose | Key symbols | Status | Evidence |
|---|---|---|---|---|
| `lumos/README.md` | Product doc, quick start, provider/retrieval/graph explanation | — | WORKING (doc matches code) | Cross-checked every claim against source; all matched (see §3–§6) |
| `lumos/pyproject.toml` | Package metadata, deps, tool config | deps: fastapi, uvicorn, httpx, pydantic-settings, ddgs, rich; dev: pytest, ruff, mypy | WORKING | Installed in `.venv`; `pytest`/`ruff` ran successfully |
| `lumos/Makefile` | Dev shortcuts | `install run cli reindex test lint format eval eval-answers` | WORKING | Targets map 1:1 to real commands I verified |
| `lumos/docs/architecture.md` | Request-path & module-boundary doc | — | WORKING (accurate) | Matches `container.py`/`orchestrator.py` exactly |
| `lumos/docs/extending.md` | How to add providers/retrieval/tools; sketches voice, coding-sandbox, computer-use, on-device modules | — | PLANNED (doc only) | No corresponding code exists for voice/coding/computer-use |
| `lumos/docs/security.md` | Honest current-protections/limitations list | — | WORKING (accurate) | Confirmed: no auth, binds 127.0.0.1, no shell tool, etc. |
| `lumos/.env.example` | All config knobs, documented inline | — | WORKING | Matches `config.py` field-for-field |
| `lumos/lumos/__main__.py` | CLI launcher / mode dispatch | `main()`, `_run_web()`, `_run_reindex()` | WORKING | `python -m lumos [web\|cli\|reindex\|help]` |
| `lumos/lumos/main.py` | FastAPI app + lifespan | `app`, `lifespan()` | WORKING | Mounts `/static`, includes API router, serves `index.html` |
| `lumos/lumos/cli.py` | Terminal chat UI | `run()`, `handle_command()`, `chat_once()`, `status_summary()` | WORKING | Exercised end-to-end by `tests/test_cli.py` (8 tests) |
| `lumos/lumos/config.py` | `pydantic-settings` Settings, env-anchored paths | `Settings`, `get_settings()` | WORKING | All fields verified against `.env.example` and callers |
| `lumos/lumos/schemas.py` | Pydantic request/response models | `ChatRequest/Response`, `GraphResponse`, `HealthResponse` | WORKING | Used by both `api/routes.py` and `cli.py` |
| `lumos/lumos/core/container.py` | Manual DI: wires DB, providers, retrieval, graph, tools, agent | `LumosContainer`, `build_container()` | WORKING | Single composition root; no framework, just a dataclass |
| `lumos/lumos/core/logging.py`, `core/time.py` | Logging setup, UTC timestamp helper | `configure_logging()`, `utc_now_iso()` | WORKING | Trivial, correct |
| `lumos/lumos/agent/orchestrator.py` | The "agent": retrieval → prompt → provider → bounded tool loop → persist | `AgentOrchestrator.chat()` | WORKING | Covered by `tests/test_orchestrator.py` (9 tests) |
| `lumos/lumos/agent/prompts.py` | System prompt assembly | `build_system_prompt()` | WORKING | — |
| `lumos/lumos/providers/{base,router,ollama,openai_compatible,echo}.py` | Provider protocol + 3 concrete providers + router | `ChatProvider`, `ProviderRouter`, `OllamaProvider`, `OpenAICompatibleProvider`, `EchoProvider` | WORKING | `tests/test_router.py` (8), `test_provider_checks.py` (12), `test_provider_config.py` (8) — all use `httpx.MockTransport`, no real network |
| `lumos/lumos/memory/database.py` | All SQLite schema + queries (conversations, messages, documents, chunks, memories, FTS5) | `Database` | WORKING | `tests/test_database.py`, `test_memory_relevance.py` |
| `lumos/lumos/notes/ingestor.py` | Filesystem scan → hash → chunk → index | `NotesIngestor.ingest_all()` | WORKING | `tests/test_ingestor.py` |
| `lumos/lumos/retrieval/{chunker,relevance,service}.py` | Paragraph chunking, stopword/floor relevance rules, BM25 search + graph-linked-note expansion | `chunk_text()`, `search_terms()`, `above_floor()`, `RetrievalService` | WORKING | `tests/test_chunker.py`, `test_relevance.py` (11), `test_retrieval_expansion.py` (17) |
| `lumos/lumos/graph/{extract,store,service}.py` | Deterministic `[[wikilink]]`/`#tag` extraction, SQLite graph persistence, read-only graph queries | `extract_refs()`, `sync_note()`, `GraphService` | WORKING | `test_graph_extract.py` (16), `test_graph_ingest.py` (12), `test_graph_service.py` (14), `test_graph_api.py` (8) |
| `lumos/lumos/tools/{registry,builtin}.py` | Explicit tool allowlist + 2–3 concrete tools | `ToolRegistry`, `build_tool_registry()` | WORKING | `tests/test_tools.py` |
| `lumos/lumos/web/{base,service,ddgs_provider,searxng}.py` | Web search abstraction + 2 adapters | `WebSearchService`, `DDGSSearchProvider`, `SearxNGSearchProvider` | WORKING (DDGS), UNVERIFIED (SearXNG live) | No test exercises a live SearXNG instance; DDGS depends on an installed package, not mocked in tests |
| `lumos/lumos/api/routes.py` | 7 REST endpoints | `/health /chat /conversations/{id} /notes/reindex /search/notes /search/web /graph` | WORKING | Exercised indirectly via CLI tests reusing the same container; no dedicated `TestClient` HTTP test file found for most routes except graph (`test_graph_api.py`) |
| `lumos/lumos/static/{index.html,app.js,styles.css}` | Vanilla JS/CSS chat + graph-drawer frontend | `sendMessage()`, graph drawer functions | WORKING (code-complete), UNVERIFIED (not exercised in a browser this session) | No JS tests exist; logic read and is internally consistent with the API schemas |
| `lumos/evals/` | Custom retrieval+answer eval harness and 32-note corpus | `harness.py`, `run_eval.py`, `evals/notes/*`, `questions.json` | WORKING | I ran `python -m evals.run_eval`; reproduced README's exact numbers (30/30, 18 rescued, 6/6 multi-note) |
| `lumos/tests/*.py` (17 files) | Unit/integration tests, no network | 165 tests | WORKING | I ran `pytest -q`: **165 passed**, 0 failed |
| `lumos/notes/` | User's live notes folder | only `README.md` | EMPTY | No user notes have been added yet in this checkout |
| `lumos/data/lumos.db` (+ `.bak`) | Live runtime SQLite DB | — | EXISTS, not inspected (privacy) | Gitignored; ~280KB, implies some manual testing occurred |
| `archive/` | Explicitly non-running reference code | — | OBSOLETE (by design) | `archive/README.md:1` states "Nothing here is part of the running Lumos project" |
| `archive/claude-v0.1/` | A second, earlier full implementation (assistant/router/RAG/tools/CLI/web) | `Assistant`, `Router`, `Embedder`/`VectorStore`, `SQLiteMemory`, `WebSearchTool` (Tavily) | OBSOLETE, reference-only | Confirms an embeddings/vector-store design exists as prior art (see §6, §9) |
| `archive/build-artifacts/` | Stale prebuilt wheel | — | OBSOLETE | `archive/README.md:11` calls it stale |
| *(nowhere)* | Tokenizer, transformer, training loop, checkpoints, model registry, vector DB, auth, work-graph UI | — | **MISSING** | Exhaustive `find`/`grep` across `lumos/` and `archive/` found none |

---

## 3. What is implemented

### Fully implemented and tested

**Provider routing (auto/local/cloud with graceful degradation).**
- Behavior: `ProviderRouter._ordered()` (`lumos/lumos/providers/router.py:51-75`) builds an ordered provider list — primary (Ollama) → fallback (OpenAI-compatible) → echo — for `auto`, or forces a single provider for `local`/`cloud`, raising `ProviderError` if that slot isn't configured.
- Paths: `providers/{base,router,ollama,openai_compatible,echo}.py`.
- Tested: yes, 28 tests across `test_router.py`, `test_provider_checks.py`, `test_provider_config.py`, all against `httpx.MockTransport` (no live network).
- Runnable: yes — confirmed via the full test suite and via `evals/run_eval.py` which builds real containers.
- Config needed: none to boot (echo fallback always available); `.env` keys needed for real model output.
- Limitations: only two real model backends (Ollama-wire and OpenAI-`/chat/completions`-wire); no capability-based or quality-based routing (`docs/architecture.md:78` calls this out as future work) — no request ever silently escalates from local to cloud.

**Conversation memory + durable "remembered" facts (SQLite).**
- Behavior: every turn is persisted (`memory/database.py: add_message`, `get_messages`); user-invoked `/remember` (CLI) or a gated `save_memory` tool writes to a `memories` table with its own FTS5 index and a stricter relevance floor (0.50 vs. notes' 0.40) so recalled memories are conservative (`memory/database.py:412-473`).
- Tested: `test_database.py`, `test_memory_relevance.py` (9 tests).
- Runnable: yes.
- Limitations: memory is a flat list of strings with an optional key/importance/source — no structured schema, no linking to the knowledge graph, no UI to browse/edit/delete memories (deletion/export are only possible by directly editing the SQLite file).

**Notes ingestion + FTS5 lexical retrieval, with an honest relevance model.**
- Behavior: scans `notes/`, skips hidden/oversized/unsupported files, hashes content (`notes/ingestor.py:59-121`), chunks paragraph-aware with overlap (`retrieval/chunker.py`), indexes into SQLite FTS5 (`porter unicode61` tokenizer), and applies two deliberate relevance rules before anything is shown or sent to a model: stopword-aware term extraction and a "hold its own against the best hit" score floor (`retrieval/relevance.py`).
- Tested: `test_chunker.py`, `test_relevance.py` (11), `test_ingestor.py`, `test_database.py`.
- Runnable: yes, verified this session.
- Limitations: purely lexical (BM25 via SQLite's `bm25()`), English-tuned stopword list, no semantic/embedding retrieval (see §5, §6, §9 for the gap and the reference design already sitting in `archive/`).

**Deterministic knowledge graph over notes (Graph V1).**
- Behavior: at ingest time, `graph/extract.py` pulls `[[wikilinks]]`, `#tags`, and whitelisted frontmatter (`tags`/`aliases`) out of Markdown notes only (code files are excluded), producing nodes (`note`/`tag`/`entity`) and edges (`links_to`/`mentions`/`tagged`) in dedicated SQLite tables (`graph/store.py`). Entity nodes upgrade to note nodes (and incoming edges flip `mentions`→`links_to`) when a matching note is later ingested, and the reverse happens on deletion (`graph/store.py:108-133, 305-338`).
- Reading is a separate, off-by-default flag (`LUMOS_GRAPH_ENABLED`) from writing (which always happens) — a deliberate, well-documented design decision (`config.py:66-70`).
- Retrieval expansion (`LUMOS_GRAPH_EXPAND_RETRIEVAL`) is a *third*, independently-gated behavior: BM25 hits become seeds, and notes one `links_to` hop away are appended (never displace search hits) under hard caps (`graph_expand_max_notes=3`, `graph_expand_max_chars=800`) (`retrieval/service.py:66-114`).
- Tested: 50 tests across `test_graph_extract.py`, `test_graph_ingest.py`, `test_graph_service.py`, `test_graph_api.py`, `test_retrieval_expansion.py`.
- Runnable: yes — I ran the retrieval eval myself (below) and reproduced the documented numbers exactly.
- Limitations: **read-only** (no way to create/edit graph nodes or edges from the app — the graph is entirely derived from note text); only one edge type (`links_to`) is ever traversed for expansion, by design, to avoid hub explosion; the web "graph" UI is a **list-based ego view in a side drawer**, not a rendered node-link diagram (no SVG/canvas/force-directed layout exists anywhere in `static/app.js` or `styles.css`) — this is a meaningfully weaker claim than "visual knowledge graph."

**Custom evaluation harness (not just unit tests) for the graph feature.**
- Behavior: two tiers — a deterministic, model-free retrieval-completeness check (did every note an answer needs reach the model?), and an optional model-in-the-loop answer check using planted "canary" facts, run `--repeat` times per question to treat model variance as a rate rather than a single sample (`evals/harness.py`). It explicitly refuses to report answer numbers if the echo fallback answers (`NoModel` exception, `evals/harness.py:39-41, 341-347`), and it validates its own corpus's premises (`test_eval_corpus.py`, 8 tests) so a bad question can't manufacture a good-looking result.
- **I executed this myself this session**: `python -m evals.run_eval` → **12/30 (40%) reachable by BM25 alone, 30/30 (100%) with the graph, 18 questions rescued, 0 short of a note, 1/6 → 6/6 on multi-note questions** — an exact match to the numbers documented in `lumos/evals/README.md:110-118`. This is strong, first-hand evidence that the graph-expansion feature genuinely works as claimed, not just as documented.

**CLI (`python -m lumos cli`) and Web UI (`python -m lumos` / `python -m lumos web`).**
- See §4 and §8 for full detail. Both are thin clients over the same `AgentOrchestrator`/`LumosContainer`, so behavior is consistent between them by construction, not by convention.

**Test suite.**
- 165 tests, **I ran them and all 165 passed** (`pytest -q`, 8.65s, no network, no external services). `ruff check .` also passes cleanly with zero findings.

### Partially implemented

**Tool calling / "agent" loop.** A real, bounded tool loop exists (`agent/orchestrator.py:125-176`, max 3 rounds via `max_tool_rounds`, falls back to a tools-off final call if the budget is exhausted rather than erroring) with three tools: `search_notes`, `search_web`, and an optional gated `save_memory`. This is a genuine, working implementation of *tool calling* — but it is not the fuller "agent" the project vision describes (§7): there is no explicit plan object, no user approval gate before any tool executes, and — concretely — **the `tool_events` the orchestrator already computes and returns in every `ChatResponse` (`schemas.py:24-31`) are never displayed by either the CLI (`cli.py:219-225`, `_print_response` only prints answer + up to 4 sources) or the web UI (`static/app.js` renders `sources` but never reads `data.tool_events`)**. The audit trail exists in the database (`messages.metadata_json`) but is invisible to the user in both current interfaces.

**Web search.** DDGS is a real, working default (no config needed) confirmed by code (not by a live network call this session, to avoid an uncontrolled external request). SearXNG is a complete adapter but requires a self-hosted instance the auditor has no way to verify is running; neither path has a dedicated automated test with a mocked transport (unlike the model providers). Proactive web search is wrapped in a `try/except` so a search failure never breaks a chat turn (`orchestrator.py:86-93`), which is good defensive design, but it also means a silently-broken web search adapter would be very hard for the user to notice outside of `/status`.

**Provider `check()`/status reporting.** Deliberately honest and nuanced (`ollama.py:64-91`, `openai_compatible.py:56-81`) — e.g. it knows ollama.com cannot verify an API key via a cheap GET, so it reports `reachable` (not `available`) until a real chat succeeds, and remembers auth failures as sticky until the next successful chat. This is a genuinely mature piece of engineering for something as small as a status line, but it is inherently a best-effort heuristic, not a guarantee.

---

## 4. CLI audit

**Entry point:** `python -m lumos cli` → `lumos/lumos/cli.py:run()`. Also reachable via `python -m lumos` (defaults to `web`) and `python -m lumos reindex` (one-shot, no chat loop) from `lumos/lumos/__main__.py:41-55`.

### Commands (all in `cli.py:34-203`)

| Command | Arguments | What it actually does | Source | Status |
|---|---|---|---|---|
| `/help` | none | Prints the static `HELP` string | `cli.py:34-46` | WORKING |
| `/status` | none | Calls `status_summary()`: provider states, web-search availability, DB row counts, graph enabled/counts, DB path, notes path | `cli.py:57-112` | WORKING, tested |
| `/reindex` | none | `container.ingestor.ingest_all()`, prints scanned/indexed/skipped/removed/chunks | `cli.py:168-174` | WORKING, tested |
| `/graph <note>` | note path or slug | One-hop neighbor table + "related notes" footer; prints `GRAPH_DISABLED_DETAIL` if graph reads are off | `cli.py:118-152` | WORKING, tested (incl. disabled-by-default case) |
| `/remember <text>` | free text | `database.save_memory(text, source="user_cli")`, returns the new memory id | `cli.py:179-185` | WORKING, tested |
| `/model auto\|local\|cloud` | one of three | Sets `state.route` for subsequent turns only (not persisted) | `cli.py:186-190` | WORKING |
| `/notes on\|off`, `/web on\|off` | `on`/`off` | Toggles whether retrieval/web-search context is gathered this session | `cli.py:191-199` | WORKING |
| `/reset` | none | Clears `state.conversation_id` (next turn starts a fresh conversation row) | `cli.py:200-202` | WORKING |
| `/quit` (or `/exit`) | none | Returns sentinel `QUIT`, exits the loop | `cli.py:162-163` | WORKING |
| *(bare text)* | — | `chat_once()` → `AgentOrchestrator.chat()`, prints answer, provider/model, up to 4 sources | `cli.py:206-225` | WORKING — **does not print `tool_events`** even when tools fired |

**Environment variables consumed:** all `LUMOS_*` settings in `.env` (see `config.py`); the CLI itself reads none directly — it goes through `get_settings()`/`build_container()`, identical to the web app.

**Expected user flow:** `pip install -e ".[dev]"` → copy `.env.example` to `.env` → optionally add a key → `python -m lumos cli` → notes auto-index on startup (if `LUMOS_INGEST_NOTES_ON_STARTUP=true`, default) → free chat, with slash commands for housekeeping.

**Documented-but-missing commands:** none found — every command in `README.md:79-92`'s table exists in code and matches the behavior described. This is a repository where the docs are unusually accurate.

**Commands that exist but are incomplete/misleading:**
- None are *broken*. The one real gap is transparency, not correctness: tool calls happen, are stored, but are not shown to the CLI user (see §3, §12).
- `/model` changes routing but not which provider is actually reachable — a user can set `/model local` with no Ollama configured and get a clear `ProviderError` (by design, `router.py:52-57`), which is correct behavior, just worth knowing before testing.

**Recommended first smoke-test sequence** (all safe, local, no keys required — I have verified steps 1–3 myself this session):
```bash
cd lumos
pip install -e ".[dev]"          # already done in this checkout (.venv exists)
pytest -q                        # I ran this: 165 passed
python -m evals.run_eval         # I ran this: reproduces README's graph numbers exactly
python -m lumos cli              # NOT run this session — starts an interactive loop
  # at the prompt: /status  → expect echo-only, 0 documents (empty notes/ folder)
  # type any message         → expect the echo-fallback canned reply, since no LUMOS_*_API_KEY is set
  # /remember I like tea      → expect "Saved memory #1."
  # /quit
```
I did not run `python -m lumos cli` or `python -m lumos` (web) interactively this session because both start long-lived/interactive processes; their behavior is instead evidenced by `test_cli.py` (8 tests, exercising `handle_command`/`chat_once`/`status_summary` directly against a real container) and by reading the code.

---

## 5. Model and provider audit

- **Does Lumos have a trainable model implementation?** **No.** There is no tokenizer, no model-architecture code, no training loop, no checkpoint format, no dataset pipeline, and no model registry anywhere in `lumos/` or `archive/`. This was confirmed by a full-repository search for training-related code and file trees; none exists.
- **Model providers today are exclusively external/local *inference* APIs, plus one placeholder:**
  - `OllamaProvider` (`providers/ollama.py`) — speaks Ollama's `/api/chat` wire protocol against either a local Ollama install (`LUMOS_OLLAMA_MODE=local`, fully private, requires the user to `ollama pull` a model) or Ollama Cloud (`LUMOS_OLLAMA_MODE=cloud`, the default — a *hosted, non-Lumos-owned* model reached over the internet with an API key). This is the "primary" slot.
  - `OpenAICompatibleProvider` (`providers/openai_compatible.py`) — generic `/chat/completions` adapter, defaulting to OpenRouter. This is the "fallback" slot, disabled unless a key is set.
  - `EchoProvider` (`providers/echo.py`) — a canned, non-AI responder used only as a last resort in `auto` routing so a fresh install always answers something.
- **Ollama/local path:** complete and working for both sub-modes (cloud and local share one adapter because the wire protocol matches; `ollama.py:22-27`). This is the most "local-first" path available today, but "local Ollama" still means running someone else's pretrained model (e.g. `qwen3:1.7b`) via Ollama's runtime — it is **not** a Lumos-trained model.
- **OpenAI-compatible path:** complete, generic, and intentionally not SDK-coupled (`openai_compatible.py:30-35`); works against OpenRouter, OpenAI, Groq, or any compatible host.
- **Routing/fallback:** implemented, deliberately simple and predictable (`ProviderRouter`, §3), with no quality-based escalation by design (`architecture.md:70-78` and `README.md:141` state this explicitly as a *future* item, and correctly frame it as a privacy/cost tradeoff rather than an oversight).
- **Conflict with the "own trained model" goal:** the current architecture does **not conflict** with eventually adding a Lumos-owned model — the `ChatProvider` protocol (`providers/base.py:55-65`, three async methods: `check`/`chat`, plus `name`/`model` attributes) is narrow and would accept a fourth provider that wraps a locally-run Lumos checkpoint with no changes to the orchestrator, router, or UI. This is a genuine architectural strength worth preserving.
- **Critical distinction to keep making explicitly in all future documentation and conversation:** "Lumos routes to Ollama/OpenRouter" is **provider integration**, not "Lumos has learned/trained a model." Nothing in the current code trains, fine-tunes, or updates any model weights. All "learning" that exists is retrieval (notes/graph) and explicit user-authored memory — i.e., context assembly, not weight update. This must not be conflated in status reporting to the user.

---

## 6. Memory, second brain, and retrieval audit

| Area | Status | Evidence |
|---|---|---|
| Conversations | **IMPLEMENTED** | `memory/database.py:44-62, 137-196` — `conversations`/`messages` tables, full CRUD used by both UIs |
| Durable user memories | **IMPLEMENTED** (basic) | `memories`/`memories_fts` tables (`database.py:87-99, 385-473`); CLI `/remember`; optional model-initiated `save_memory` tool (off by default) |
| Notes | **IMPLEMENTED** (read-only ingestion) | `notes/ingestor.py`; no in-app note creation/editing — notes are authored externally |
| Database schema/storage | **IMPLEMENTED** | Plain `sqlite3`, WAL mode, foreign keys on (`database.py:24-38`); no ORM, deliberately (`architecture.md:34`) |
| Document ingestion | **IMPLEMENTED** | Hash-based incremental reindex, suffix allowlist, size cap, hidden-file skip (`ingestor.py:11-31, 59-121`) |
| Chunking | **IMPLEMENTED** (character/paragraph-based) | `retrieval/chunker.py` — explicitly not tokenizer-aware, by design, for low-resource predictability |
| Embeddings | **MISSING** in the live app; **reference design exists in `archive/`** | `archive/claude-v0.1/lumos/rag/embedder.py` (Ollama `nomic-embed-text` + hashing fallback) — README calls this "the reference design for semantic retrieval in v0.2" (`archive/README.md:9-10`), but it is not wired into `lumos/` |
| Vector/semantic search | **MISSING**; reference design exists (`archive/.../rag/store.py`, a NumPy cosine-similarity store) | not ported |
| Keyword search | **IMPLEMENTED**, mature | SQLite FTS5 + BM25 + two deliberate relevance rules (§3); this is the one retrieval path that is genuinely well-built |
| RAG/retrieval into prompts | **IMPLEMENTED** (lexical + graph-linked) | `agent/orchestrator.py:69-83`, `retrieval/service.py:116-157` |
| Source attribution | **IMPLEMENTED** | `SourceItem` schema, shown in both UIs; explicitly suppressed under the echo provider so it can't misrepresent unused context (`orchestrator.py:189-218`) |
| Confidence/provenance metadata | **PARTIAL** | BM25 score is surfaced per source; graph edges carry a `provenance`/`source` column (`graph/store.py:48-49`) but this is not surfaced to the user anywhere in the UI |
| Edit/delete/export/backup controls | **MISSING** (for memories and notes via the app) | No API route or CLI command deletes/edits a memory or a note; the only "backup" is the manual `.bak` file observed in `data/` and deleting `lumos.db` to force a rebuild (`notes/README.md:11`) |
| Obsidian/Markdown-vault compatibility | **PARTIAL** | Reads `[[wikilinks]]`, `#tags`, YAML `tags:`/`aliases:` frontmatter the way Obsidian writes them (`graph/extract.py:1-13`); does not read Obsidian's own graph/canvas files, does not write anything back into the vault |
| Knowledge graph | **PARTIAL — IMPLEMENTED but not "visual"** | Real, tested, derived graph in SQLite (§3); the web UI exposes it as a clickable list-based ego view in a drawer (`static/index.html:90-103`, `static/app.js:214-334`), not a rendered node-link diagram |

**What would need to be built for the desired "second brain" system:** (1) an embeddings/vector index — either port `archive/.../rag/` or build fresh, behind the same `search_notes(query, limit)` contract the docs already specify (`docs/extending.md:21-30`); (2) note create/edit/delete from the app, with the graph kept in sync (the sync machinery in `graph/store.py` already assumes ingest-time rewrites, so this is additive, not a rewrite); (3) memory lifecycle controls (list/edit/delete/export) — currently the biggest concrete gap relative to the vision's "inspectable, editable, deletable, exportable" requirement; (4) an actual visual graph renderer (even a simple force-directed SVG) if the ego-view list is judged insufficient; (5) a review/approval pipeline before anything ingested from the open web ever becomes a durable memory (`save_memory` is already gated off by default — the review *UI* the code comments reference does not exist yet, `builtin.py:73-104`, README `LUMOS_ALLOW_MODEL_MEMORY_WRITES` note).

---

## 7. Agent and tool safety audit

**Does an orchestrator/agent loop exist?** Yes — `AgentOrchestrator.chat()` (`agent/orchestrator.py:50-227`). It is a single linear turn: gather context (notes, linked notes, web, memories) → build system prompt → call provider with tool schemas → if tool calls returned, execute them and loop (bounded) → final answer → persist → build sources. **There is no explicit "plan" object or multi-step planning phase** — it is a bounded ReAct-style tool-calling loop, which is a real and useful thing, but narrower than the vision's "make a visible plan" requirement (project brief, "An agent in this project means..."). This distinction should be kept explicit in any future status reporting.

**How tools are registered/invoked:** `ToolRegistry` (`tools/registry.py`) is a genuinely explicit allowlist — a model can only invoke a function by exact name that was registered; unknown names raise `KeyError` (`registry.py:43-46`). Tools are built once at container construction (`tools/builtin.py:9-105`) from injected services, not dynamically discovered.

**Actual tools that exist**, with risk rating:

| Tool | What it does | Can it write files? | Execute commands? | Network access? | Credentials? | Risk rating |
|---|---|---|---|---|---|---|
| `search_notes` | BM25 query over already-ingested note chunks | No | No | No | No | **Low — read-only**, bounded (`limit` clamped 1–10) |
| `search_web` | Query DDGS or SearXNG | No | No | **Yes** (outbound HTTP to a search provider) | No (no keys sent) | **Network risk**, otherwise read-only; the query text itself leaves the machine |
| `save_memory` *(off by default)* | Inserts a row into the `memories` table | Writes to the local SQLite DB only (not the filesystem/notes) | No | No | No | **Write/modification risk** — disabled by default specifically because no approval UI exists yet (`builtin.py:87-90`, `.env.example:59-60`) |

No tool anywhere executes shell commands, edits arbitrary files, or reaches credentialed services on the model's behalf — this matches `docs/security.md:9` and `README.md:15` exactly, and I found no counter-evidence anywhere in the code.

**Approval/permission checks:** none at the per-call level (no "confirm before this tool runs" gate) — the only gating mechanism is registration itself (a tool not registered cannot be called) and the `LUMOS_ALLOW_MODEL_MEMORY_WRITES` flag for the one tool with any write effect. This is consistent with the current risk profile (nothing destructive is registered) but would need a real approval mechanism before any higher-risk tool (file write, code execution, purchases) is ever added — `docs/extending.md:32-40` already states this requirement for future tools.

**Are tool actions logged?** Yes, but only implicitly: `tool_events` (tool name, arguments, ok/error, result) are attached to the assistant's message metadata in SQLite (`orchestrator.py:122-187`) — a genuine, per-turn audit trail exists in the database. It is **not exposed** through any CLI/API "show me what tools ran" surface, and neither current UI renders it (§3, §12) — so today it is an audit trail only for someone querying the SQLite file directly, not for the end user in-product.

**Task/work-graph visualization:** **MISSING.** No component renders "what Lumos is doing right now" as a plan/graph. The knowledge graph UI (§6) is unrelated — it visualizes *notes*, not *agent activity*.

**Overall assessment:** what exists today is **safe by narrowness** — there is simply nothing dangerous registered, not because a permission system successfully constrains something dangerous. That is a fine, honest place to be for v0.1, but it means the "safety" claims in `docs/security.md` are currently true by absence of risky capability rather than by presence of a tested guardrail, and that distinction matters before any higher-risk tool (shell, file write, purchasing, browser control) is added.

---

## 8. Web/API/UI audit

- **Web app:** exists and is real — FastAPI (`main.py`) serving a single-page vanilla HTML/CSS/JS client (`static/index.html`, `app.js`, `styles.css`) at `/`, mounted static assets at `/static`, JSON API under `/api`.
- **API:** 7 endpoints, all in `api/routes.py` (§2 table). No authentication/authorization anywhere (`docs/security.md:19-21` states this openly), no CORS middleware configured (acceptable given the UI is same-origin), no rate limiting.
- **Routes/endpoints implemented:** `GET /api/health`, `POST /api/chat`, `GET /api/conversations/{id}`, `POST /api/notes/reindex`, `POST /api/search/notes`, `POST /api/search/web`, `GET /api/graph`. All backed by real container calls, not stubs. `GET /docs` (FastAPI's auto OpenAPI UI) is also live by default.
- **Static files/frontend:** real, not placeholders — the JS implements a full chat loop, health polling, source cards, and a graph-browsing drawer with its own mini view-history/back button (`app.js:234-380`). It has no automated test coverage (no Playwright/Jest present in the repo) — its correctness is inferred from careful reading and from the API contract it consumes, not from execution.
- **Visual knowledge graph:** exists as a **list-based ego view**, not a node-link visual diagram (see §6). **Visual work/task graph:** does not exist at all (see §7).
- **What's needed to turn the CLI prototype into a fuller local web UI:** the web UI already *is* the primary intended surface (the CLI is explicitly the "lightest option," `README.md:76-78`) — so the remaining gaps are: authentication/session boundaries before any non-owner access, a way to browse/edit memories and notes in-app, a rendered graph visualization if the list view is judged insufficient, and surfacing `tool_events` for transparency.

---

## 9. Training-lab gap analysis

*(No training code is being written here — this is strictly a gap inventory.)*

| Milestone item | Status | Suggested first path | Dependencies/risks |
|---|---|---|---|
| Tokenizer | **MISSING** | Start with a small BPE trained on the user's own corpus (e.g. `tokenizers` library) sized to the ~1M-parameter target vocabulary | Vocabulary size vs. model size tradeoff must be decided before any architecture code is written |
| Small decoder-only transformer | **MISSING** | A minimal from-scratch implementation (a few hundred lines) rather than importing a large framework, to keep the "understand what we built" goal intact | PyTorch (CPU-first) as the only new heavy dependency |
| Configurable model sizes (1M→100M+) | **MISSING** | Parameterize layer count/width/heads from one config, verify at 1M first before ever touching 3M+ | Needs a realistic hardware note (a 1M model trains fast on CPU; do not imply this scales to "smart" — per the audit's own constraint) |
| Dataset ingestion/cleaning/manifesting | **MISSING** in `lumos/`; **partial prior art** in `archive/.../rag/ingest.py` (hash-manifest pattern already proven) | Reuse the hash-manifest idea from the archived ingestor for a training corpus manifest | Needs an explicit decision on what corpus (user notes? public text? both, tagged separately?) |
| Data licensing/provenance policy | **MISSING** | A simple per-source-file provenance/license tag recorded alongside the manifest | This is a policy decision, not just code — needs the user's explicit answer (see Questions section) |
| Training loop | **MISSING** | Standard loop (batch, forward, loss, backward, step), logged, checkpointed every N steps | — |
| Validation loop | **MISSING** | Held-out split from the same manifest | — |
| Checkpoint saving/resume | **MISSING** | Plain `torch.save`/`load` of model+optimizer+step count to start; a registry can come later | Needs a decision on where checkpoints live relative to the git repo (large-file handling, §10) |
| Text/sample generation | **MISSING** | Greedy/temperature sampling script against a checkpoint | — |
| Reproducible configurations | **MISSING** | One YAML/JSON per run capturing model size, data version, tokenizer version, seed | This is exactly the shape `docs/architecture.md`'s module-boundary philosophy already anticipates — should live in its own `lumos/training/` (or sibling package), not inside the chat app |
| Hardware-aware settings | **MISSING** | CPU-only defaults for the 1M milestone; explicit opt-in for GPU | The user's actual hardware is unknown to this audit — a real unknown, see questions |
| Evaluation/regression testing | **MISSING** for a trained model; **the evals/ harness pattern already proven** for the graph feature is a strong template to reuse (canaries, repeat-for-reliability, corpus-fault detection) | Apply the same discipline (§3) to model evals once training exists | — |
| Experiment history | **MISSING** | Start as append-only JSON/CSV logs per run before adding any dashboard | — |
| Dataset/model/version lineage | **MISSING** | Content-hash the dataset manifest and the tokenizer, record both in each checkpoint's metadata | — |
| Safe promotion of an experimental checkpoint | **MISSING** | A manual, explicit "promote" step (copy + tag), never automatic | Matches the project's "dangerous actions require explicit approval" principle |

**Overall:** this is a from-scratch effort. Nothing here is partially built in the live `lumos/` package. The archived `claude-v0.1` tree's `rag/` module is useful *prior art for retrieval*, not for training, and should not be mistaken for training progress.

---

## 10. "Git for AI" and backup audit

- **Git hygiene:** good. Clean working tree, linear-looking history (29 commits total across the visible branches), descriptive commit messages that read almost like a changelog with rationale. A tag `backup/pre-rewrite` exists, confirming a deliberate, safety-conscious history rewrite happened at some point (consistent with prior project memory of squashing "parallel-agent mega-commits"). Both `main` and `feature/graph-v1` are fully synced with `origin` — nothing is only-local.
- **Branches/tags:** `main`, `feature/graph-v1` (13 commits ahead, all pushed), tag `backup/pre-rewrite`. No release tags (e.g. `v0.1.0`) despite the README calling this "Lumos v0.1" — a small, easy documentation/versioning gap.
- **Source-code versioning:** standard git, nothing unusual.
- **Notes and prompt versioning:** **none** — `lumos/agent/prompts.py` is versioned only as source code (i.e., as well as any other file), not as a tracked "prompt version" with its own changelog/eval linkage. The user's own notes folder (`lumos/notes/`) has no versioning beyond whatever the user does with their own files outside the app.
- **Dataset manifests/versioning:** **none in the live app** (a manifest *pattern* exists in `archive/.../rag/ingest.py` via file-hash manifests, but it is not a "dataset version" concept — it is a reindex-skip optimization).
- **Large-file/model-checkpoint handling:** **no policy or tooling exists** — no `.gitattributes`/Git LFS configuration found. This will matter the moment any real checkpoint file is produced (even a 1M-parameter model's checkpoint plus optimizer state can be tens of MB).
- **Experiment tracking / model registry:** **none.**
- **Backup/recovery:** ad hoc — a single `lumos.db.bak` file was found in `data/` (manually created at some point, not automated), and `evals/results/` accumulates timestamped Markdown eval reports (gitignored) as a de facto experiment log for the one thing that *is* being measured (graph retrieval quality).
- **Audit/event logs:** partial — `tool_events` per assistant message (§7) is the closest thing to an audit log, and it is DB-only, not exported or queryable via any dedicated endpoint.
- **Reproducibility:** the graph eval is genuinely reproducible (fresh scratch DB per run, `evals/harness.py:277-293`) — this is the strongest reproducibility story in the repo and a good template.

**Proposed minimal versioning design (not over-engineered, matched to the actual first milestone):**
1. Keep code versioning as-is (git); add a lightweight `v0.x` git tag per README milestone bump — near-zero cost, immediate value for anyone (including a future agent session) trying to say "what did Lumos look like when X was true."
2. For notes/memories: no new system needed yet — SQLite + the user's own external note-editor history (or their own git repo of the vault, if they choose to keep one) is sufficient at this scale. Revisit only if multi-device sync or collaborative editing appears.
3. For the training lab, once it exists: one directory per experiment run (config + manifest hash + tokenizer hash + metrics + a pointer to the checkpoint file), and Git LFS (or an out-of-git artifact folder, gitignored, with a manifest committed instead of the binary) for checkpoints — do not commit raw model weights to the main git history.
4. Do not build a database-backed model registry, dataset versioning system, or full MLOps stack before the first checkpoint exists. That would be solving a scaling problem the project does not have yet.

---

## 11. Incomplete, planned, and missing work

### A. Already started but incomplete

- **Tool-call transparency.** `tool_events` are fully computed (`orchestrator.py:122-187`) and included in the `ChatResponse`/DB record, but neither UI displays them (`cli.py:219-225`, `static/app.js` — no reference to `tool_events` anywhere). *Remaining work:* render them (even minimally — "used search_notes, used search_web") in both `cli.py` and `app.js`.
- **Web search provider parity.** DDGS and SearXNG both implement `WebSearchProvider`, but only DDGS has any real-world usage evidence (it's the zero-config default); SearXNG has no automated test and depends on infrastructure outside this repo. *Remaining work:* at minimum a mocked-transport test mirroring `test_provider_checks.py`'s pattern.
- **Multi-provider plan (Phase 5).** Prior project memory records a "Phase 5 = multi-provider plan awaiting approval" — no corresponding code exists yet in this checkout (confirmed: only Ollama and one OpenAI-compatible slot exist). *Remaining work:* this is a planning item that has not started in code.
- **Graphify integration.** Was added (`9bc0551`: `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`, `.agents/`) and then **fully removed** eight commits later (`f3ae944`) once Lumos grew its own native graph (`lumos/graph`), with the commit message explicitly noting the third-party tool "has no role here" anymore. *Remaining work:* none — this is a closed loop, but `archive/README.md` and any external memory referencing "graphify" for *this* repo should be treated as stale.

### B. Discussed/planned but not found in code

- **CLI improvements beyond current commands** (e.g., memory listing/deletion, note editing) — not found.
- **Own-model training** (tokenizer, architecture, training loop, checkpoints) — not found anywhere; see §9.
- **Continual/controlled learning from user teaching, approved notes/files, reviewed web sources** — not found; the closest thing today is the gated, unreviewed `save_memory` tool, which is explicitly *disabled* pending "an approval and review interface" that does not exist (`README.md:233`).
- **Second brain** (full Obsidian-like note graph with editing) — partially found (read-only graph, §6); editing/versioning not found.
- **Obsidian-style visual graph** — a *textual* ego-view exists; a rendered visual graph does not.
- **Task/work graph** (visualizing the agent's live plan/tool use) — not found at all.
- **Model/data/checkpoint versioning** — not found; no training artifacts exist yet to version.
- **Controlled web learning** (review pipeline before internet content becomes durable memory) — not found; web search results are used as ephemeral per-turn context only, never persisted as memory.
- **Safe agent tools beyond the current three** (coding sandbox, computer-use, voice) — documented as *future* in `docs/extending.md:42-65`, no implementation.
- **Local web application** — this already exists in a genuine, working form (§8); if "local web application" in the original vision meant something more (e.g. installable desktop shell), that is not built.
- **Private multi-user access / authentication / per-user profiles** — not found; explicitly listed as a v0.1 non-goal (`README.md:280`, `docs/security.md:19,26-28`).
- **Multimodal extensions** (voice, images, 3D, video) — not found; sketched only as future module boundaries in `docs/extending.md`.

### C. Recommended but not necessarily previously discussed *(my own recommendations — clearly separated from the above)*

- **RECOMMENDED:** Surface `tool_events` in both UIs before adding any new tool — it's nearly free (the data already exists) and it is the cheapest possible step toward the vision's "auditable record of what it did."
- **RECOMMENDED:** Add a minimal memory-management surface (list/delete via CLI command and one API route) before expanding what can be remembered — the vision explicitly requires memory to be "inspectable, editable, deletable, exportable," and today none of those verbs exist for a saved memory except through raw SQLite access.
- **RECOMMENDED:** Start the training lab as a **separate top-level package** (e.g. `lumos-brain/` or `training/`), not inside `lumos/lumos/`, so its (heavier, GPU-relevant) dependencies never become a requirement for the working chat app, and so its own tests/CI can run independently.
- **RECOMMENDED:** Tag a `v0.1.0` git release now — the README already calls the project this; a tag costs nothing and gives every future audit/agent session a stable reference point.
- **RECOMMENDED:** Decide the embeddings question explicitly (§ Questions) before writing any more retrieval code, since the current BM25-only design and the `archive/` embeddings design both work, and picking one deliberately is cheaper than discovering a conflict after both exist half-built.

---

## 12. Bugs, risks, and technical debt

| # | Finding | Severity | Evidence | Recommended direction |
|---|---|---|---|---|
| 1 | `tool_events` computed and returned by the API/DB but never rendered in the CLI or web UI, so a user cannot see what tools ran even though the vision requires an "auditable record" | Medium | `orchestrator.py:122-187` vs. `cli.py:219-225`, `static/app.js` (no `tool_events` reference) | Render tool names (and ok/error) in both UIs |
| 2 | No authentication anywhere; anyone reaching the port can chat, read conversation history, and (if enabled) write memories | High *(only if ever exposed beyond localhost)*, Informational at rest | `docs/security.md:19-21` (self-documented), confirmed no auth code in `api/routes.py`/`main.py` | Documented boundary already states "do not expose before adding auth" — no code fix needed until exposure is planned |
| 3 | SQLite database is unencrypted at rest; conversation history and personal memories sit in plaintext on disk | Medium (privacy) | `docs/security.md:21`, `memory/database.py` (plain `sqlite3.connect`) | Document as a known limitation; consider OS-level disk encryption as the interim mitigation rather than building app-level crypto prematurely |
| 4 | `.venv` runs Python 3.14.3 while `pyproject.toml` declares `requires-python = ">=3.11"` and `[tool.mypy] python_version = "3.11"` targets 3.11 — mypy's type-checking baseline doesn't match the interpreter actually used to run tests | Low | `.venv/Scripts/python.exe --version` → 3.14.3; `pyproject.toml:10,53` | Align the mypy target (or note the intentional forward-compat gap) |
| 5 | Web search failures are silently swallowed in proactive search (`except Exception: logger.warning(...)`) — a broken SearXNG/DDGS install degrades invisibly to the end user beyond a log line | Low | `orchestrator.py:86-93` | Consider surfacing a soft "web search unavailable" note in the response when `use_web=True` was requested but failed |
| 6 | `archive/README.md` still describes rich-CLI/echo-provider/tool-exhaustion/memory-injection as "planned to be ported in Phase 2" — all four have since been fully ported and shipped (commits `18a67d4`, `b2ab7e7`, `9a9ea4a`, `eefda2e`) | Informational (documentation drift) | `archive/README.md:5-10` vs. git log | Update `archive/README.md` to reflect that Phase 2 porting completed |
| 7 | No git release tag matches the "v0.1" name used throughout the README/pyproject | Informational | `pyproject.toml:7`, `README.md:1` vs. `git tag` output (only `backup/pre-rewrite`) | Tag `v0.1.0` |
| 8 | No automated test exercises the FastAPI HTTP layer directly (e.g., via `TestClient`) for most routes except the graph endpoint (`test_graph_api.py`); other routes are only indirectly covered through container-level tests shared with the CLI | Low | Test file inventory (§2); no `httpx.AsyncClient`/`TestClient`-based test found for `/chat`, `/health`, `/notes/reindex`, `/search/*` | Add a thin `TestClient`-based smoke test per route to catch FastAPI wiring regressions (status codes, response-model validation) that container-level tests can't see |
| 9 | No Git LFS / large-file policy exists yet | Low (today), will become Medium the moment a real checkpoint file exists | `git check-attr`/`.gitattributes` absent | Decide the checkpoint storage policy before the training lab produces its first artifact (§10) |
| 10 | Design choices that could make future own-model training harder | Informational | — | None found that actively conflict — the `ChatProvider` protocol is narrow enough to accept a Lumos-trained model later without any current design change. The one soft risk: if the training lab is built *inside* `lumos/lumos/` rather than as a separate package, its dependencies (likely PyTorch) become a hard dependency of the chat app, which currently has none — recommend keeping them separate (see §11.C) |

No: broken imports, missing dependency declarations, database migration/data-loss risks, or dead code were found. This is a notably clean codebase for its size — the single `pass` statement in the entire `lumos/lumos` tree is a legitimate empty exception-class body (`providers/base.py:47`), and the single `# pragma: no cover` is a defensive `if row_id is None` guard on a SQLite invariant that always holds (`graph/store.py:34`).

---

## 13. Test and run status

**Available test suites:**
- `lumos/tests/` — 17 files, 165 tests (`pytest.ini_options` in `pyproject.toml:40-43`, `testpaths = ["tests"]`).
- `lumos/evals/` — a separate, purpose-built evaluation harness (not `pytest`-based for its main report, though `evals/harness.py`'s corpus-fairness logic is itself unit-tested via `tests/test_eval_corpus.py`).

**How to run each:**
```bash
cd lumos
pytest -q                    # unit/integration tests — safe, local, no network
python -m evals.run_eval           # retrieval-only eval — safe, local, no network, no model
python -m evals.run_eval --answers # ALSO calls the configured chat model — costs money/quota if using a paid/cloud provider, and needs a real Ollama/OpenRouter key
ruff check .                 # lint — safe, local
```

**Which are safe to run locally:** `pytest -q`, `python -m evals.run_eval` (no `--answers`), and `ruff check .` — all safe, local, no external calls. **I ran all three this session.**

**Which require external services/keys/etc.:** `python -m evals.run_eval --answers` requires a working provider (Ollama Cloud/local, or OpenRouter) and will make real model calls (180 calls in the README's documented run, `evals/README.md:120`) — I did **not** run this, since it would call a paid/external service without prior approval. `python -m lumos` (web) and `python -m lumos cli` are safe in principle (no network required with an empty `.env`) but are long-running/interactive, so I did not start them this session — see §4 for why, and for the equivalent evidence from `test_cli.py`.

**What I actually ran and the exact result:**
- `pytest -q` → **165 passed**, 335 warnings (all `DeprecationWarning`s about `asyncio.get_event_loop_policy`, from `pytest-asyncio` internals, not from Lumos code), 8.65s.
- `ruff check .` → **All checks passed!**
- `python -m evals.run_eval` → completed in about a second; results **exactly matched** the numbers documented in `evals/README.md` (12/30 BM25-alone, 30/30 with graph, 18 rescued, 0 short, 1/6→6/6 multi-note). This produced one new gitignored file under `evals/results/` as a normal side effect of the script (not a code change, and `evals/results/` is explicitly `.gitignore`d, `lumos/.gitignore:9`) — flagging this transparently per the instruction to report all actions taken.

**Minimal safe test plan to validate the current baseline** (everything below is safe, local, free, and is what I'd hand to the next person/agent): `pytest -q`, then `ruff check .`, then `python -m evals.run_eval`. All three together take under 15 seconds and, per this session, all currently pass.

---

## 14. Recommended roadmap

**Phase 1 — Stabilize and document the current CLI.**
*Objective:* lock in what already works before adding surface area.
*Deliverables:* tag `v0.1.0`; add the `tool_events` display to CLI/web (§11.C); fix the `archive/README.md` drift (§12 #6); add a `TestClient`-based smoke test per API route.
*Dependencies:* none. *Risks:* none material. *Definition of done:* tagged release, `pytest -q` and `ruff check .` both green (already true), tool events visible in a manual CLI run.
*First issues:* "Tag v0.1.0", "Show tool_events in CLI and web UI", "Update archive/README.md phase-2 status", "Add TestClient smoke tests for /api routes".

**Phase 2 — Safe tests, error handling, offline mode.**
*Objective:* harden what's there, not add features.
*Deliverables:* mocked-transport test for SearXNG (mirroring `test_provider_checks.py`); a visible (not just logged) "web search unavailable" signal when `use_web=True` fails.
*Dependencies:* Phase 1. *Risks:* low. *Definition of done:* web-search failure path has a test and a user-visible signal.

**Phase 3 — Local second-brain memory vault.**
*Objective:* make memory a first-class, user-controllable thing, not a write-once table.
*Deliverables:* list/edit/delete/export for memories (CLI command(s) + API route(s)); a decision on note editing in-app vs. external-only.
*Dependencies:* none technical; needs the user's answer on scope (see Questions). *Risks:* scope creep if this becomes a full CRUD app before it's needed. *Definition of done:* a user can see, delete, and export every stored memory without touching SQLite directly.

**Phase 4 — Reviewable knowledge ingestion and retrieval.**
*Objective:* decide and (if approved) build the embeddings path; add a review gate before any auto-learned fact becomes durable.
*Deliverables:* either a documented decision to stay lexical, or an embeddings adapter satisfying the existing `search_notes(query, limit)` contract, ported from/inspired by `archive/.../rag/`; a minimal approval step before `save_memory`-style writes are ever turned on by default.
*Dependencies:* Phase 3 (memory controls should exist before more gets written automatically). *Risks:* embeddings add a real dependency (a model, more RAM) — must respect the "low-resource default" principle; should be opt-in, mirroring how the graph flags are opt-in today.

**Phase 5 — Visual knowledge graph and task/work graph.**
*Objective:* close the "visual" gap identified in §6/§7.
*Deliverables:* a rendered graph view (even a simple SVG force layout) as an alternative/upgrade to the current list drawer; a minimal "what is Lumos doing right now" view driven by the already-existing `tool_events`.
*Dependencies:* Phase 1's tool-events surfacing is a direct prerequisite for the work-graph half of this phase.

**Phase 6 — Data/model/checkpoint versioning and backups.**
*Objective:* put the minimal versioning design from §10 in place *before* Phase 7 produces its first artifact.
*Deliverables:* experiment-run directory convention; Git LFS or gitignored-artifact-plus-manifest decision recorded.
*Dependencies:* none blocking; best done just ahead of Phase 7.

**Phase 7 — First 1M-parameter Lumos training laboratory.**
*Objective:* the first real step toward an owned model, isolated from the working chat app.
*Deliverables:* tokenizer, tiny transformer, tiny curated dataset with a manifest, train/validate loop, checkpoint save/resume, sample generation, one reproducible config.
*Dependencies:* Phase 6's versioning convention; an explicit answer on hardware (CPU-only vs. available GPU) and training-data source/licensing (see Questions).
*Risks:* the single biggest risk is scope/expectation — a 1M-parameter model will not produce useful general conversation; its success criterion should be "the pipeline works end-to-end and produces *any* coherent short completion on its own tiny training distribution," not "it answers questions well."
*Definition of done:* a checkpoint exists, was produced by a reproducible, documented run, and a small eval script can load it and generate text.

**Phase 8 — Scale only after measured evaluation and hardware planning.** Objective/deliverables/DoD all gated on Phase 7's actual measured results plus an explicit hardware conversation with the user; do not pre-plan model sizes beyond 1M until Phase 7 is done.

**Phase 9 — Optional local/external model integrations as adapters, not permanent dependencies.** Already substantially satisfied by the existing `ChatProvider` protocol (§5) — this phase is mostly "keep doing what's already being done" plus formally adding a fourth provider once Phase 7/8 produce something loadable.

**Phase 10 — Specialized capabilities one at a time (coding, voice, images, 3D, video, multilingual).** Not started; `docs/extending.md` already sketches sensible module boundaries for voice and a coding sandbox — treat those sketches as the starting design brief when this phase begins, and gate each new tool through the same approval/allowlist discipline already used for `search_notes`/`search_web`/`save_memory`.

---

## 15. Immediate next task

**Recommended task: surface `tool_events` in both the CLI and the web UI.**

This is small, high-value, fully supported by existing code, testable, and 100% reversible.

- **Exact files involved:**
  - `lumos/lumos/cli.py` — `_print_response()` (currently `cli.py:219-225`), which has `response.tool_events` available on the `ChatResponse` it already receives but does not print.
  - `lumos/lumos/static/app.js` — `addMessage()` (currently `app.js:50-87`), which already receives `data` from `/api/chat` and could read `data.tool_events` alongside the `sources` it already renders.
  - No backend change is needed — `ChatResponse.tool_events` (`schemas.py:30`) is already populated end-to-end.

- **Acceptance criteria:** after a turn where a tool actually fired (e.g., ask a question with `use_notes=True` and a real provider configured, or more simply, register a test tool that always fires), the CLI prints at least the tool name and success/failure for each entry in `tool_events`, and the web UI shows the same information somewhere near the message (e.g., a small "used: search_notes" chip). A turn with no tool calls shows nothing extra, unchanged from today.

- **Short implementation plan:**
  1. In `cli.py`, after the existing sources loop in `_print_response`, iterate `response.tool_events` and print one dim line per event (tool name + ok/error).
  2. In `app.js`, inside `addMessage`, after building `sourcesEl`, if `options.toolEvents?.length`, render a small line/badge per event; pass `tool_events: data.tool_events` through from `sendMessage`'s `addMessage('assistant', data.answer, { sources: data.sources, toolEvents: data.tool_events })` call.
  3. No schema change needed (`tool_events: list[dict[str, Any]]` already exists on `ChatResponse`).

- **Tests to add/run:** extend `tests/test_cli.py` (which already builds a `container` with an echo-only provider and calls `chat_once`/`handle_command` directly) with one test that registers a tool-hungry provider (a pattern already used in `tests/test_orchestrator.py`'s `ToolHungryProvider`) and asserts the printed/rendered output includes the tool name. Run `pytest -q tests/test_cli.py` afterward; run the full `pytest -q` before considering it done, since it touches shared rendering code.

- **What must not be changed yet:** the orchestrator's tool-loop logic, the `ChatResponse`/`ChatRequest` schemas' existing fields, the provider protocol, the graph/retrieval code, and anything under `evals/` — this task is presentation-only and should not touch any of those.

---

## Project Context Handoff

```
LUMOS PROJECT — CONTEXT HANDOFF (audit performed 2026-09-16)

WHAT IT IS: A working single-user/family personal-AI prototype. Python 3.11+,
FastAPI + vanilla JS web UI + Rich-based terminal CLI, SQLite for everything
(conversations, memories, notes index via FTS5, and a derived knowledge graph).
Package: `lumos-personal-ai` at lumos/pyproject.toml. Main package code lives at
lumos/lumos/ (~3,800 lines). Repo root also has archive/ (two OLD, non-running
implementations kept for reference only — do not import from or "fix" these).

CURRENT BRANCH: feature/graph-v1, 13 commits ahead of main, BOTH fully pushed to
origin (nothing local-only). Working tree clean. Last commit 2026-07-13
(12543ee). Tag `backup/pre-rewrite` exists from an earlier deliberate history
rewrite. No v0.1.0 release tag yet despite README calling it "Lumos v0.1".

VERIFIED THIS SESSION: `pytest -q` → 165/165 passed. `ruff check .` → clean.
`python -m evals.run_eval` → reproduced README's graph-retrieval numbers exactly
(12/30 BM25-alone → 30/30 with graph; 18 rescued; 1/6→6/6 on multi-note
questions). This is real, working, tested code — not a demo/scaffold.

WHAT IS REAL AND WORKING: provider routing (Ollama Cloud/local → OpenRouter/
OpenAI-compatible → echo fallback, in lumos/lumos/providers/); SQLite
conversation memory + gated durable "remember" facts; notes ingestion + BM25
(FTS5) retrieval with two deliberate relevance rules (stopwords, score floor);
a deterministic knowledge graph (wikilinks/tags) with read-only browsing and an
opt-in retrieval-expansion feature (both gated behind separate flags,
LUMOS_GRAPH_ENABLED / LUMOS_GRAPH_EXPAND_RETRIEVAL); a bounded 3-tool allowlist
(search_notes, search_web, optional save_memory) inside a bounded tool-call loop
(agent/orchestrator.py); a CLI and web UI, both thin clients over one
AgentOrchestrator; a genuinely well-designed custom eval harness
(evals/harness.py) with canary facts, repeat-for-reliability, and corpus-fault
detection — this is unusually rigorous for a project this size.

WHAT IS NOT REAL YET (do not claim otherwise): NO tokenizer, NO transformer
architecture, NO training loop, NO checkpoints, NO model registry — zero
own-model training code exists anywhere. NO embeddings/vector search in the
live app (a reference design sits unused in archive/claude-v0.1/lumos/rag/ —
Embedder/VectorStore/NumpyVectorStore — explicitly noted in archive/README.md
as "the reference design for semantic retrieval in v0.2"). NO authentication,
NO multi-user support (single implicit user by design, v0.1 non-goal). NO
visual (rendered) knowledge graph — the web "graph" is a clickable list-based
ego view in a side drawer, not a node-link diagram. NO task/work-graph
visualization of what the agent is doing. NO memory edit/delete/export UI
(only insert, via CLI /remember or the disabled-by-default save_memory tool).
The agent loop is a bounded ReAct-style tool-caller, NOT a planning agent with
approval gates — there is no "visible plan" object as the project vision
defines "agent."

ONE CONCRETE, ALREADY-DIAGNOSED GAP: `tool_events` (which tools ran, with what
args, success/failure) are fully computed by AgentOrchestrator.chat() and
returned in every ChatResponse, and stored in SQLite message metadata — but
NEITHER the CLI (lumos/lumos/cli.py `_print_response`) NOR the web UI
(lumos/lumos/static/app.js `addMessage`) displays them. This is the recommended
first task: cheap, safe, high-value, and a genuine step toward the "auditable
agent" vision.

KEY FILES TO KNOW: lumos/lumos/core/container.py (single composition
root/dependency wiring — read this first to understand how everything connects);
lumos/lumos/agent/orchestrator.py (the "agent"); lumos/lumos/config.py (every
tunable, all documented in lumos/.env.example); lumos/README.md (unusually
accurate — every claim in it was checked against source during this audit and
matched); lumos/docs/{architecture,extending,security}.md.

KNOWN STALE DOCS: archive/README.md still says four features (rich CLI, echo
provider, graceful tool-round exhaustion, memory fact-injection) are "planned
to be ported in Phase 2" — all four shipped months ago (commits 18a67d4,
b2ab7e7, 9a9ea4a, eefda2e). A prior session's memory of this project said
feature/graph-v1 was "unpushed" — that is now stale; it is fully pushed.

DO NOT: describe Ollama/OpenRouter routing as "Lumos's trained model." Do not
describe the SQLite memory table as neural-network learning. Do not claim the
1M-parameter training milestone (once started) will produce general
intelligence — frame it explicitly as an educational/pipeline-correctness
milestone. Do not add authentication/multi-user/destructive tooling without
explicit user approval — none of these exist by deliberate design choice, not
oversight.
```

---

## Proposed GitHub issues (priority order — not created; awaiting explicit approval)

| # | Priority | Title | Why |
|---|---|---|---|
| 1 | P0 | Show `tool_events` in CLI and web UI | Cheapest possible step toward auditable-agent vision; data already exists (§11.C, §15) |
| 2 | P0 | Tag `v0.1.0` release | README already calls it this; zero-cost reference point |
| 3 | P1 | Add memory list/delete/export (CLI + API) | Vision requires memory be "inspectable, editable, deletable, exportable" — currently only insertable |
| 4 | P1 | Update `archive/README.md` Phase-2 status | Documentation drift — four "planned" items already shipped |
| 5 | P1 | Add `TestClient`-based smoke tests for all `/api` routes | Only the graph route has direct HTTP-layer test coverage today |
| 6 | P2 | Add mocked-transport test for SearXNG provider | Parity gap vs. DDGS/model-provider test rigor |
| 7 | P2 | Surface a visible signal when proactive web search fails | Currently silent beyond a log line |
| 8 | P2 | Decide and record embeddings/vector-retrieval scope (v0.2) | Architectural fork — cheaper to decide now than after partial builds diverge |
| 9 | P3 | Design experiment/checkpoint versioning convention (pre-training-lab) | Needed before Phase 7 produces its first artifact; avoids committing binaries to git history |
| 10 | P3 | Scaffold isolated training-lab package (tokenizer + tiny transformer + train/eval loop, 1M params) | First concrete step toward the long-term "owned model" goal, kept decoupled from the chat app |

---

## Questions/unknowns requiring your answer before further architectural work

1. **Embeddings/vector retrieval:** stay BM25-only (current, low-resource, working) or port/rebuild the `archive/claude-v0.1/lumos/rag/` design (Ollama `nomic-embed-text` + NumPy store)? This changes dependencies and resource requirements.
2. **Note editing in-app:** should Lumos ever write to the notes vault (create/edit notes, not just read them), or should the vault remain strictly externally-authored (Obsidian/editor of choice) with Lumos as a read-only index forever?
3. **Memory review/approval:** what should the actual approval UI for model-initiated memory writes look like before `LUMOS_ALLOW_MODEL_MEMORY_WRITES` is ever turned on by default — per-write confirmation, a review queue, something else?
4. **Training-lab hardware:** what hardware is actually available for the first 1M-parameter milestone (CPU-only laptop? a GPU? cloud burst budget?) — this materially changes what "first path" is realistic for Phase 7.
5. **Training data source and licensing policy:** what corpus is the first model allowed to train on — the user's own notes only, a public dataset, both? What licensing/consent rule should gate anything not personally authored?
6. **Visual graph priority:** is the current list-based ego view acceptable for the near term, or is a rendered node-link visualization (and the associated frontend work) a near-term priority?
7. **Multi-user/family access:** is authentication/per-profile access actually needed soon (the vision mentions "family, and explicitly invited users"), or does the household currently share one instance/profile, deferring this?
8. **Release cadence and versioning:** should `v0.1.0`/`v0.2.0` etc. be formal git tags going forward, tied to the README's "boundaries" sections, or informal as today?
