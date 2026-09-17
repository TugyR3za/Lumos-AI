# Lumos Project Recovery Audit

Audit basis: active branch `feature/graph-v1` at commit `12543ee`, inspected September 16, 2026. No repository files were changed during the audit, packages installed, real notes reindexed, external models called, or paid/networked evaluations run.

## 1. Executive summary

### What Lumos currently is

**IMPLEMENTED — partially working prototype.** Lumos is a Python 3.11+ personal-assistant prototype with:

- A terminal chat client and local FastAPI web client.
- Ollama and OpenAI-compatible provider adapters.
- Predictable provider fallback with a non-AI echo fallback.
- SQLite conversation history and searchable durable memories.
- Incremental notes ingestion, paragraph-aware chunking, and SQLite FTS5/BM25 search.
- A deterministic graph derived from Markdown wikilinks and tags.
- A bounded model/tool loop with three allowlisted tools.
- A substantial offline test suite.

This is more mature than a scaffold, but it is not yet a safe family-ready MVP. It has no authentication, per-user isolation, complete memory controls, accessible action audit trail, or reliable offline-permission boundary.

### What it was intended to become

**PLANNED.** The supplied vision describes a private, local-first “second brain” and controlled agent platform that eventually trains and runs Lumos-owned models. It includes inspectable memory, reviewed learning, visual knowledge and work graphs, reproducible model training, versioned datasets/checkpoints, safe tools, and optional external adapters.

Some foundations match that direction, particularly modular providers, SQLite persistence, local notes, provenance fields, an allowlist, and deterministic graph indexing. Most of the long-term system remains unimplemented.

### Current maturity

**PARTIAL — prototype.**

The code is coherent, runnable, and tested, but a usable MVP would require explicit privacy enforcement, memory management, authentication or strict localhost safeguards, backup/migration support, and documentation corrections.

### Most important truth

Lumos does not currently have its own AI brain. Every substantive answer comes from an existing Ollama-served model or an OpenAI-compatible service. `EchoProvider` is canned text, not a model. There is no tokenizer, transformer, training loop, checkpoint format, dataset lineage system, or Lumos model registry.

In addition, the nominal privacy toggles are not permission boundaries: disabling notes or web context stops proactive retrieval, but the model still receives `search_notes` and `search_web` tool schemas and can request those tools.

### Three most valuable next actions

1. **RECOMMENDED:** Make notes, web access, and provider fallback explicit enforceable permissions, not advisory UI toggles.
2. **RECOMMENDED:** Add memory/conversation inspect-edit-delete-export controls, schema migrations, and tested backup/restore.
3. **RECOMMENDED:** Define a separate, reproducible training-lab boundary before writing model code: hardware profile, licensed corpus policy, tokenizer/version format, experiment manifest, and promotion rules.

## 2. Repository map

| Path | Purpose and important symbols | Status | Evidence |
|---|---|---:|---|
| `lumos/README.md` | User-facing v0.1 setup, providers, retrieval, graph, tools, API, boundaries | **PARTIAL** | Broadly matches the active implementation, but contains privacy and evaluation drift discussed below |
| `lumos/pyproject.toml` | Package metadata, dependencies, `lumos` entry point, pytest/Ruff/mypy settings | **IMPLEMENTED** | Installable setuptools package; no lock file or coverage config |
| `lumos/.env.example` | Runtime configuration examples | **PARTIAL** | Covers common settings, but not every `Settings` field |
| `lumos/Makefile` | Install, launch, reindex, tests, lint, formatting, evaluations | **IMPLEMENTED** | Commands correspond to package entry points; eval writes a report despite being described as a read-only-style check |
| `lumos/lumos/config.py` | `Settings`, `.env` loading, path anchoring, provider defaults | **IMPLEMENTED** | Central typed configuration; `default_route` is presently unused |
| `lumos/lumos/__main__.py` | Top-level `web`, `cli`, `reindex`, and help dispatch | **IMPLEMENTED** | Minimal manual `sys.argv` dispatch |
| `lumos/lumos/cli.py` | Interactive CLI, state, slash commands, status and graph rendering | **IMPLEMENTED** | Tested end to end with echo and temporary databases |
| `lumos/lumos/main.py` | FastAPI application, startup ingestion, static UI mounting | **IMPLEMENTED** | Real application entry point |
| `lumos/lumos/api/routes.py` | Health, chat, conversation, reindex, note/web search, graph endpoints | **IMPLEMENTED** | Real routes; no authentication or memory-management API |
| `lumos/lumos/static/` | Vanilla HTML/CSS/JS chat UI and graph drawer | **PARTIAL** | Functional client; graph is a navigable adjacency drawer, not a visual node/edge graph |
| `lumos/lumos/core/container.py` | Composition root: database, graph, retrieval, providers, tools, agent | **IMPLEMENTED** | Clean modular assembly point |
| `lumos/lumos/agent/` | Prompt construction, history/retrieval assembly, provider and tool loop | **PARTIAL** | Functional bounded loop; no explicit planning, approval state machine, or visible work tree |
| `lumos/lumos/providers/` | Provider contracts, Ollama, OpenAI-compatible, echo, routing | **IMPLEMENTED** | Network adapters and fallback logic are tested with mocked HTTP |
| `lumos/lumos/tools/` | Allowlisted `search_notes`, `search_web`, optional `save_memory` | **PARTIAL** | Small and bounded, but request toggles do not remove corresponding tools |
| `lumos/lumos/memory/database.py` | SQLite schema and operations for conversations, messages, notes, memories, FTS | **PARTIAL** | Functional persistence; no migrations, edit/delete/export APIs, encryption, or backup manager |
| `lumos/lumos/notes/ingestor.py` | Incremental configured-folder ingestion by content hash | **IMPLEMENTED** | Supports text, Markdown, source, JSON, YAML, TOML, HTML, CSS, C/C++ and Rust |
| `lumos/lumos/retrieval/` | Character chunking, stopword filtering, FTS5/BM25 relevance, graph expansion | **IMPLEMENTED** | Deterministic and well tested; no embeddings in active code |
| `lumos/lumos/graph/` | Markdown reference extraction, graph persistence and one-hop queries | **IMPLEMENTED** | SQLite nodes/edges with feature-flagged reads and retrieval expansion |
| `lumos/docs/` | Architecture, security, and extension guidance | **PARTIAL** | Useful boundaries, but architecture still calls durable memories “future” despite their implementation |
| `lumos/evals/` | 32-note graph corpus, 30 questions, deterministic retrieval and optional answer evaluation | **IMPLEMENTED** | Strong feature-specific evaluation; answer mode calls configured models and can be expensive |
| `lumos/tests/` | 17 modules, 147 test functions, 165 collected cases | **IMPLEMENTED** | All 165 cases pass; no browser, live-provider, permissions, migration, or backup tests |
| `archive/claude-v0.1/` | Obsolete alternate v0.1 with Groq, Tavily, Ollama embeddings and NumPy vectors | **OBSOLETE** | Explicitly excluded from the running application by `archive/README.md` |
| `archive/build-artifacts/` | Stale wheel and checksum | **OBSOLETE** | Documentation warns to rebuild rather than use it |
| `.git/` | 29 commits, two local branches, one tag, GitHub remote | **IMPLEMENTED** | Clean tree; active feature branch is 13 commits ahead of `main` |

