from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    conversation_history_limit: int = 16

    default_route: Literal["auto", "local", "cloud"] = "auto"
    max_tool_rounds: int = 3
    request_timeout_seconds: float = 90.0

    ollama_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:1.7b"

    cloud_enabled: bool = True
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: SecretStr | None = None
    cloud_model: str = "gpt-4.1-mini"

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
