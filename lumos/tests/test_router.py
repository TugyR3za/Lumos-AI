import pytest

from lumos.providers.base import ProviderCheck, ProviderError, ProviderResponse
from lumos.providers.echo import EchoProvider
from lumos.providers.router import ProviderRouter


class FakeProvider:
    def __init__(self, name: str, fail: bool = False, check: ProviderCheck | None = None):
        self.name = name
        self.model = f"{name}-model"
        self.fail = fail
        self._check = check or ProviderCheck("available")

    async def check(self) -> ProviderCheck:
        return self._check

    async def chat(self, messages, tools=None):
        if self.fail:
            raise ProviderError(f"{self.name} failed")
        return ProviderResponse("ok", self.name, self.model)


@pytest.mark.asyncio
async def test_auto_falls_back_after_primary_error():
    router = ProviderRouter(
        primary=FakeProvider("primary", fail=True),
        fallback=FakeProvider("fallback"),
    )
    response = await router.chat([{"role": "user", "content": "hello"}], None, "auto")
    assert response.provider == "fallback"


@pytest.mark.asyncio
async def test_local_route_does_not_fall_back():
    router = ProviderRouter(
        primary=FakeProvider("primary", fail=True),
        fallback=FakeProvider("fallback"),
    )
    with pytest.raises(ProviderError):
        await router.chat([{"role": "user", "content": "hello"}], None, "local")


@pytest.mark.asyncio
async def test_auto_uses_echo_after_all_providers_fail():
    router = ProviderRouter(
        primary=FakeProvider("primary", fail=True),
        fallback=FakeProvider("fallback", fail=True),
        echo=EchoProvider(),
    )
    response = await router.chat([{"role": "user", "content": "hello there"}], None, "auto")
    assert response.provider == "echo"
    assert "hello there" in response.content


@pytest.mark.asyncio
async def test_auto_uses_echo_when_nothing_is_configured():
    router = ProviderRouter(primary=None, fallback=None, echo=EchoProvider())
    response = await router.chat([{"role": "user", "content": "hi"}], None, "auto")
    assert response.provider == "echo"


@pytest.mark.asyncio
async def test_auto_prefers_real_provider_over_echo():
    router = ProviderRouter(
        primary=FakeProvider("primary"),
        fallback=None,
        echo=EchoProvider(),
    )
    response = await router.chat([{"role": "user", "content": "hello"}], None, "auto")
    assert response.provider == "primary"


@pytest.mark.asyncio
async def test_explicit_routes_never_reach_echo():
    router = ProviderRouter(primary=None, fallback=None, echo=EchoProvider())
    with pytest.raises(ProviderError, match="primary provider"):
        await router.chat([{"role": "user", "content": "hello"}], None, "local")
    with pytest.raises(ProviderError, match="fallback provider"):
        await router.chat([{"role": "user", "content": "hello"}], None, "cloud")


@pytest.mark.asyncio
async def test_status_uses_slot_names_and_states():
    router = ProviderRouter(primary=None, fallback=None, echo=EchoProvider())
    status = await router.status()
    assert set(status) == {"primary", "fallback", "echo"}
    assert status["echo"] == {
        "configured": True,
        "state": "available",
        "available": True,
        "detail": None,
        "provider": "echo",
        "model": "echo-fallback",
    }
    assert status["primary"] == {
        "configured": False,
        "state": "not_configured",
        "available": False,
    }


@pytest.mark.asyncio
async def test_status_surfaces_auth_failure_with_detail():
    failing_check = ProviderCheck("auth_failed", "HTTP 401 from /api/ps")
    router = ProviderRouter(
        primary=FakeProvider("primary", check=failing_check),
        fallback=None,
    )
    status = await router.status()
    assert status["primary"]["state"] == "auth_failed"
    assert status["primary"]["available"] is False
    assert status["primary"]["detail"] == "HTTP 401 from /api/ps"
