"""protocols 单元测试：两个 adapter 的请求塑形 + 响应归一化（mock SDK，无网络）。"""
import pytest

from app.llm.protocols import LLMResponse, OpenAIAdapter, AnthropicAdapter


# ---------- OpenAIAdapter ----------

class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, finish_reason):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeOpenAIResponse:
    def __init__(self, content, finish_reason="stop", model="deepseek-chat", p=10, c=20):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.model = model
        self.usage = _FakeUsage(p, c)


class _FakeChatCompletions:
    def __init__(self, create_ret):
        self._ret = create_ret
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ret


class _FakeOpenAIClient:
    def __init__(self, create_ret):
        self.chat = type("C", (), {"completions": _FakeChatCompletions(create_ret)})()


@pytest.mark.asyncio
async def test_openai_adapter_passes_response_format_and_returns_llmresponse(monkeypatch):
    fake = _FakeOpenAIClient(_FakeOpenAIResponse('{"k": 1}', finish_reason="stop"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: fake)

    adapter = OpenAIAdapter(api_key="sk", base_url="https://api.deepseek.com", timeout=60)
    resp = await adapter.complete(
        model="deepseek-chat",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        temperature=0.3, max_tokens=8192,
        response_format={"type": "json_object"},
    )
    assert isinstance(resp, LLMResponse)
    assert resp.content == '{"k": 1}'
    assert resp.finish_reason == "stop"
    assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    assert resp.cost_usd > 0
    # response_format 必须透传给 SDK
    assert fake.chat.completions.last_kwargs["response_format"] == {"type": "json_object"}
    assert fake.chat.completions.last_kwargs["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_openai_adapter_omits_max_tokens_when_none(monkeypatch):
    fake = _FakeOpenAIClient(_FakeOpenAIResponse("ok"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: fake)
    adapter = OpenAIAdapter(api_key="sk", base_url="", timeout=60)
    await adapter.complete(
        model="m", messages=[{"role": "user", "content": "u"}],
        temperature=0.3, max_tokens=None, response_format=None,
    )
    assert "max_tokens" not in fake.chat.completions.last_kwargs


# ---------- AnthropicAdapter ----------

class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeAnthropicUsage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _FakeAnthropicResponse:
    def __init__(self, text, stop_reason="end_turn", model="claude-3-5-sonnet-latest"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.model = model
        self.usage = _FakeAnthropicUsage(12, 34)


class _FakeMessages:
    def __init__(self, create_ret):
        self._ret = create_ret
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ret


class _FakeAnthropicClient:
    def __init__(self, create_ret):
        self.messages = _FakeMessages(create_ret)


@pytest.mark.asyncio
async def test_anthropic_adapter_extracts_system_and_maps_roles(monkeypatch):
    fake = _FakeAnthropicClient(_FakeAnthropicResponse("hello", stop_reason="end_turn"))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: fake)

    adapter = AnthropicAdapter(api_key="sk-ant", base_url="", timeout=60)
    resp = await adapter.complete(
        model="claude-3-5-sonnet-latest",
        messages=[{"role": "system", "content": "be brief"},
                  {"role": "user", "content": "hi"}],
        temperature=0.3, max_tokens=None,
        response_format={"type": "json_object"},  # 必须被忽略
    )
    assert resp.content == "hello"
    assert resp.finish_reason == "stop"          # end_turn → stop
    assert resp.usage["total_tokens"] == 12 + 34
    kw = fake.messages.last_kwargs
    # system 提到顶层；messages 只剩 user
    assert kw["system"] == "be brief"
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    # max_tokens 必填 → adapter 兜底 8192
    assert kw["max_tokens"] == 8192
    # response_format 不可透传（Anthropic 无原生 JSON 模式）
    assert "response_format" not in kw


@pytest.mark.asyncio
async def test_anthropic_adapter_normalizes_stop_reasons(monkeypatch):
    for raw, want in [("end_turn", "stop"), ("stop_sequence", "stop"),
                      ("max_tokens", "length"), ("pause_turn", "length"),
                      ("tool_use", "tool_calls"), ("refusal", "refusal")]:
        fake = _FakeAnthropicClient(_FakeAnthropicResponse("x", stop_reason=raw))
        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: fake)
        adapter = AnthropicAdapter(api_key="sk", base_url="", timeout=60)
        resp = await adapter.complete(
            model="claude", messages=[{"role": "user", "content": "x"}],
            temperature=0.3, max_tokens=100, response_format=None,
        )
        assert resp.finish_reason == want


# ---------- 安全：SDK 客户端不得跟随重定向 ----------
# openai/anthropic SDK 默认 follow_redirects=True（实测 openai 2.41.0）。恶意兼容端点
# 可 302 → 内网/云元数据，httpx 跨域重定向只剥 Authorization/Cookie、不剥 x-api-key，
# 导致 LLM Key 被拖到内网目标。构造 SDK 客户端时强制关闭重定向。

def test_openai_adapter_disables_redirects():
    import httpx
    adapter = OpenAIAdapter(api_key="sk-x", base_url="https://api.deepseek.com", timeout=30.0)
    inner = adapter._client._client  # AsyncOpenAI._client -> httpx.AsyncClient
    assert isinstance(inner, httpx.AsyncClient)
    assert inner.follow_redirects is False


def test_anthropic_adapter_disables_redirects():
    # 当前环境 anthropic SDK 与 httpx 版本失配（proxies kwarg），构造可能失败；
    # 依赖修复后此测试锁定「不跟随重定向」，失配时跳过并在汇报中单独标记。
    import httpx
    try:
        adapter = AnthropicAdapter(api_key="sk-x", base_url="https://api.anthropic.com", timeout=30.0)
    except TypeError as e:
        if "proxies" in str(e):
            pytest.skip("anthropic SDK/httpx 版本失配，待修复依赖（见汇报）")
        raise
    inner = adapter._client._client  # AsyncAnthropic._client -> httpx.AsyncClient
    assert isinstance(inner, httpx.AsyncClient)
    assert inner.follow_redirects is False