No Docker files, Compose configuration, CI workflows, dependency lock files, changelog, formal roadmap file, coverage configuration, or current AGENTS/CLAUDE instructions exist.

## 3. What is implemented

### Fully implemented functionality

#### **IMPLEMENTED — package and application composition**

`build_container()` constructs every active subsystem and injects dependencies rather than relying on global services (`lumos/lumos/core/container.py:38`). It is tested indirectly by CLI, API, provider configuration, graph, and retrieval tests and is likely runnable in the existing virtual environment.

#### **IMPLEMENTED — SQLite conversations**

`create_conversation()`, `add_message()`, and `get_messages()` persist ordered user/assistant history with provider, model, metadata, and timestamps (`lumos/lumos/memory/database.py:137`).

Limitations:

- No conversation list, rename, delete, export, retention, ownership, or per-user isolation.
- Tool-event metadata is stored but omitted from the conversation API.

#### **IMPLEMENTED — durable searchable memories**

`save_memory()` and `search_memories()` provide FTS5-backed durable personal facts with namespace, optional key, importance, source, and timestamps (`lumos/lumos/memory/database.py:385`).

- User-controlled CLI writes exist through `/remember`.
- Model writes are disabled by default.
- Relevant memories are injected into prompts, not used to train a neural network.
- Memory retrieval has dedicated relevance tests.

Limitations:

- No list/edit/delete/export UI or API.
- No approval queue when model writes are enabled.
- Provenance is stored but not shown to the user or included in prompt context.

#### **IMPLEMENTED — notes ingestion**

`NotesIngestor.ingest_all()` scans one configured directory, ignores hidden and unsupported files, caps file size, hashes contents, chunks changed files, and removes stale index records (`lumos/lumos/notes/ingestor.py:59`).

Limitations:

- Text-like formats only; no PDF, DOCX, images, email, or browser imports.
- Replacement decoding can hide invalid UTF-8.
- A transient read failure can make an existing index record appear stale and remove it from the derived database.
- Symbolic links are not explicitly rejected.

#### **IMPLEMENTED — FTS5/BM25 retrieval**

The active stack is:

```text
configured notes folder
  → UTF-8 decoding
  → paragraph-aware character chunks
  → SQLite documents/chunks
  → FTS5 + BM25
  → stopword cleanup + relative score floor
```

Important code:

- `lumos/lumos/retrieval/chunker.py:6` — `chunk_text()`
- `lumos/lumos/retrieval/relevance.py:53` — `search_terms()`
- `lumos/lumos/memory/database.py:319` — `Database.search_chunks()`
- `lumos/lumos/retrieval/service.py:55` — `RetrievalService.search_notes()`

This is tested and likely runnable without a model.

#### **IMPLEMENTED — Markdown knowledge graph**

Markdown ingestion extracts `[[wikilinks]]`, body `#tags`, frontmatter `tags`, and frontmatter `aliases`. The database stores note, tag, and unresolved-entity nodes with `links_to`, `tagged`, and `mentions` edges. Graph writes share the document transaction.

Important code:

- `lumos/lumos/graph/extract.py:73` — `extract_refs()`
- `lumos/lumos/graph/store.py:73` — `sync_note()`
- `lumos/lumos/graph/service.py:65` — `GraphService`

Graph reads and graph-aware retrieval are separately feature-flagged and off by default.

#### **IMPLEMENTED — provider adapters and routing**

- Ollama local or Ollama Cloud: `lumos/lumos/providers/ollama.py`
- OpenAI-compatible `/chat/completions`: `lumos/lumos/providers/openai_compatible.py`
- Canned setup response: `lumos/lumos/providers/echo.py`
- Primary/fallback/echo order: `lumos/lumos/providers/router.py`

Adapters normalize tool calls and provider status. Mock-transport tests cover authentication, probing, and response handling.

#### **IMPLEMENTED — local API and web UI**

FastAPI serves JSON routes and static assets. The browser supports chat, persistent current conversation ID, route selection, notes/web toggles, health display, notes reindexing, source cards, and graph search/navigation. It is dependency-free frontend code, not a placeholder.

### Partially implemented functionality

#### **PARTIAL — agent behavior**

The orchestrator can gather context, call a provider, execute tools, observe results, loop for a configured number of rounds, and save an event summary.

It does not create or expose a plan, model tasks/subtasks, ask for tool approval, pause/resume goals, render a work tree, maintain a first-class append-only action log, or enforce the user’s notes/web toggles against tool calls.

#### **PARTIAL — attribution**

Search-hit source cards are returned, but they represent retrieved candidates, not verified sources actually used by the answer. Linked notes are deliberately omitted from source cards even if they influenced the answer; the prompt merely asks the model to name them.

#### **PARTIAL — Obsidian compatibility**

Basic wikilinks, tags, aliases, and Markdown vault files are understood. There is no full Obsidian parser, backlinks file format, block reference support, attachments, embedded media, canvas files, vault settings, note editing, or graph layout. Path-qualified wikilinks may not resolve correctly because link targets and duplicate-path slugs are normalized differently.

