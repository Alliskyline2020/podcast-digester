"""统一 LLM 调用入口 complete()：分发到对应协议 adapter + 指数退避重试 + 错误翻译。

所有模型调用（chat_json / chat_structured / 直接调用）都从这里过。
"""
import asyncio
import logging

from ..config import MAX_RETRIES, BASE_DELAY, MAX_DELAY
from .config import get_config, LLMConfig
from .protocols import LLMResponse, OpenAIAdapter, AnthropicAdapter

logger = logging.getLogger(__name__)


def _get_adapter(cfg: LLMConfig, timeout: float):
    """按 provider_type 选 adapter。客户端不缓存（配置可热更；成本可接受）。"""
    if cfg.provider_type == "anthropic_compatible":
        return AnthropicAdapter(cfg.api_key, cfg.base_url, timeout)
    return OpenAIAdapter(cfg.api_key, cfg.base_url, timeout)


def _is_retryable(err: Exception) -> bool:
    """429 / 5xx / 网络超时 可重试；其它（鉴权、参数错误）不重试。"""
    error_str = str(err).lower()
    return any(x in error_str for x in (
        "429", "rate limit", "too many requests",
        "500", "502", "503", "504", "server error",
        "connection", "timeout", "network", "temporarily",
    ))


async def _retry_with_backoff(func, *, retry_on_json: bool = False):
    """指数退避重试。仅重试可重试错误（_is_retryable）。

    retry_on_json=True 时也重试 json.JSONDecodeError（供 chat_json 包住 parse 用）。
    """
    import json  # 局部导入，避免非 JSON 路径强依赖
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await func()
        except json.JSONDecodeError as e:
            last_error = e
            if not retry_on_json or attempt >= MAX_RETRIES:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))
            continue
        except Exception as e:
            last_error = e
            if not _is_retryable(e) or attempt >= MAX_RETRIES:
                raise
            delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
            if "429" in str(e).lower():
                delay = min(delay * 2, MAX_DELAY)
            logger.warning(f"LLM 可重试错误 (第 {attempt + 1}/{MAX_RETRIES + 1} 次): {e}，{delay:.1f}s 后重试")
            await asyncio.sleep(delay)
    raise last_error


async def complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    timeout: float | None = None,
) -> LLMResponse:
    """统一 LLM 调用。参数留空则用 get_config() 的默认值。重试瞬态 API 错误。"""
    cfg = get_config()
    model = model or cfg.model
    temperature = cfg.temperature if temperature is None else temperature
    timeout = timeout or cfg.timeout
    adapter = _get_adapter(cfg, timeout)

    return await _retry_with_backoff(
        lambda: adapter.complete(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
    )
