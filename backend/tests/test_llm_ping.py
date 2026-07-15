"""ping_llm: 连通性探测。"""
import pytest

from app.llm.config import LLMConfig
from app.llm.protocols import LLMResponse


def _cfg():
    return LLMConfig(
        provider="deepseek", provider_type="openai_compatible", api_key="sk-x",
        base_url="https://api.deepseek.com", model="deepseek-chat",
        temperature=0.3, max_tokens=None, timeout=60.0,
    )


@pytest.mark.llm
async def test_ping_success(monkeypatch):
    import app.llm.client as client

    class _Ok:
        async def complete(self, *, model, messages, temperature, max_tokens, response_format):
            return LLMResponse(content="pong", model=model, usage={},
                               finish_reason="stop", cost_usd=0.0)

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Ok())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is True
    assert "连通" in detail


@pytest.mark.llm
async def test_ping_auth_failure(monkeypatch):
    import app.llm.client as client

    class _AuthFail:
        async def complete(self, **kwargs):
            raise Exception("401 Unauthorized: invalid api key")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _AuthFail())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is False
    assert "API Key" in detail or "401" in detail


@pytest.mark.llm
async def test_ping_timeout(monkeypatch):
    import app.llm.client as client

    class _Timeout:
        async def complete(self, **kwargs):
            raise Exception("connection timeout")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Timeout())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is False
    assert "超时" in detail or "timeout" in detail.lower()
