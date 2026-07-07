"""Central configuration.

Loads settings from `config.yaml` (checked into the repo, non-secret) and
secrets from `.env` (never committed). Everything downstream reads from a single
`Config` object, so there is exactly one place to change a default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = two levels up from this file (lumos/config.py -> repo root).
ROOT = Path(__file__).resolve().parent.parent


def _deep_get(d: dict, path: str, default: Any = None) -> Any:
    """Read a nested key like 'router.prefer' from a dict, safely."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class Config:
    """Resolved, ready-to-use configuration for the whole app."""

    raw: dict = field(default_factory=dict)
    root: Path = ROOT

    # --- paths ---
    @property
    def data_dir(self) -> Path:
        return self._path("paths.data_dir", "data")

    @property
    def notes_dir(self) -> Path:
        return self._path("paths.notes_dir", "data/notes")

    @property
    def db_path(self) -> Path:
        return self._path("paths.db_path", "data/lumos.db")

    @property
    def vector_path(self) -> Path:
        return self._path("paths.vector_path", "data/vectors.npz")

    # --- secrets (from environment / .env) ---
    @property
    def groq_api_key(self) -> str | None:
        return os.getenv("GROQ_API_KEY") or None

    @property
    def tavily_api_key(self) -> str | None:
        return os.getenv("TAVILY_API_KEY") or None

    # --- generic access ---
    def get(self, path: str, default: Any = None) -> Any:
        return _deep_get(self.raw, path, default)

    def _path(self, key: str, default: str) -> Path:
        val = self.get(key, default)
        p = Path(val)
        return p if p.is_absolute() else (self.root / p)

    def ensure_dirs(self) -> None:
        """Create the folders the app writes to, if missing."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(config_file: str | os.PathLike | None = None) -> Config:
    """Load `.env` then `config.yaml` and return a resolved Config."""
    load_dotenv(ROOT / ".env")  # no-op if the file is absent
    path = Path(config_file) if config_file else (ROOT / "config.yaml")
    raw: dict = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg = Config(raw=raw)
    cfg.ensure_dirs()
    return cfg
