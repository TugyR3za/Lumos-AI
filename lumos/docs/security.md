# Security and privacy notes

Lumos v0.1 is a development build for localhost use.

## Current protections

- Binds to `127.0.0.1` by default.
- Does not expose API keys to the browser.
- Does not include arbitrary shell or computer-control tools.
- Uses an explicit tool allowlist.
- Bounds tool-call rounds to prevent endless loops.
- Restricts notes ingestion to one configured folder.
- Skips hidden, unsupported, and oversized files.
- Labels retrieved content as untrusted reference data in the system prompt.
- Disables model-initiated durable memory writes by default.

## Important limitations

- There is no authentication in v0.1.
- Anyone who can reach the HTTP port can use the system and read conversation output.
- SQLite is not encrypted at rest.
- A cloud request sends its assembled prompt, recent history, and selected retrieval context to the configured provider.
- Web search sends the search query to the configured search service.
- Prompt injection cannot be eliminated by a prompt alone; future high-risk tools need policy enforcement outside the model.

## Before family or remote use

Add authentication, per-user profiles, encrypted secret storage, TLS, request rate limits, audit logs, and memory permissions. Do not bind to `0.0.0.0` or expose the port through a router until those controls exist.