#### **PARTIAL — evaluations**

The graph evaluation is thoughtful and deterministic at retrieval level. It is not a general model-quality, safety, privacy, or regression suite.

## 4. CLI audit

### Top-level commands

| Command | Actual behavior | Inputs/configuration | Status |
|---|---|---|---|
| `python -m lumos` | Starts Uvicorn web application | Server, storage, providers, search, graph and agent settings | **IMPLEMENTED** |
| `python -m lumos web` | Same as default | Same | **IMPLEMENTED** |
| `python -m lumos cli` | Starts terminal chat, optionally ingests notes first | All runtime settings | **IMPLEMENTED** |
| `python -m lumos reindex` | Opens/initializes the configured DB, scans notes, updates chunks and graph, removes stale documents | Database/notes paths, file and chunk limits | **IMPLEMENTED — modifies derived data** |
| `python -m lumos help`, `-h`, `--help` | Prints launcher docstring | None | **IMPLEMENTED** |
| Any other first argument | Prints help and exits 2 | No structured parser | **IMPLEMENTED but minimal** |

There is no `argparse` validation, version command, structured subcommand help, or support for command-line configuration overrides.

### Interactive slash commands

| Command | What it does | Important caveats |
|---|---|---|
| `/help` | Prints command list | **IMPLEMENTED** |
| `/status` | Probes providers, reports web adapter, DB counts, graph and paths | May make provider health network calls when configured |
| `/reindex` | Reingests configured notes folder | Writes database and can remove stale index records |
| `/graph <path-or-slug>` | Shows one-hop graph neighbors and related notes | Requires `LUMOS_GRAPH_ENABLED=true` |
| `/remember <text>` | Immediately stores durable memory with source `user_cli` | No review, edit, delete or undo |
| `/model auto\|local\|cloud` | Changes route for the current process | `local` means primary Ollama slot and can point to Ollama Cloud |
| `/notes on\|off` | Enables/disables proactive note retrieval | Does not remove `search_notes` from model tools |
| `/web on\|off` | Enables/disables proactive web retrieval | Does not remove `search_web` from model tools |
| `/reset` | Drops only the in-process conversation ID | Does not delete stored history |
| `/quit`, `/exit` | Exits CLI | `/exit` exists but is absent from help |

### Environment variables

The documented core set includes server, storage, Ollama, OpenAI-compatible cloud, search, retrieval, graph, and memory variables. Additional code-supported settings not fully surfaced in `.env.example` include file-size limits, chunk sizes, retrieval top-k, history limit, graph display caps, `default_route`, tool-round limit and provider timeout (`lumos/lumos/config.py:24`).

### Expected user flow

1. Install dependencies and create `.env`.
2. Select Ollama Cloud, local Ollama, or an OpenAI-compatible fallback.
3. Put notes under the configured notes folder.
4. Start `web` or `cli`; startup ingestion runs by default.
5. Chat with notes on and web off.
6. Use `/remember` for explicit durable facts.
7. Optionally enable graph reads/expansion.

### Documented but missing or misleading

- No model training, model registry, dataset, checkpoint, memory-management, export, backup, approval, task-plan, or work-graph commands.
- Archived documentation mentions `/reindex force` and provider names such as `groq`/`echo`; those belong to the obsolete implementation.
- `Settings.default_route` is not applied to either CLI state or API defaults.
- “Local” routing is misleading when the primary is configured as Ollama Cloud.
- “Web off” and “notes off” do not prohibit model-initiated search tools.

### Recommended first smoke-test sequence

After backing up the existing ignored database and using a temporary database/notes directory:

```powershell
python -m lumos --help
python -m lumos reindex
python -m lumos cli
```

Inside the CLI:

```text
/status
/help
/notes off
/web off
hello
/reset
/quit
```

Use the echo fallback first. Do not test `/remember` against the real database unless a persistent write is intended.

## 5. Model and provider audit

| Capability | State | Evidence |
|---|---:|---|
| Lumos-owned trainable model | **MISSING** | No tensor/model/training package or dependency |
| Tokenizer | **MISSING** | Only regex term splitting and provider tokenization |
| Decoder-only transformer | **MISSING** | No architecture code |
| Dataset pipeline | **MISSING** | Notes ingestion is retrieval ingestion, not training-data preparation |
| Training/validation loop | **MISSING** | No optimizer, loss, batching or validation |
| Checkpoint/resume | **MISSING** | No state serialization |
| Model evaluation suite | **MISSING** | Existing eval measures retrieval and provider-generated answers |
| Model registry | **MISSING** | Provider model names are configuration strings |
| Ollama local inference | **IMPLEMENTED** | Local `/api/chat` adapter |
| Ollama Cloud inference | **IMPLEMENTED** | Same adapter with Bearer token |
| OpenAI-compatible inference | **IMPLEMENTED** | `/chat/completions` adapter |
| Echo responder | **IMPLEMENTED** | Canned setup response, explicitly not a model |
| Primary/fallback router | **IMPLEMENTED** | Error-based provider fallback |
| Quality/capability routing | **MISSING** | No task classifier, capability metadata or quality evaluation |

The current provider abstraction does not prevent future own-model integration: a Lumos inference runtime could implement `ChatProvider`. However, the default architecture and documentation center external/runtime adapters, and no separate training/runtime boundary exists yet.

A future owned model should be clearly separated into:

```text
training lab → promoted model artifact → local inference adapter → ProviderRouter
```

Training code should not live in the agent orchestrator or be triggered by ordinary chat.

## 6. Memory, second brain, and retrieval audit

