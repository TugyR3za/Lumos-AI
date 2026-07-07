from pathlib import Path

from lumos.config import Settings
from lumos.core.container import build_container
from lumos.providers.ollama import OllamaProvider


def make_settings(tmp_path: Path, **overrides) -> Settings:
    kwargs: dict = {
        "database_path": tmp_path / "lumos.db",
        "notes_path": tmp_path / "notes",
        "web_search_provider": "disabled",
        "ingest_notes_on_startup": False,
        # Pin secrets to None so keys in the developer's real environment
        # cannot change test outcomes.
        "ollama_api_key": None,
        "cloud_api_key": None,
    }
    kwargs.update(overrides)
    settings = Settings(_env_file=None, **kwargs)
    settings.ensure_directories()
    return settings


def test_cloud_mode_resolves_cloud_defaults(tmp_path: Path):
    settings = make_settings(tmp_path, ollama_mode="cloud")
    assert settings.resolved_ollama_base_url == "https://ollama.com"
    assert settings.resolved_ollama_model == "gpt-oss:20b"


def test_local_mode_resolves_local_defaults(tmp_path: Path):
    settings = make_settings(tmp_path, ollama_mode="local")
    assert settings.resolved_ollama_base_url == "http://127.0.0.1:11434"
    assert settings.resolved_ollama_model == "qwen3:1.7b"


def test_explicit_overrides_beat_mode_defaults(tmp_path: Path):
    settings = make_settings(
        tmp_path,
        ollama_mode="cloud",
        ollama_base_url="http://192.168.1.20:11434",
        ollama_model="llama3.2:3b",
    )
    assert settings.resolved_ollama_base_url == "http://192.168.1.20:11434"
    assert settings.resolved_ollama_model == "llama3.2:3b"


def test_cloud_mode_without_key_leaves_ollama_unconfigured(tmp_path: Path):
    settings = make_settings(tmp_path, ollama_mode="cloud", ollama_api_key=None)
    container = build_container(settings)
    assert container.providers.local is None
    assert container.providers.fallback is not None  # echo still answers


def test_cloud_mode_with_key_builds_authed_provider(tmp_path: Path):
    settings = make_settings(tmp_path, ollama_mode="cloud", ollama_api_key="test-key")
    container = build_container(settings)
    provider = container.providers.local
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama-cloud"
    assert provider.base_url == "https://ollama.com"
    assert provider.model == "gpt-oss:20b"
    assert provider._headers == {"Authorization": "Bearer test-key"}


def test_local_mode_needs_no_key_and_sends_no_auth(tmp_path: Path):
    # A key present in the environment must not leak into local requests.
    settings = make_settings(tmp_path, ollama_mode="local", ollama_api_key="test-key")
    container = build_container(settings)
    provider = container.providers.local
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider._headers == {}


def test_fallback_defaults_point_at_openrouter(tmp_path: Path):
    settings = make_settings(tmp_path)
    assert settings.cloud_base_url == "https://openrouter.ai/api/v1"
    # No key -> no fallback provider is constructed.
    container = build_container(settings)
    assert container.providers.cloud is None
