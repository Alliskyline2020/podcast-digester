"""client.complete 单元测试：provider_type 分发 + 重试 + 错误翻译（mock adapter）。"""
import pytest

import app.llm.client as client_module
from app.llm.protocols import LLMResponse


def _ok_response(content='{"a":1}'):
    return LLMResponse(content=content, model="deepseek-chat",
                       usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
                       finish_reason="stop", cost_usd=0.01)


@pytest.mark.asyncio
async def test_complete_dispatches_to_openai_adapter_for_deepseek(monkeypatch):
    calls = []

    class FakeAdapter:
        async def complete(self, **kw):
            calls.append(kw)
            return _ok_response()

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: FakeAdapter())
    # 绕过真实 get_config：注入一个最小配置
    from app.llm.config import LLMConfig
    fake_cfg = LLMConfig("deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
                         "deepseek-chat", 0.3, None, 60.0)
    monkeypatch.setattr(client_module, "get_config", lambda: fake_cfg)

    resp = await client_module.complete(
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )
    assert resp.content == '{"a":1}'
    assert calls[0]["model"] == "deepseek-chat"
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_complete_retries_on_rate_limit_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    class FlakyAdapter:
        async def complete(self, **kw):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise Exception("429 Too Many Requests")  # 可重试
            return _ok_response()

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: FlakyAdapter())
    from app.llm.config import LLMConfig
    monkeypatch.setattr(client_module, "get_config", lambda: LLMConfig(
        "deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
        "deepseek-chat", 0.3, None, 60.0))
    # 加速测试：把退避延迟压到 ~0
    monkeypatch.setattr(client_module, "BASE_DELAY", 0.0)
    monkeypatch.setattr(client_module, "MAX_DELAY", 0.0)

    resp = await client_module.complete(messages=[{"role": "user", "content": "x"}])
    assert attempts["n"] == 3
    assert resp.content == '{"a":1}'


@pytest.mark.asyncio
async def test_complete_does_not_retry_on_non_retryable(monkeypatch):
    attempts = {"n": 0}

    class BadAdapter:
        async def complete(self, **kw):
            attempts["n"] += 1
            raise Exception("Invalid API key")  # 不可重试

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: BadAdapter())
    from app.llm.config import LLMConfig
    monkeypatch.setattr(client_module, "get_config", lambda: LLMConfig(
        "deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
        "deepseek-chat", 0.3, None, 60.0))

    with pytest.raises(Exception, match="Invalid API key"):
        await client_module.complete(messages=[{"role": "user", "content": "x"}])
    assert attempts["n"] == 1  # 没重试


@pytest.mark.asyncio
async def test_retry_with_backoff_skips_api_retry_when_retry_api_false(monkeypatch):
    """当 retry_api=False 时，不重试可重试的 API 错误（如 429）。"""
    import json
    attempts = {"n": 0}

    async def raise_429():
        attempts["n"] += 1
        raise Exception("429 Too Many Requests")

    # 加速测试：把退避延迟压到 ~0
    monkeypatch.setattr(client_module, "BASE_DELAY", 0.0)
    monkeypatch.setattr(client_module, "MAX_DELAY", 0.0)

    with pytest.raises(Exception, match="429 Too Many Requests"):
        await client_module._retry_with_backoff(
            raise_429, retry_on_json=True, retry_api=False
        )

    # retry_api=False 时，可重试的 API 错误也不重试，直接抛出
    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_retry_with_backoff_retries_json_when_retry_on_json_true_and_retry_api_false(monkeypatch):
    """当 retry_on_json=True 且 retry_api=False 时，仅重试 JSON 解析错误，不重试 API 错误。"""
    import json
    attempts = {"n": 0}

    async def raise_json_then_ok():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise json.JSONDecodeError("bad json", "doc", 0)
        return {"ok": True}

    # 加速测试：把退避延迟压到 ~0
    monkeypatch.setattr(client_module, "BASE_DELAY", 0.0)
    monkeypatch.setattr(client_module, "MAX_DELAY", 0.0)

    result = await client_module._retry_with_backoff(
        raise_json_then_ok, retry_on_json=True, retry_api=False
    )

    assert result == {"ok": True}
    assert attempts["n"] == 3  # 前两次 JSONDecodeError，第三次成功
