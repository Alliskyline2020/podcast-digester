"""
LLM 调用包。

公共入口：
- complete():            统一底层调用（分发 OpenAI/Anthropic adapter + 重试）
- chat_json():           调 LLM 并确保返回解析后的 JSON（向后兼容旧调用）
- chat_structured():     调 LLM 返回 Pydantic 结构化对象
- get_config():          读取 LLM 配置（provider/key/base_url/model/...）

所有模型调用都过 complete()。messages 永远是 OpenAI 形态；Anthropic adapter 内部转换。
"""
import json
import logging
import time
from typing import TypeVar, Type

from .client import complete, _retry_with_backoff
from .config import get_config
from .cost import cost as calculate_llm_cost  # 向后兼容：旧代码可能 from app.llm import calculate_llm_cost
from .protocols import LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LLMParseError(Exception):
    """LLM 输出解析错误。"""
    pass


class LLMRateLimitError(Exception):
    """LLM API 速率限制错误。"""
    pass


async def chat_json(
    system: str,
    user: str,
    temperature: float | None = None,
    response_format: dict | None = None,
    max_retries: int | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
) -> dict:
    """调用 LLM 并确保返回解析后的 JSON。

    通过 complete() 发起调用（complete 内部重试瞬态 API 错误），再做 JSON 解析。
    解析失败时尝试提取 ```json 代码块兜底；仍失败抛 LLMParseError。
    max_tokens 截断（finish_reason=length）直接抛 LLMParseError（重试也救不回）。
    """
    if response_format is None:
        response_format = {"type": "json_object"}

    async def _do_call() -> dict:
        start_time = time.time()
        resp = await complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        content = resp.content
        latency_ms = int((time.time() - start_time) * 1000)

        if resp.finish_reason == "length":
            raise LLMParseError(
                f"Response truncated by max_tokens={max_tokens} "
                f"(finish_reason=length). Output length so far: {len(content)} chars. "
                f"Increase max_tokens or split the workload."
            )

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 提取 ```json / ``` 代码块兜底（Anthropic 无原生 JSON 模式时尤其重要）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)  # 仍失败则抛 JSONDecodeError → 由外层重试/抛出

        data["_meta"] = {
            "prompt_tokens": resp.usage["prompt_tokens"],
            "completion_tokens": resp.usage["completion_tokens"],
            "total_tokens": resp.usage["total_tokens"],
            "cost_usd": resp.cost_usd,
            "latency_ms": latency_ms,
        }
        return data

    try:
        # complete() 已重试 API 错误；这里 retry_on_json=True 让坏 JSON 也触发整体重试
        # retry_api=False 避免与 complete() 内部重试嵌套（仅重试 JSON 解析错误）
        return await _retry_with_backoff(_do_call, retry_on_json=True, retry_api=False)
    except LLMParseError:
        raise
    except Exception as e:
        raise LLMParseError(f"Failed to get valid JSON response: {e}")


async def chat_structured(
    system: str,
    user: str,
    response_model: Type[T],
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
) -> T:
    """调用 LLM 并返回 Pydantic 结构化对象（OpenAI json_schema 模式）。"""
    async def _do_call() -> T:
        start_time = time.time()
        resp = await complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        )
        latency_ms = int((time.time() - start_time) * 1000)
        data = json.loads(resp.content)
        obj = response_model.model_validate(data)
        obj._meta = {
            "prompt_tokens": resp.usage["prompt_tokens"],
            "completion_tokens": resp.usage["completion_tokens"],
            "total_tokens": resp.usage["total_tokens"],
            "cost_usd": resp.cost_usd,
            "latency_ms": latency_ms,
        }
        return obj

    try:
        # complete() 已重试 API 错误；retry_api=False 避免与内部重试嵌套（仅重试 JSON 解析错误）
        return await _retry_with_backoff(_do_call, retry_on_json=True, retry_api=False)
    except Exception as e:
        raise LLMParseError(f"Failed to get structured response: {e}")


__all__ = [
    "complete", "chat_json", "chat_structured", "get_config",
    "LLMResponse", "LLMParseError", "LLMRateLimitError", "calculate_llm_cost",
]