| Area | Status | Current reality |
|---|---:|---|
| Conversations | **IMPLEMENTED** | SQLite conversations/messages with provider/model and timestamps |
| Durable user memories | **PARTIAL** | Save and relevance search exist; management controls do not |
| Notes | **IMPLEMENTED** | Configured local folder, read-only ingestion |
| Database schema/storage | **IMPLEMENTED** | SQLite with WAL and foreign keys |
| Schema migrations | **MISSING** | Tables are created with `IF NOT EXISTS`; no schema version or upgrade path |
| Document ingestion | **IMPLEMENTED** | Incremental hash-based text ingestion |
| Chunking | **IMPLEMENTED** | Paragraph-aware character chunks with overlap |
| Embeddings | **MISSING active / obsolete archived** | Archived alternate tree has Ollama and hashing vector code; active package does not import it |
| Vector search | **MISSING active** | Archived NumPy implementation is obsolete |
| Keyword search | **IMPLEMENTED** | SQLite FTS5/BM25 with LIKE fallback |
| RAG into prompts | **IMPLEMENTED** | Notes, optional graph expansions, web snippets and memories |
| Source attribution | **PARTIAL** | Candidate source cards, not verified answer-level citations |
| Confidence metadata | **PARTIAL** | Relative BM25 scores exist; no calibrated confidence |
| Provenance | **PARTIAL** | Document path/hash, memory source, edge source/provenance are stored but incompletely exposed |
| Memory edit/delete/export | **MISSING** | No methods/routes/UI |
| Conversation delete/export | **MISSING** | No methods/routes/UI |
| Backup/restore | **MISSING** | An ignored `.bak` file exists, but no managed workflow |
| Obsidian compatibility | **PARTIAL** | Markdown, wikilinks, tags and aliases only |
| Knowledge graph | **IMPLEMENTED data / PARTIAL UI** | SQLite graph and adjacency drawer; no visual graph layout |
| Multi-user profiles | **MISSING** | Single namespace and no ownership/auth |
| Controlled learning | **MISSING** | Retrieval and saved memories do not update model weights |

### What a real second brain still needs

1. A canonical vault format, preferably user-owned Markdown plus sidecar metadata.
2. Stable content IDs independent of filenames.
3. Note and memory CRUD with undo/history.
4. Import review, quarantine and approval states.
5. Provenance, license, author, source URL, ingestion date and trust metadata.
6. Hybrid retrieval only after lexical baseline tests remain available.
7. Export and restore commands that do not require Lumos to interpret the content.
8. Encryption/secret strategy appropriate to the threat model.
9. A true visual graph and an accessible nonvisual alternative.
10. Per-user access rules before family use.

## 7. Agent and tool safety audit

### Orchestration

**PARTIAL.** `AgentOrchestrator.chat()` stores the user message, retrieves context, builds a prompt, calls a provider, executes tools, feeds results back, stops after a bounded number of rounds, and stores the answer and event metadata. There is no explicit planning phase or plan object.

### Tool registration and invocation

`ToolRegistry` is an explicit in-memory allowlist. Unknown tools are rejected. Tool arguments are not validated against the published JSON schema before invocation; Python signature/type failures are caught by the orchestrator and returned as tool errors.

### Existing tool risk ratings

| Tool | Availability | Risk rating | Safety status |
|---|---|---|---|
| `search_notes` | Always registered | Read-only low risk; **private-data disclosure risk** | Bounded result count, but callable when notes are toggled off |
| `search_web` | Always registered | **Network risk** and query privacy risk | Bounded result count, but callable when web is toggled off |
| `save_memory` | Only when configured | **Write/modification risk** and private-data persistence risk | Disabled by default; no real approval gate when enabled |
| CLI `/remember` | Direct user command | Write/modification risk | Explicit user action, but no undo/edit/delete |
| Reindex/API reindex | Direct user/API action | Derived-data modification risk | No authentication or approval; reads configured files |
| Shell/filesystem-write/computer control | Absent | Not applicable | Safest part of the current design |
| Credential access tools | Absent | Not applicable | Provider adapters hold keys in process only |

### Safety findings

- **HIGH:** Request toggles do not constrain the offered tool set or execution permission.
- **HIGH:** Automatic fallback can send the assembled private prompt to another provider after an error without a fresh approval.
- **HIGH if remotely exposed:** No authentication or per-user isolation.
- **MEDIUM:** `save_memory` trusts a model’s interpretation of “explicitly asked” whenever globally enabled.
- **MEDIUM:** Tool events are saved only in assistant-message metadata and cannot be reviewed through the API/UI.
- **MEDIUM:** Prompt-injection resistance relies mainly on prompt text; appropriate for current read/search tools but insufficient for future side-effecting tools.
- **MISSING:** Work/task tree, approval queue, capability tokens, deny rules, and append-only audit log.

## 8. Web/API/UI audit

### API

**IMPLEMENTED:**

- `GET /api/health`
- `POST /api/chat`
- `GET /api/conversations/{conversation_id}`
- `POST /api/notes/reindex`
- `POST /api/search/notes`
- `POST /api/search/web`
- `GET /api/graph`
- Generated FastAPI documentation at `/docs`

### Web application

**IMPLEMENTED prototype.** It is a real zero-build client, not a placeholder. It supports chat, health status, sources, route selection, notes/web toggles, reindexing and graph browsing.

### Missing or partial UI capabilities

- No authentication or user profiles.
- No conversation browser, rename, delete or export.
- No memory browser, provenance display, approval, edit, delete or export.
- No accessible tool-event/action audit view.
- No streaming.
- No settings management.
- No offline mode indicator beyond provider status.
- Reloaded conversation history loses sources and tool events.
- No graph canvas, spatial visualization, filtering or graph export.
- No work/task graph.
- No note editor or vault file browser.
- No responsive/native/mobile client verification.

The web shell already exists. The next work is not a frontend rewrite; it is to expose secure domain APIs for permissions, memory, conversations, audit events, backups and vault access, then add UI surfaces over those APIs.

## 9. Training-lab gap analysis

