"""list_models: 拉取端点可用模型列表。"""
import pytest

from app.llm.config import LLMConfig


def _cfg():
    return LLMConfig(
        provider="deepseek", provider_type="openai_compatible", api_key="sk-x",
        base_url="https://api.deepseek.com", model="deepseek-chat",
        temperature=0.3, max_tokens=None, timeout=60.0,
    )


@pytest.mark.llm
async def test_list_models_success_dedup(monkeypatch):
    import app.llm.client as client

    class _Ok:
        async def list_models(self):
            return ["deepseek-chat", "deepseek-reasoner", "deepseek-chat"]  # 含重复

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Ok())
    ok, val = await client.list_models(_cfg())
    assert ok is True
    assert val == ["deepseek-chat", "deepseek-reasoner"]   # 去重保序


@pytest.mark.llm
async def test_list_models_auth_failure(monkeypatch):
    import app.llm.client as client

    class _Fail:
        async def list_models(self):
            raise Exception("401 Unauthorized: invalid api key")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Fail())
    ok, val = await client.list_models(_cfg())
    assert ok is False
    assert "API Key" in val or "401" in val


@pytest.mark.llm
async def test_list_models_timeout(monkeypatch):
    import app.llm.client as client

    class _Timeout:
        async def list_models(self):
            raise Exception("connection timeout")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Timeout())
    ok, val = await client.list_models(_cfg())
    assert ok is False
    assert "超时" in val or "timeout" in val.lower()
