# Extending Lumos

## Add a provider

Implement the `ChatProvider` protocol from `app/providers/base.py`:

```python
class MyProvider:
    name = "my-provider"
    model = "my-model"

    async def is_available(self) -> bool:
        ...

    async def chat(self, messages, tools=None) -> ProviderResponse:
        ...
```

Normalize tool calls into Lumos `ToolCall` objects. Register the provider in `build_container()` or replace the router with a policy-based implementation.

## Add a retrieval engine

Create a service exposing:

```python
def search_notes(query: str, limit: int = 5) -> list[dict]:
    ...
```

Each result should include `title`, `path`, `content`, and `score`. This allows replacing FTS5 with embeddings, a hybrid ranker, or an on-device index.

## Add a tool

Register a `RegisteredTool` in `app/tools/builtin.py` or a separate feature module. Keep tools narrow:

- Validate and cap all inputs.
- Return JSON-serializable data.
- Use an explicit timeout for network or process work.
- Require approval before writes, purchases, messages, terminal commands, or computer control.
- Record an audit event.

## Future voice module

Recommended boundary:

```text
microphone -> speech-to-text adapter -> /api/chat -> text-to-speech adapter -> speaker
```

Speech-to-text and text-to-speech should not be embedded into the agent. They should be replaceable input/output services so a local Whisper-style model can later replace a cloud voice provider.

## Future coding module

Add a separate sandbox service rather than a raw shell tool. The tool should operate inside a project workspace or container with:

- Path allowlists
- CPU/memory/time limits
- Network policy
- Git checkpoints
- Test-command allowlists
- Human approval for destructive operations

## Future computer-use module

Use a visible action plan and approval gate. Keep perception, planning, and execution separate. Never give the language model unrestricted operating-system credentials.

## Future on-device version

The current frontend is API-only and the provider contract is transport-agnostic. An on-device build can replace:

- FastAPI with an embedded Python server or native bridge
- Ollama with llama.cpp, MLX, ExecuTorch, or another runtime
- SQLite FTS5 with the same local database
- Browser UI with a native interface
