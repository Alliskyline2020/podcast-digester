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


async def _retry_with_backoff(func, *, retry_on_json: bool = False, retry_api: bool = True):
    """指数退避重试。仅重试可重试错误（_is_retryable）。

    retry_on_json=True 时也重试 json.JSONDecodeError（供 chat_json 包住 parse 用）。
    retry_api=False 时跳过 API 错误重试（避免与 complete() 内部重试嵌套）。
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
            if not retry_api or not _is_retryable(e) or attempt >= MAX_RETRIES:
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


def _humanize_llm_error(err: Exception) -> str:
    """把 SDK/网络错误翻译成给用户看的一句话。"""
    s = str(err).lower()
    if "401" in s or "invalid api key" in s or "unauthorized" in s:
        return "API Key 无效或未授权（401）"
    if "403" in s or "forbidden" in s:
        return "拒绝访问（403），可能是 Key 无该模型权限"
    if "404" in s or "model" in s and "not found" in s:
        return "模型名或端点不对（404）"
    if "timeout" in s or "timed out" in s:
        return "请求超时（检查网络或 base_url 是否可达）"
    if "connection" in s or "name or service" in s or "getaddrinfo" in s:
        return "无法连接到该 API 地址（域名不通 / base_url 错误）"
    return f"请求失败：{err}"


async def ping_llm(cfg: LLMConfig) -> tuple[bool, str]:
    """用给定配置发一个极小请求，验证 key/端点/模型可用。

    用传入的 cfg（而非 get_config()），这样能测「未保存的草稿值」。
    返回 (ok, 中文说明)。
    """
    adapter = _get_adapter(cfg, min(cfg.timeout, 15.0))
    try:
        resp = await adapter.complete(
            model=cfg.model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=5,
            response_format=None,
        )
        return True, f"连通（模型 {resp.model}）"
    except Exception as e:
        return False, _humanize_llm_error(e)
