from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OLLAMA_LOCAL_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_CLOUD_BASE_URL = "https://ollama.com"
OLLAMA_LOCAL_DEFAULT_MODEL = "qwen3:1.7b"
OLLAMA_CLOUD_DEFAULT_MODEL = "gpt-oss:20b"


def _anchored(path: Path) -> Path:
    """Resolve relative paths against the project root, not the process CWD."""
    path = path.expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="LUMOS_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Lumos"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 8000

    database_path: Path = Path("data/lumos.db")
    notes_path: Path = Path("notes")
    ingest_notes_on_startup: bool = True
    notes_max_file_bytes: int = 2_000_000
    chunk_size_chars: int = 1_200
    chunk_overlap_chars: int = 160
    retrieval_top_k: int = 5
    # A note has to hold its own next to the best match for the question: keep only
    # the hits scoring at least this fraction of the top one. A fraction and not a
    # score, because a BM25 score means nothing across queries. 0 turns it off and
    # hands back the whole top-k, junk and all.
    #
    # 0.5 costs a real answer on the eval corpus — "the woman who keeps our spare
    # key" ranks the garage that keeps a spare wheel-nut key above the note that
    # names her, and cutting that hard drops the note that leads to the answer. 0.4
    # keeps every answer with a step of room to spare.
    retrieval_score_floor: float = 0.40
    memory_top_k: int = 4
    conversation_history_limit: int = 16

    # Knowledge graph derived from notes at ingest time. Reads are off by
    # default: with this false, GraphService answers empty and no caller can
    # change retrieval or prompts. The graph is still written during ingest —
    # it is cheap, and it means turning this on needs no reindex.
    graph_enabled: bool = False
    graph_max_related: int = 5
    graph_max_neighbors: int = 50

    # Graph-aware retrieval: the notes a search finds are seeds, and the notes
    # they [[link]] to — or that link to them — follow the hits into the prompt.
    # This is the one graph feature that changes what the model is told, so it is
    # opt-in on top of graph_enabled and off by default. The note context can
    # grow by at most graph_expand_max_notes * graph_expand_max_chars characters.
    graph_expand_retrieval: bool = False
    graph_expand_max_notes: int = 3
    graph_expand_max_chars: int = 800

    default_route: Literal["auto", "local", "cloud"] = "auto"
    max_tool_rounds: int = 3
    request_timeout_seconds: float = 90.0

    # Primary provider: Ollama. "cloud" talks to Ollama Cloud (API key, no
    # downloads, no local RAM); "local" talks to an Ollama install on this
    # machine. Blank base URL / model resolve to per-mode defaults below.
    ollama_enabled: bool = True
    ollama_mode: Literal["local", "cloud"] = "cloud"
    ollama_base_url: str | None = None
    ollama_api_key: SecretStr | None = None
    ollama_model: str | None = None

    # Fallback provider: any OpenAI-compatible endpoint; OpenRouter by default.
    cloud_enabled: bool = True
    cloud_base_url: str = "https://openrouter.ai/api/v1"
    cloud_api_key: SecretStr | None = None
    cloud_model: str = "openai/gpt-4o-mini"

    echo_fallback: bool = True

    web_search_provider: Literal["auto", "ddgs", "searxng", "disabled"] = "auto"
    searxng_base_url: str | None = None
    web_search_max_results: int = 5

    allow_model_memory_writes: bool = False
    log_level: str = "INFO"

    @property
    def resolved_database_path(self) -> Path:
        return _anchored(self.database_path)

    @property
    def resolved_notes_path(self) -> Path:
        return _anchored(self.notes_path)

    @property
    def resolved_ollama_base_url(self) -> str:
        if self.ollama_base_url:
            return self.ollama_base_url
        if self.ollama_mode == "cloud":
            return OLLAMA_CLOUD_BASE_URL
        return OLLAMA_LOCAL_BASE_URL

    @property
    def resolved_ollama_model(self) -> str:
        if self.ollama_model:
            return self.ollama_model
        if self.ollama_mode == "cloud":
            return OLLAMA_CLOUD_DEFAULT_MODEL
        return OLLAMA_LOCAL_DEFAULT_MODEL

    @property
    def ollama_api_key_value(self) -> str | None:
        return self.ollama_api_key.get_secret_value() if self.ollama_api_key else None

    @property
    def cloud_api_key_value(self) -> str | None:
        return self.cloud_api_key.get_secret_value() if self.cloud_api_key else None

    def ensure_directories(self) -> None:
        self.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolved_notes_path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