| Milestone item | State | Suggested first path | Dependencies/risks |
|---|---:|---|---|
| Tokenizer | **MISSING** | Versioned byte-level or small BPE experiment with deterministic tests | Corpus choice affects vocabulary; license and multilingual goals must be known |
| Small decoder-only transformer | **MISSING** | Separate optional `training` package with a minimal causal transformer and parameter-count tests | Framework choice, numerical correctness, hardware profile |
| Configurable ~1M sizes | **MISSING** | Named configs with computed parameter totals | Tokenizer vocabulary can dominate a 1M budget |
| Dataset ingestion/cleaning | **MISSING** | Immutable raw inputs → reviewed normalized shards → manifest | Privacy, poisoning, duplicate data and licensing |
| Licensing/provenance policy | **MISSING** | Require source, license/permission, hash and approval for every input | Must be decided before collecting data |
| Training loop | **MISSING** | Deterministic causal-language-model baseline | Framework and device support |
| Validation loop | **MISSING** | Fixed held-out set, loss/perplexity plus memorization checks | Leakage and tiny-dataset overfitting |
| Checkpoint save/resume | **MISSING** | Model, optimizer, scheduler, RNG, step and config in one manifest | Atomic writes and large-file handling |
| Sample generation | **MISSING owned-model** | Seeded greedy/top-k generation separate from provider adapters | Sampling can conceal weak learning |
| Reproducible configs | **MISSING** | Checked-in TOML/YAML plus resolved run manifest | Need lock file and environment capture |
| Hardware-aware settings | **MISSING** | Record CPU/GPU/RAM/VRAM, precision and measured throughput | Owner hardware is unknown |
| Evaluation/regression | **MISSING model-level** | Tiny overfit test, held-out loss, memorization/privacy, prompt suite | Do not compare 1M model to frontier assistants as if equivalent |
| Experiment history | **MISSING** | Append-only run directories and summary index | Avoid committing huge logs |
| Dataset/model lineage | **MISSING** | Hashes linking dataset, tokenizer, config, code commit and checkpoint | Requires stable manifest specification |
| Safe checkpoint promotion | **MISSING** | Explicit candidate → evaluated → approved → active states | Must never auto-promote from chat data |

The archived hashing/Ollama embedding implementation is retrieval infrastructure, not evidence of language-model training.

A 1M-parameter model is a research and education milestone. Feasibility and useful context length depend on vocabulary size, sequence length, batch size, framework, precision, hardware, data quality and evaluation—not parameter count alone.

## 10. “Git for AI” and backup audit

### Current state

| Area | State |
|---|---:|
| Git repository hygiene | **PARTIAL** — current tree clean and ignores runtime data/caches |
| Commit history | **IMPLEMENTED** — 29 commits with descriptive graph/relevance changes |
| Branches | `main`, `feature/graph-v1`; feature is 13 commits ahead |
| Tags | One `backup/pre-rewrite` tag, not a release version |
| Remote | GitHub origin configured |
| Uncommitted changes | None at audit time |
| Stashes | None |
| Releases | **UNVERIFIED** |
| Issues/pull requests | **UNVERIFIED** — exact remote was inaccessible via web lookup and `gh` is not installed |
| CI | **MISSING** |
| Dependency lock | **MISSING** |
| Runtime data versioning | **MISSING** |
| Dataset manifests | **MISSING for training** |
| Prompt versioning | Git only |
| Checkpoint/LFS strategy | **MISSING** |
| Experiment tracking | Graph evaluation reports only |
| Model registry | **MISSING** |
| Backup/recovery automation | **MISSING** |
| Audit/event log | **PARTIAL** — tool events embedded in message metadata |
| Reproducibility | **PARTIAL** for application, **MISSING** for training |

Runtime `data/` and `evals/results/` are ignored. A `lumos.db` and older `lumos.db.bak` exist locally, but their contents were not read or modified. There is no evidence that the backup is current, restorable, encrypted, or automatically produced.

Historical generated Graphify data was removed from the current tree, but remains in Git history and contributed substantial repository history size.

### Minimal practical versioning design

**RECOMMENDED:**

1. Keep source, prompts, schemas, small configs and manifests in Git.
2. Add a database `schema_version` table and explicit migrations.
3. Define a vault manifest containing file hashes and metadata; keep Markdown itself user-owned.
4. Add a `lumos backup` command using SQLite’s backup API, copying vault metadata/manifests, producing a timestamped archive and checksum, and excluding secrets unless requested.
5. Store experiment manifests in Git, not checkpoints.
6. Store checkpoints and large datasets outside normal Git; use content-addressed paths and optionally Git LFS/DVC only when needed.
7. Record Git commit, dataset/tokenizer hashes, resolved config, hardware/software versions, seed, metrics and checkpoint hashes in every experiment manifest.
8. Require an explicit recorded promotion event before a checkpoint becomes the active local model.

## 11. Incomplete, planned, and missing work

### A. Already started but incomplete

- **PARTIAL — durable memory:** storage, FTS and recall exist; CRUD, provenance display, consent workflow, deletion and export do not.
- **PARTIAL — knowledge graph:** real nodes/edges and one-hop navigation exist; no full visual graph, editor, stable cross-vault IDs or complete Obsidian semantics.
- **PARTIAL — agent auditability:** tool events are captured, but hidden inside message metadata and unavailable in UI/API.
- **PARTIAL — permissions:** global allowlist exists, but request-level notes/web permissions are not enforced.
- **PARTIAL — provider privacy:** modular adapters exist, but fallback consent and disclosure preview are absent.
- **PARTIAL — source attribution:** retrieval sources are shown, but use is not verified and linked-note attribution depends on model prose.
- **PARTIAL — evaluations:** graph retrieval is evaluated well; overall correctness, privacy, safety, provider parity and UI are not.
- **PARTIAL — typing:** mypy is configured, but currently reports ten errors.
- **PARTIAL — backups:** one local `.bak` exists without a managed or tested workflow.
- **PARTIAL — archived semantic retrieval:** the archived tree has an embedding/vector prototype, but it is obsolete and has known design weaknesses such as append-only changed-file behavior.

### B. Discussed/planned but not found in active code

- **PLANNED:** richer CLI and explicit offline behavior.
- **PLANNED:** owned-model and fine-tuning/training pipeline.
- **PLANNED:** controlled continual learning.
- **PLANNED:** full second brain.
- **PLANNED:** Obsidian-style visual graph.
- **PLANNED:** task/work graph.
- **PLANNED:** data, tokenizer, model and checkpoint versioning.
- **PLANNED:** reviewed web learning and provenance.
- **PLANNED:** approval-gated write, coding and computer-use tools.
- **PLANNED:** safer local web application for family use.
- **PLANNED:** authentication and private multi-user profiles.
- **PLANNED:** voice input/output.
- **PLANNED:** coding sandbox.
- **PLANNED:** image, video and 3D workflows.
- **PLANNED:** multilingual features.
- **PLANNED:** mobile/native/on-device interfaces.
- **PLANNED:** streaming responses.
- **PLANNED:** embedding or hybrid retrieval.

