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
    # DeepSeek —— V4 系列（当前主力）。定价来源（每 1M tokens，cache miss 输入价）：
    # https://api-docs.deepseek.com/quick_start/pricing （2026/07 核对）
    # 注意：deepseek-chat / deepseek-reasoner 旧名将于 2026/07/24 15:59 UTC 废弃，
    # 分别别名映射到 deepseek-v4-flash 的非思考/思考模式，故三者输入/输出单价同档。
    # 原 deepseek-reasoner 的 $0.55/$2.19 是 R1 价，随 R1 下线作废。
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},   # DeepSeek-V4-Flash（默认开思考模式）
    "deepseek-v4-pro": {"input": 0.435, "output": 0.87},     # DeepSeek-V4-Pro
    "deepseek-chat": {"input": 0.14, "output": 0.28},        # 旧名 → v4-flash 非思考模式
    "deepseek-reasoner": {"input": 0.14, "output": 0.28},    # 旧名 → v4-flash 思考模式
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
