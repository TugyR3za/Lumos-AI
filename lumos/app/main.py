from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.core.container import build_container
from app.core.logging import configure_logging

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    app.state.container = container
    if settings.ingest_notes_on_startup:
        await asyncio.to_thread(container.ingestor.ingest_all)
    yield


app = FastAPI(
    title="Lumos API",
    version="0.1.0",
    description="Python-first private personal AI system.",
    lifespan=lifespan,
)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
