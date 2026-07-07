import pytest

from lumos.providers.base import ProviderError, ProviderResponse
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