### C. Recommendations not established as historical requirements

- **RECOMMENDED:** Treat all context export—notes, memories, history and web queries—as named capabilities checked per request.
- **RECOMMENDED:** Add an explicit “strict offline” mode that cannot construct external providers or network tools.
- **RECOMMENDED:** Use schema migrations before adding any more durable tables.
- **RECOMMENDED:** Add immutable audit-event records separate from chat messages.
- **RECOMMENDED:** Persist source snapshots/tool events needed to reproduce an answer.
- **RECOMMENDED:** Test backup restoration, not just backup creation.
- **RECOMMENDED:** Add CI for supported Python versions, Ruff, mypy and offline pytest.
- **RECOMMENDED:** Keep training dependencies optional and isolated from the everyday assistant install.
- **RECOMMENDED:** Establish a data-governance file before downloading or converting training corpora.

## 12. Bugs, risks, and technical debt

| Severity | Finding | Evidence | Fix direction |
|---|---|---|---|
| **High** | Notes/web toggles do not prevent tool use | Tools are globally built and all schemas sent every turn | Build a per-request allowed-tool set and enforce it during advertisement and execution |
| **High** | Automatic provider fallback may resend private assembled context externally without fresh approval | Router retries the same messages | Add deny/ask/preapproved fallback policy and context disclosure |
| **High if exposed** | No authentication or user isolation | Documented in `docs/security.md` | Keep loopback-only until authentication, authorization, CSRF/rate controls and TLS strategy exist |
| **Medium** | Product language overstates “local by default” | Default is Ollama Cloud plus DDGS | Document exactly what leaves the device |
| **Medium** | `local` route can actually mean Ollama Cloud | Router preserves legacy wire labels | Rename choices while preserving compatibility |
| **Medium** | No migrations or schema version | `initialize()` only creates tables | Add numbered transactional migrations |
| **Medium** | Existing indexed document may be removed after transient read/oversize/empty-file skip | Only successful/unchanged paths enter `active_paths` | Remove only files confirmed absent |
| **Medium** | Tool-event audit data is inaccessible | Stored in message metadata but omitted by API | Add first-class authorized audit records |
| **Medium** | Sources are retrieval candidates, not proven citations | All proactive rows become sources | Track real dependencies or label cards “retrieved context” |
| **Medium** | Provider JSON/shape errors may bypass fallback and return 500 | Incomplete response error normalization | Convert parse failures to `ProviderError` |
| **Medium** | No memory deletion/edit/export | Database exposes only save/search | Add authenticated CRUD, export and confirmation |
| **Medium** | Symlinked files are not explicitly contained | Ingest reads lexical child paths | Resolve candidates and require them under vault root |
| **Medium** | Path-qualified Obsidian wikilinks can mismatch note slugs | Link and duplicate-path normalization differ | Add canonical target resolution and tests |
| **Medium** | No dependency lock or CI | Repository inventory | Add locked environment and offline CI matrix |
| **Medium** | Ten mypy errors | Verified in five files | Fix nullable IDs and narrow source/result types |
| **Low** | `Settings.default_route` is unused | Config vs hardcoded defaults | Apply consistently or remove |
| **Low** | `/exit` is implemented but undocumented | CLI dispatch | Document or remove alias |
| **Low** | DDGS reports available without network verification | `is_available()` always returns true | Separate configured from verified |
| **Low** | Reopened web history loses sources/tool events | Conversation API response is minimal | Return and render authorized metadata |
| **Low** | Root README evaluation counts are stale | Root README vs eval docs | Generate or test documentation facts |
| **Low** | Architecture docs call memories “future” | `docs/architecture.md` | Update description |
| **Low** | Test environment shows upcoming dependency incompatibilities | 335 warnings on Python 3.14 | Test supported version matrix and update deliberately |
| **Informational** | No Lumos model/training stack exists | Repository-wide inspection | Build only after governance/reproducibility design |
| **Informational** | Graph UI is not a visual graph | Static application code | Add actual layout later while preserving list accessibility |
| **Informational** | Archived wheel/vector code is stale | `archive/README.md` | Keep isolated; consider history cleanup separately |

No critical default-state issue was found: the current default server binds to loopback, arbitrary command execution is absent, and model memory writes are off. The high findings become more serious if the service is exposed or external providers are configured.

## 13. Test and run status

### Available suites

The `tests/` directory covers CLI and echo-chat flow, SQLite and FTS5, providers and routing, tool allowlisting, orchestration, memory, ingestion, chunking, relevance, graph extraction/persistence/querying/API/expansion, and evaluation-corpus validity.

Run with:

```powershell
cd "D:\Projects\Lumos AI\lumos"
.venv\Scripts\python.exe -m pytest -q
```

### Commands and external requirements

| Command | Requirements/risk |
|---|---|
| `pytest -q` | Offline and safe; provider HTTP is mocked; uses temporary files |
| `ruff check .` | Offline and safe |
| `mypy lumos` | Offline and safe |
| `python -m evals.run_eval` | No model/network, but writes a report under `evals/results` by default |
| `python -m evals.run_eval --answers` | Calls configured providers; up to 180 model calls at defaults |
| `python -m lumos reindex` | Writes real configured DB and scans real notes |
| `python -m lumos cli` | May ingest notes, write conversation data and call configured providers |
| `python -m lumos web` | Same, plus server exposure |

### What was run

- Default-Python attempt: did not collect because Python 3.14 had no global pytest.
- Sandboxed venv attempt: 50 tests passed and 115 setup errors occurred because pytest could not access the Windows temp root.
- Retried with normal temporary-directory access: **165 passed, 0 failed, 335 warnings, 10.24 seconds**.
- Ruff: **All checks passed**.
- Mypy: **10 errors in 5 files**.
- Post-check Git status: clean; no tracked changes.

