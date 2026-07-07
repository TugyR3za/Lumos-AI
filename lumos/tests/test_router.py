import pytest

from lumos.providers.base import ProviderError, ProviderResponse
from lumos.providers.echo import EchoProvider
from lumos.providers.router import ProviderRouter


class FakeProvider:
    def __init__(self, name: str, fail: bool = False):
        self.name = name
        self.model = f"{name}-model"
        self.fail = fail

    async def is_available(self) -> bool:
        return not self.fail

    async def chat(self, messages, tools=None):
        if self.fail:
            raise ProviderError(f"{self.name} failed")
        return ProviderResponse("ok", self.name, self.model)


@pytest.mark.asyncio
async def test_auto_falls_back_to_cloud_after_local_error():
    router = ProviderRouter(
        local=FakeProvider("local", fail=True),
        cloud=FakeProvider("cloud"),
    )
    response = await router.chat([{"role": "user", "content": "hello"}], None, "auto")
    assert response.provider == "cloud"


@pytest.mark.asyncio
async def test_local_mode_does_not_fallback():
    router = ProviderRouter(
        local=FakeProvider("local", fail=True),
        cloud=FakeProvider("cloud"),
    )
    with pytest.raises(ProviderError):
        await router.chat([{"role": "user", "content": "hello"}], None, "local")


@pytest.mark.asyncio
async def test_auto_uses_echo_after_all_providers_fail():
    router = ProviderRouter(
        local=FakeProvider("local", fail=True),
        cloud=FakeProvider("cloud", fail=True),
        fallback=EchoProvider(),
    )
    response = await router.chat([{"role": "user", "content": "hello there"}], None, "auto")
    assert response.provider == "echo"
    assert "hello there" in response.content


@pytest.mark.asyncio
async def test_auto_uses_echo_when_nothing_is_configured():
    router = ProviderRouter(local=None, cloud=None, fallback=EchoProvider())
    response = await router.chat([{"role": "user", "content": "hi"}], None, "auto")
    assert response.provider == "echo"


@pytest.mark.asyncio
async def test_auto_prefers_real_provider_over_echo():
    router = ProviderRouter(
        local=FakeProvider("local"),
        cloud=None,
        fallback=EchoProvider(),
    )
    response = await router.chat([{"role": "user", "content": "hello"}], None, "auto")
    assert response.provider == "local"


@pytest.mark.asyncio
async def test_explicit_routes_never_reach_echo():
    router = ProviderRouter(local=None, cloud=None, fallback=EchoProvider())
    for route in ("local", "cloud"):
        with pytest.raises(ProviderError):
            await router.chat([{"role": "user", "content": "hello"}], None, route)


@pytest.mark.asyncio
async def test_status_reports_fallback_slot():
    router = ProviderRouter(local=None, cloud=None, fallback=EchoProvider())
    status = await router.status()
    assert status["fallback"] == {
        "configured": True,
        "available": True,
        "provider": "echo",
        "model": "echo-fallback",
    }
    assert status["local"] == {"configured": False, "available": False}
