"""协议适配层：把统一的 complete() 请求塑形成各家 SDK 的形状，再归一化响应。

两个 adapter 共享同一签名 complete(*, model, messages, temperature, max_tokens,
response_format) -> LLMResponse，使 client.complete() 可按 provider_type 无脑分发。

- OpenAIAdapter：response_format 透传（OpenAI 兼容端点支持 json_object/json_schema）。
- AnthropicAdapter：response_format 忽略（无原生 JSON 模式，靠 prompt + 上层 fenced
  代码块抽取兜底）；system 抽到顶层；max_tokens 必填故兜底 8192。
"""
from dataclasses import dataclass
from typing import Optional

from .cost import cost


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict               # {prompt_tokens, completion_tokens, total_tokens}
    finish_reason: str        # 归一化：stop | length | content_filter | refusal | ...
    cost_usd: float


class OpenAIAdapter:
    """openai.AsyncOpenAI 包装。覆盖 DeepSeek/OpenAI/GLM/通义/豆包/月之暗面等。"""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        from openai import AsyncOpenAI
        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def complete(self, *, model, messages, temperature, max_tokens,
                       response_format) -> LLMResponse:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = await self._client.chat.completions.create(**kwargs)
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=resp.model or model,
            usage=usage,
            finish_reason=resp.choices[0].finish_reason or "stop",
            cost_usd=cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        )


def _split_system(messages):
    """把 OpenAI 风格 messages 拆成 (system_str, conversation[])。

    Anthropic 要求 system 在顶层、messages 只含 user/assistant。
    管线是单轮 [system, user]，无需处理多轮交替修复。
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    conv = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        conv.append({"role": "assistant" if role == "assistant" else "user",
                     "content": m["content"]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, conv


def _normalize_stop_reason(stop_reason: Optional[str]) -> str:
    """Anthropic stop_reason → 统一 finish_reason。

    pause_turn（系统暂停长输出）归一化为 length：内容被截断、JSON 不完整，
    与 max_tokens 同等对待，使 chat_json 立即给出"截断，需增大 max_tokens"的
    清晰错误，而非对坏 JSON 重试。tool_use/refusal 为未来扩展覆盖。
    """
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "pause_turn": "length",
        "tool_use": "tool_calls",
        "refusal": "refusal",
    }.get(stop_reason or "", stop_reason or "stop")


class AnthropicAdapter:
    """anthropic.AsyncAnthropic 包装。"""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)

    async def complete(self, *, model, messages, temperature, max_tokens,
                       response_format) -> LLMResponse:
        # response_format 故意忽略：Anthropic 无原生 JSON 模式。
        system, conv = _split_system(messages)
        create_kwargs = {
            "model": model,
            "messages": conv,
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens is not None else 8192,
        }
        if system is not None:
            create_kwargs["system"] = system
        resp = await self._client.messages.create(**create_kwargs)
        content = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )
        usage = {
            "prompt_tokens": resp.usage.input_tokens,
            "completion_tokens": resp.usage.output_tokens,
            "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
        }
        return LLMResponse(
            content=content,
            model=resp.model or model,
            usage=usage,
            finish_reason=_normalize_stop_reason(resp.stop_reason),
            cost_usd=cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        )