No real model, web search, live provider, evaluation answer run, real reindex, CLI chat, or web server was invoked.

### Minimal safe baseline plan

1. Run pytest with an explicitly writable temporary root and cache disabled.
2. Run Ruff.
3. Fix and then require mypy.
4. Add tests proving disabled notes/web tools cannot be invoked.
5. Run retrieval-only evaluation with `--report` targeting a disposable temporary path.
6. Use a temporary database/vault for launcher smoke tests.
7. Perform live provider tests only with explicit cost/privacy approval.

## 14. Recommended roadmap

### Phase 1 — Stabilize and document the current CLI

**Objective:** Make runtime behavior predictable and accurately described.

**Deliverables:** Structured command parser and `--version`; correct route naming; apply/remove `default_route`; accurate privacy disclosure; complete configuration reference; mypy and documentation fixes.

**Dependencies:** None.

**Major risks:** Breaking existing route values.

**Definition of done:** Help, README, `.env.example`, API defaults and behavior agree; pytest/Ruff/mypy pass.

**First issues:** Route terminology; CLI parser; configuration reference; typing cleanup; README/eval fact tests.

### Phase 2 — Add safe tests, error handling and offline mode

**Objective:** Turn privacy choices into enforceable runtime policy.

**Deliverables:** Per-request capabilities; strict offline mode; fallback policy; provider error normalization; zero-network tests; offline CI.

**Dependencies:** Phase 1 terminology.

**Major risks:** Accidental changes in automatic routing.

**Definition of done:** Tests prove notes off, web off and offline mode make prohibited access impossible.

**First issues:** Permission tests; tool filtering; fallback consent; provider error wrapping; CI.

### Phase 3 — Build the local second-brain memory vault

**Objective:** Make private information inspectable and user-owned.

**Deliverables:** Stable IDs; CRUD/export; provenance/trust metadata; conversation management; migrations; backup/restore.

**Dependencies:** Authentication and retention policy.

**Major risks:** Irreversible schema or privacy mistakes.

**Definition of done:** Every durable item can be found, inspected, edited, deleted, exported and restored.

**First issues:** Migration framework; memory API; conversation API; export format; restore test.

### Phase 4 — Add reviewable knowledge ingestion and retrieval

**Objective:** Permit new knowledge only through traceable review.

**Deliverables:** Import staging; source/license/hash manifests; approval workflow; duplicate detection; optional hybrid retrieval; answer-context provenance.

**Dependencies:** Vault schema and permissions.

**Major risks:** Poisoned/unlicensed content and embedding leakage.

**Definition of done:** No imported content becomes trusted memory or training data without recorded review.

**First issues:** Ingestion manifest; review states; provenance UI; retrieval benchmark; optional embeddings.

### Phase 5 — Add visual knowledge graph and task/work graph

**Objective:** Make knowledge relationships and agent activity visible.

**Deliverables:** Node/edge layout with list fallback; filters/provenance; task/action event schema; work timeline and approvals.

**Dependencies:** Stable graph/audit APIs.

**Major risks:** Visual complexity obscuring provenance or permission state.

**Definition of done:** Users can trace every relationship and agent action.

**First issues:** Graph export API; visualization spike; audit-event table; work timeline; approval cards.

### Phase 6 — Add data/model/checkpoint versioning and backups

**Objective:** Establish minimal “Git for AI” reproducibility.

**Deliverables:** Dataset/tokenizer/config/run manifests; content-addressed artifacts; checkpoint policy; backup verification; promotion records.

**Dependencies:** Training manifest specification and storage capacity.

**Major risks:** Binary growth and incomplete lineage.

**Definition of done:** Any promoted artifact traces to code, data, tokenizer, config, hardware and evaluation.

**First issues:** Manifest schema; hashing; storage policy; backup drill; promotion record.

### Phase 7 — Build the first ~1M-parameter training laboratory

**Objective:** Train a tiny owned decoder model reproducibly as a research milestone.

**Deliverables:** Isolated training dependencies; tokenizer; tiny decoder; parameter counter; licensed toy corpus; train/validate/generate; checkpoint/resume; reproducible smoke run.

**Dependencies:** Hardware inventory, data policy and Phase 6 manifests.

**Major risks:** Mistaking overfit samples for intelligence; vocabulary budget; nondeterminism.

**Definition of done:** A fresh environment reproduces a documented tiny run and metrics from approved inputs.

**First issues:** Hardware report; framework choice; tokenizer experiment; model config; overfit-one-batch test; checkpoint round-trip.

### Phase 8 — Scale only after measured evaluation and hardware planning

**Objective:** Increase size only when evidence justifies it.

**Deliverables:** 3M/10M/20M profiles, resource measurements, held-out metrics, ablations and cost estimates.

**Dependencies:** Reliable 1M lab.

**Major risks:** Scaling data defects, cost and checkpoint sprawl.

**Definition of done:** Every size increase has a hypothesis, budget and measured improvement.

### Phase 9 — Keep local/external models as adapters

**Objective:** Support comparison and fallback without making APIs the permanent core.

**Deliverables:** Capability metadata, provider policies, privacy previews, benchmark adapters and local-runtime promotion.

**Dependencies:** Safe permissions and owned-model runtime.

**Major risks:** Silent cloud dependence or incomparable results.

**Definition of done:** Lumos operates fully offline and external adapters can be disabled without degrading the vault.

### Phase 10 — Add specialized capabilities one at a time

**Objective:** Expand safely into coding, voice, images, 3D, video and multilingual work.

**Deliverables:** One isolated capability, threat model, permission set and evaluation suite at a time.

**Dependencies:** Agent audit/approval infrastructure.

**Major risks:** Overbroad credentials, unreviewed generated files, privacy leakage and resource costs.

**Definition of done:** Each module is independently disableable, audited and tested before the next begins.

## 15. Immediate next task

### **RECOMMENDED — Enforce notes and web toggles as real permissions**

This is small, high-value, testable and directly supported by the current architecture.

### Likely files

- `lumos/lumos/agent/orchestrator.py`
- `lumos/lumos/tools/registry.py`
- `lumos/lumos/tools/builtin.py`
- `lumos/tests/test_orchestrator.py`
- `lumos/tests/test_tools.py`
- `lumos/tests/test_cli.py`
- README/security documentation after behavior is proven

