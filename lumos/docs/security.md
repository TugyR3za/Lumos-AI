# Security and privacy notes

Lumos v0.1 is a development build for localhost use.

## Current protections

- Binds to `127.0.0.1` by default.
- Does not expose API keys to the browser.
- Does not include arbitrary shell or computer-control tools.
- Uses an explicit tool allowlist.
- Narrows that allowlist per request: disabled notes/web permissions hide and reject
  `search_notes`/`search_web` calls before their handlers run.
- Bounds tool-call rounds to prevent endless loops.
- Restricts notes ingestion to one configured folder.
- Skips hidden, unsupported, and oversized files.
- Labels retrieved content as untrusted reference data in the system prompt.
- Disables model-initiated durable memory writes by default.
- Keeps memory management off the model entirely: `/memories`, `/memory show`, `/memory delete`
  and `/memory export` are terminal commands, not registered tools, so no prompt-injected note
  or web page can reach them.
- Requires an exact typed `yes` before deleting a memory, and refuses to delete at all when
  there is no interactive terminal to ask.
- Deletes a memory from the FTS index in the same transaction as the row, so the text leaves
  the database rather than merely leaving the listing.
- Previews rather than prints memories when listing them, and escapes their content so a saved
  memory cannot inject terminal markup.
- Exports read only the `memories` table through an explicit field whitelist; the exporter is
  never given the settings object, so provider keys are out of its reach.

## Important limitations

- There is no authentication in v0.1.
- Anyone who can reach the HTTP port can use the system and read conversation output.
- SQLite is not encrypted at rest.
- A `/memory export` file is unencrypted plaintext containing every saved memory. It is written
  under `data/` (untracked by git) and is never deleted by Lumos; protecting, moving or removing
  it is the user's responsibility.
- A cloud request sends its assembled prompt, recent history, and selected retrieval context to the configured provider.
- Web search sends the search query to the configured search service.
- Prompt injection cannot be eliminated by a prompt alone; future high-risk tools need policy enforcement outside the model.

## Before family or remote use

Add authentication, per-user profiles, encrypted secret storage, TLS, request rate limits, audit logs, and memory permissions. Do not bind to `0.0.0.0` or expose the port through a router until those controls exist.
