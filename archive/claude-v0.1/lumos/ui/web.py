"""Minimal web UI: FastAPI backend + a single static page.

Kept intentionally small for v0.1 — a JSON chat endpoint and a couple of helpers.
Streaming, auth, and family profiles are deliberately left for later versions;
the seams are here (per-request `session`, provider `prefer`) to add them.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..app import build_app

STATIC_DIR = Path(__file__).parent / "static"

app_state = build_app()
api = FastAPI(title="Lumos", version="0.1.0")


class ChatIn(BaseModel):
    message: str
    session: str = "web"
    prefer: str | None = None


@api.on_event("startup")
def _startup() -> None:
    app_state.reindex()  # index notes when the server boots


@api.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@api.post("/api/chat")
def chat(body: ChatIn) -> dict:
    reply = app_state.assistant.ask(body.message, session=body.session, prefer=body.prefer)
    return {"reply": reply}


@api.get("/api/status")
def status() -> dict:
    return {
        "providers": app_state.router.status(),
        "tools": app_state.tools.names(),
        "notes_chunks": app_state.retriever.store.count(),
    }


@api.post("/api/reindex")
def reindex(force: bool = False) -> dict:
    return app_state.reindex(force=force)


api.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    run()
