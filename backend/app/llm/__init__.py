"""
LLM 调用模块
支持 OpenAI 兼容 API（DeepSeek）

包含指数退避重试机制，处理：
- API 速率限制（429）
- 临时网络错误
- 服务器错误（5xx）
- JSON 解析错误
"""
import asyncio
import logging
import time
from typing import TypeVar, Type, Any, Callable
from openai import AsyncOpenAI
from pydantic import BaseModel
import json

from ..config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, DEFAULT_TEMPERATURE,
    calculate_llm_cost,
)

logger = logging.getLogger(__name__)

# 延迟初始化客户端（在第一次使用时创建）
_client = None


def _get_client() -> AsyncOpenAI:
    """获取 LLM 客户端（延迟初始化）"""
    global _client
    if _client is None:
        if not DEEPSEEK_API_KEY:
            raise ValueError(
                "DEEPSEEK_API_KEY is not set. "
                "Please set the environment variable."
            )
        _client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        logger.info("LLM client initialized")
    return _client


T = TypeVar("T", bound=BaseModel)


class LLMParseError(Exception):
    """LLM 输出解析错误"""
    pass


class LLMRateLimitError(Exception):
    """LLM API 速率限制错误"""
    pass


async def _retry_with_backoff(
    func: Callable,
    *args,
    is_parse_error: bool = False,
    **kwargs
) -> Any:
    """
    带指数退避的重试装饰器

    处理可重试的临时错误，包括：
    - JSON 解析错误
    - API 速率限制（429）
    - 服务器错误（5xx）
    - 网络连接错误

    重试策略：
    - JSON 解析错误：立即重试（延迟 0.1s, 0.2s, 0.3s）
    - 速率限制：指数退避并加倍延迟（2s, 4s, 8s）
    - 服务器/网络错误：标准指数退避（1s, 2s, 4s）

    Args:
        func: 要重试的异步函数
        is_parse_error: 是否为解析错误（解析错误不等待，直接重试）
        *args: 函数位置参数
        **kwargs: 函数关键字参数

    Returns:
        函数返回值

    Raises:
        Exception: 重试失败后的最后一次错误

    Examples:
        >>> result = await _retry_with_backoff(llm_client.generate, prompt="test")
        >>> data = await _retry_with_backoff(
        ...     lambda: json.loads(response.text),
        ...     is_parse_error=True
        ... )
    """
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            return await func(*args, **kwargs)
        except json.JSONDecodeError as e:
            last_error = e
            if attempt < MAX_RETRIES:
                logger.warning(f"JSON parse error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}")
                # 解析错误不等待，直接重试
                await asyncio.sleep(0.1 * (attempt + 1))
            continue
        except Exception as e:
            last_error = e

            # 检查是否为可重试的错误
            error_str = str(e).lower()
            is_rate_limit = any(x in error_str for x in ["429", "rate limit", "too many requests"])
            is_server_error = any(x in error_str for x in ["500", "502", "503", "504", "server error"])
            is_network_error = any(x in error_str for x in ["connection", "timeout", "network"])

            if not (is_rate_limit or is_server_error or is_network_error):
                # 不可重试的错误，直接抛出
                raise

            if attempt < MAX_RETRIES:
                # 计算退避时间：指数增长，最大 MAX_DELAY
                delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                if is_rate_limit:
                    delay = min(delay * 2, MAX_DELAY)  # 速率限制时加倍延迟
                    logger.warning(f"Rate limit hit (attempt {attempt + 1}/{MAX_RETRIES + 1}), waiting {delay:.1f}s")
                else:
                    logger.warning(f"Retryable error (attempt {attempt + 1}/{MAX_RETRIES + 1}): {e}, waiting {delay:.1f}s")

                await asyncio.sleep(delay)
            else:
                logger.error(f"Max retries ({MAX_RETRIES}) exceeded for: {e}")

    raise last_error


async def chat_json(
    system: str,
    user: str,
    temperature: float = DEFAULT_TEMPERATURE,
    response_format: dict = None,
    max_retries: int = MAX_RETRIES,
    model: str = None,
    max_tokens: int = 8192,
) -> dict:
    """
    调用 LLM 并确保返回 JSON

    包含指数退避重试机制，处理：
    - API 速率限制（429）
    - 临时网络错误
    - 服务器错误（5xx）
    - JSON 解析错误

    Args:
        system: 系统提示词
        user: 用户输入
        temperature: 温度参数
        response_format: 响应格式，默认 {"type": "json_object"}
        max_retries: 最大重试次数
        model: 模型名称
        max_tokens: 单次响应最大 tokens。默认 8192（DeepSeek-chat 输出上限），
            显式覆盖即可调小。API 实际只按生成量计费，所以设大不会浪费成本。
            历史上发生过 highlight/summary 在长节目里被默认 4K 截断导致 JSON 解析失败。

    Returns:
        解析后的 JSON 对象

    Raises:
        LLMParseError: JSON 解析失败
    """
    if model is None:
        model = DEEPSEEK_MODEL
    if response_format is None:
        response_format = {"type": "json_object"}

    async def _do_call() -> dict:
        start_time = time.time()

        client = _get_client()
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": response_format,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = await client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content
        latency_ms = int((time.time() - start_time) * 1000)

        # 检测是否因 max_tokens 截断；这类截断会让 JSON 解析必然失败，
        # 重试也救不回来（每次都会被同一根线截断）。提早抛出明确错误，
        # 让调用方知道是输出超限，而不是 LLM"返回坏 JSON"。
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            raise LLMParseError(
                f"Response truncated by max_tokens={max_tokens or 'default'} "
                f"(finish_reason=length). Output length so far: {len(content)} chars. "
                f"Increase max_tokens or split the workload."
            )

        # 解析 JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 代码块
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)

        # 记录成本信息
        usage = response.usage
        data["_meta"] = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cost_usd": calculate_llm_cost(model, usage.prompt_tokens, usage.completion_tokens),
            "latency_ms": latency_ms,
        }

        return data

    try:
        return await _retry_with_backoff(_do_call)
    except Exception as e:
        raise LLMParseError(f"Failed to get valid JSON response: {e}")


async def chat_structured(
    system: str,
    user: str,
    response_model: Type[T],
    temperature: float = DEFAULT_TEMPERATURE,
    model: str = None,
    max_tokens: int = 8192,
) -> T:
    """
    调用 LLM 并返回结构化对象（使用 structured outputs）

    包含指数退避重试机制，处理：
    - API 速率限制（429）
    - 临时网络错误
    - 服务器错误（5xx）

    Args:
        system: 系统提示词
        user: 用户输入
        response_model: Pydantic 模型类
        temperature: 温度参数
        model: 模型名称
        max_tokens: 单次响应最大 tokens，默认 8192（同 chat_json）

    Returns:
        解析后的 Pydantic 对象
    """
    if model is None:
        model = DEEPSEEK_MODEL

    async def _do_call() -> T:
        start_time = time.time()

        client = _get_client()
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = await client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content
        latency_ms = int((time.time() - start_time) * 1000)

        data = json.loads(content)
        obj = response_model.model_validate(data)

        # 添加元数据
        usage = response.usage
        obj._meta = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cost_usd": calculate_llm_cost(model, usage.prompt_tokens, usage.completion_tokens),
            "latency_ms": latency_ms,
        }

        return obj

    try:
        return await _retry_with_backoff(_do_call)
    except Exception as e:
        raise LLMParseError(f"Failed to get structured response: {e}")
