"""LLM 成本核算：按 (模型, 输入/输出 token) 查价格表。

未知模型返回 0.0 并打 warning（spec: unknown → 0.0 + warn），
让 per-episode 预算守护 `_meta.cost_usd` 始终有值、永不崩。
价格单位：USD per 1,000,000 tokens。来源：各厂商官网定价页（impl 时核对）。
"""
import logging

logger = logging.getLogger(__name__)

# 价格表：USD per 1M tokens。新增 provider 时按官方定价页补条目。
# 字段含义：{"input": 输入单价, "output": 输出单价}
COST_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Anthropic
    "claude-3-5-sonnet-latest": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-latest": {"input": 0.80, "output": 4.00},
    # GLM (智谱)
    "glm-4-flash": {"input": 0.10, "output": 0.10},
    "glm-4": {"input": 3.50, "output": 3.50},
    # 通义千问
    "qwen-plus": {"input": 0.40, "output": 1.20},
    # 月之暗面
    "moonshot-v1-8k": {"input": 1.70, "output": 1.70},
}


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """计算单次 LLM 调用成本（美元）。

    未知模型返回 0.0 并 warning（不抛异常，保证预算守护逻辑不崩）。
    """
    rates = COST_PER_1M_TOKENS.get(model)
    if rates is None:
        logger.warning(
            "cost: 未知模型 %r，按 0.0 计费。请在 COST_PER_1M_TOKENS 补条目。", model
        )
        return 0.0
    return (prompt_tokens / 1_000_000) * rates["input"] + \
           (completion_tokens / 1_000_000) * rates["output"]
