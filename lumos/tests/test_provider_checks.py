"""Probe (`check`) classification and chat auth handling for the HTTP providers.

ollama.com and openrouter.ai both serve their catalog endpoints without auth,
and ollama.com's /api/ps rejects valid API keys too (observed 2026-07-07), so
these tests pin the behavior that makes /status truthful: reachability-only
probing for Ollama, OpenRouter's auth-enforcing /key endpoint, and
chat-observed outcomes (sticky 401/403 failure, sticky verified success) as
the source of auth truth.
"""

import httpx
import pytest

from lumos.providers.base import ProviderAuthError
from lumos.providers.ollama import OllamaProvider
from lumos.providers.openai_compatible import OpenAICompatibleProvider

RouteSpec = tuple[int, dict | str | None]


def make_transport(routes: dict[str, RouteSpec | Exception], seen: list[str]):
    """MockTransport serving per-path responses; records every requested path."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        spec = routes.get(request.url.path, (404, None))
        if isinstance(spec, Exception):
            raise spec
        status_code, payload = spec
        if isinstance(payload, dict):
            return httpx.Response(status_code, json=payload)
        return httpx.Response(status_code, text=payload or "")

    return httpx.MockTransport(handler)


def cloud_ollama(routes: dict, seen: list[str]) -> OllamaProvider:
    return OllamaProvider(
        "https://ollama.com",
        "gpt-oss:20b",
        api_key="test-key",
        transport=make_transport(routes, seen),
    )


@pytest.mark.asyncio
async def test_cloud_probe_is_reachability_only():
    # Before any chat the key is unverified: the probe must say "reachable",
    # not "available", and must never call /api/ps (which 401s for valid keys
    # too on ollama.com).
    seen: list[str] = []
    provider = cloud_ollama({"/api/tags": (200, {"models": []})}, seen)
    check = await provider.check()
    assert check.state == "reachable"
    assert "not verified" in (check.detail or "")
    assert seen == ["/api/tags"]


@pytest.mark.asyncio
async def test_probe_401_from_enforcing_server_is_auth_failed():
    # ollama.com serves /api/tags publicly, but a private deployment behind an
    # authenticating proxy can enforce auth there — that 401 is a real signal.
    seen: list[str] = []
    provider = cloud_ollama({"/api/tags": (401, "unauthorized")}, seen)
    check = await provider.check()
    assert check.state == "auth_failed"
    assert "LUMOS_OLLAMA_API_KEY" in (check.detail or "")


@pytest.mark.asyncio
async def test_cloud_probe_reports_network_error_as_unreachable():
    seen: list[str] = []
    provider = cloud_ollama({"/api/tags": httpx.ConnectError("connection refused")}, seen)
    check = await provider.check()
    assert check.state == "unreachable"
    assert "connection refused" in (check.detail or "")


@pytest.mark.asyncio
async def test_successful_chat_upgrades_reachable_to_available():
    # Regression for the /api/ps misreport: a valid key showed "auth failed"
    # while chat worked. Status must track what chat actually does.
    seen: list[str] = []
    routes: dict = {
        "/api/tags": (200, {"models": []}),
        "/api/chat": (200, {"message": {"content": "hello"}, "model": "gpt-oss:20b"}),
    }
    provider = cloud_ollama(routes, seen)

    before = await provider.check()
    assert before.state == "reachable"

    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.content == "hello"

    after = await provider.check()
    assert after.state == "available"
    assert "verified by live chat" in (after.detail or "")


@pytest.mark.asyncio
async def test_local_probe_uses_tags_and_needs_no_auth():
    seen: list[str] = []
    provider = OllamaProvider(
        "http://127.0.0.1:11434",
        "qwen3:1.7b",
        transport=make_transport({"/api/tags": (200, {"models": []})}, seen),
    )
    check = await provider.check()
    assert check.state == "available"
    assert seen == ["/api/tags"]


@pytest.mark.asyncio
async def test_chat_401_raises_auth_error_and_sticks_in_check():
    seen: list[str] = []
    routes: dict = {
        "/api/chat": (401, "unauthorized"),
        # A healthy-looking reachability probe must not mask the chat failure.
        "/api/tags": (200, {"models": []}),
    }
    provider = cloud_ollama(routes, seen)

    with pytest.raises(ProviderAuthError):
        await provider.chat([{"role": "user", "content": "hi"}])

    check = await provider.check()
    assert check.state == "auth_failed"
    assert "/api/chat" in (check.detail or "")


@pytest.mark.asyncio
async def test_successful_chat_clears_recorded_auth_failure():
    seen: list[str] = []
    routes: dict = {"/api/chat": (401, "unauthorized"), "/api/tags": (200, {"models": []})}
    provider = cloud_ollama(routes, seen)

    with pytest.raises(ProviderAuthError):
        await provider.chat([{"role": "user", "content": "hi"}])
    routes["/api/chat"] = (200, {"message": {"content": "hello"}, "model": "gpt-oss:20b"})
    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.content == "hello"

    check = await provider.check()
    assert check.state == "available"
    assert "verified by live chat" in (check.detail or "")


def test_openai_compatible_name_derives_from_host():
    assert OpenAICompatibleProvider("https://openrouter.ai/api/v1", "k", "m").name == "openrouter"
    assert OpenAICompatibleProvider("https://api.openai.com/v1", "k", "m").name == "openai"
    assert OpenAICompatibleProvider("https://api.groq.com/openai/v1", "k", "m").name == "groq"
    assert (
        OpenAICompatibleProvider("https://llm.example.com/v1", "k", "m").name == "openai-compatible"
    )


@pytest.mark.asyncio
async def test_openrouter_probe_uses_key_endpoint():
    seen: list[str] = []
    provider = OpenAICompatibleProvider(
        "https://openrouter.ai/api/v1",
        "test-key",
        "openai/gpt-4o-mini",
        transport=make_transport({"/api/v1/key": (200, {"data": {}})}, seen),
    )
    check = await provider.check()
    assert check.state == "available"
    assert seen == ["/api/v1/key"]  # /models is public on OpenRouter


@pytest.mark.asyncio
async def test_openrouter_bad_key_is_auth_failed():
    seen: list[str] = []
    provider = OpenAICompatibleProvider(
        "https://openrouter.ai/api/v1",
        "bad-key",
        "openai/gpt-4o-mini",
        transport=make_transport({"/api/v1/key": (401, "no")}, seen),
    )
    check = await provider.check()
    assert check.state == "auth_failed"
    assert "LUMOS_CLOUD_API_KEY" in (check.detail or "")


@pytest.mark.asyncio
async def test_generic_host_probes_models():
    seen: list[str] = []
    provider = OpenAICompatibleProvider(
        "https://api.openai.com/v1",
        "test-key",
        "gpt-4o-mini",
        transport=make_transport({"/v1/models": (200, {"data": []})}, seen),
    )
    check = await provider.check()
    assert check.state == "available"
    assert seen == ["/v1/models"]


@pytest.mark.asyncio
async def test_openai_compatible_chat_401_raises_and_sticks():
    seen: list[str] = []
    provider = OpenAICompatibleProvider(
        "https://api.openai.com/v1",
        "bad-key",
        "gpt-4o-mini",
        transport=make_transport({"/v1/chat/completions": (401, "bad key")}, seen),
    )

    with pytest.raises(ProviderAuthError):
        await provider.chat([{"role": "user", "content": "hi"}])

    check = await provider.check()
    assert check.state == "auth_failed"
    assert "/chat/completions" in (check.detail or "")