### Acceptance criteria

1. `use_notes=false` prevents proactive note retrieval and prevents `search_notes` from being advertised or executed.
2. `use_web=false` prevents proactive web retrieval and prevents `search_web` from being advertised or executed.
3. A provider returning a fabricated disabled-tool call receives a controlled denial and cannot bypass policy.
4. `save_memory` remains governed separately and disabled by default.
5. Existing allowed-tool loops still work.
6. Offline unit tests prove no search service was called.
7. All existing tests, new tests, Ruff and mypy pass.

### Short implementation plan

1. Add a registry view or schema filter for an explicit set of permitted tool names.
2. Compute the permitted set per chat request.
3. Use that set for both provider schemas and execution checks.
4. Record denied tool attempts as audit events.
5. Add tests for advertised schemas, execution denial and zero service calls.
6. Update CLI/UI wording to say the toggles are enforced.

### Must not change yet

- Provider protocols.
- Database schema.
- Graph ranking/expansion behavior.
- Training architecture.
- Memory format.
- Default external provider choices beyond documenting the separate fallback-policy issue.

## Proposed GitHub issues

No issues were created.

| Priority | Proposed issue | Type |
|---:|---|---|
| P0 | Enforce notes/web request permissions across proactive context and tool calls | Security/privacy |
| P0 | Add strict offline mode and explicit external-fallback consent policy | Security/privacy |
| P0 | Correct local/cloud terminology and privacy disclosures | Documentation/product |
| P1 | Add SQLite schema migrations and version tracking | Reliability |
| P1 | Add memory and conversation inspect/edit/delete/export APIs | Second brain |
| P1 | Add tested SQLite/vault backup and restore workflow | Recovery |
| P1 | Expose append-only tool/action audit events | Agent safety |
| P1 | Normalize provider parse failures into router-visible errors | Reliability |
| P1 | Fix ten mypy errors and require type checks in CI | Quality |
| P1 | Add offline CI with supported Python version matrix | Quality |
| P2 | Prevent transient ingest failures from deleting valid index records | Data integrity |
| P2 | Reject or explicitly authorize vault symlink escapes | Security |
| P2 | Fix path-qualified Obsidian wikilink resolution | Graph |
| P2 | Persist answer context/source provenance | Auditability |
| P2 | Add memory approval queue before enabling model writes | Safety |
| P2 | Reconcile README, architecture and eval documentation | Documentation |
| P3 | Implement actual visual graph with accessible list fallback | UI |
| P3 | Design task/work event model and visualization | Agents |
| P3 | Define dataset/tokenizer/model/run manifest specification | Training |
| P3 | Record owner hardware profile and choose isolated training framework | Training |
| P3 | Build reproducible ~1M-parameter training-lab milestone | Training |

## Questions and unknowns requiring owner input

1. What exact CPU, RAM, GPU, VRAM, storage and operating systems must training and inference support?
2. Should “strict offline” be the default, or should external providers remain enabled when explicitly configured?
3. May automatic fallback ever send notes, memories or history to a second provider without per-request approval?
4. Is the existing SQLite database important production/personal data, and is the `.bak` known to be valid?
5. Should Markdown files be the canonical source of truth, or may Lumos store notes primarily in SQLite?
6. Is compatibility with a real Obsidian vault required, including attachments, aliases, frontmatter and folder links?
7. What memory retention, deletion, encryption and backup guarantees are required?
8. Who are the intended users initially: owner only, local family accounts, or remote invited users?
9. Which languages have first-class priority for retrieval, UI and eventual model training?
10. What content is legally and personally approved for training: owner-authored text only, licensed public corpora, or both?
11. Is PyTorch acceptable for the first training lab, or is another framework/runtime preferred?
12. Should `feature/graph-v1` be merged into `main` before stabilization work, or remain isolated?
13. Are the archived embedding/vector components worth rehabilitating, or should active retrieval work start from a new design?
14. What threat model matters most: other local users, malware, browser attacks, LAN users, cloud providers, device loss, or all of these?
15. Should audit logs be immutable, and if so, who may delete or redact private entries?

## Project Context Handoff

```text
PROJECT: Lumos-AI
AUDITED STATE: feature/graph-v1 @ 12543ee; clean tree at audit time; 29 commits.
MATURITY: Real, tested prototype; not yet a safe family-ready MVP.

CURRENTLY IMPLEMENTED:
- Python/FastAPI web chat and Rich terminal CLI.
- SQLite conversations, messages, saved memories, notes/chunks and FTS5.
- Incremental notes ingestion and BM25 retrieval.
- Markdown wikilink/tag graph with CLI/API/web adjacency browsing.
- Optional graph-expanded retrieval.
- Ollama local/cloud and OpenAI-compatible provider adapters.
- Primary/fallback/echo router.
- Allowlisted search_notes, search_web, optional save_memory tools.
- 165 offline tests passing; Ruff passing.

IMPORTANT NON-IMPLEMENTED CAPABILITIES:
- No Lumos-owned model, tokenizer, transformer, training loop, checkpointing,
  dataset lineage, experiment tracker or model registry.
- No true visual knowledge graph or task/work graph.
- No authentication, multi-user isolation, memory CRUD/export, migrations,
  managed backups, approvals or accessible action audit log.
- No embeddings/vector search in the active package; archived version only.

TOP RISKS:
1. Notes/web toggles do not remove the corresponding model tools.
2. Automatic fallback can resend private assembled context externally.
3. No authentication if the HTTP port is exposed.
4. No schema migrations or tested restore process.
5. Sources represent retrieved candidates, not proven citations.
6. Mypy currently reports 10 errors.

VERIFICATION:
- pytest: 165 passed, 0 failed, 335 dependency/toolchain warnings.
- Ruff: all checks passed.
- mypy: 10 errors in 5 files.
- No real model, network search, reindex, paid evaluation or code mutation run.

RECOMMENDED NEXT TASK:
Enforce per-request notes/web permissions for both tool advertisement and
execution, with denial audit events and regression tests. Do not begin training
or rewrite the architecture yet.
```
