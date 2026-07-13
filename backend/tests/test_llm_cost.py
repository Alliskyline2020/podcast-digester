"""cost() 单元测试：价格查表 + 未知模型兜底。"""
import logging

from app.llm.cost import cost, COST_PER_1M_TOKENS


def test_known_model_input_plus_output():
    # deepseek-chat: input 0.14 / output 0.28 per 1M (USD)
    c = cost("deepseek-chat", 1_000_000, 1_000_000)
    assert c == 0.14 + 0.28


def test_zero_tokens_is_zero_cost():
    assert cost("deepseek-chat", 0, 0) == 0.0


def test_unknown_model_returns_zero_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="app.llm.cost"):
        c = cost("some-unknown-model", 500, 500)
    assert c == 0.0
    assert any("some-unknown-model" in r.message for r in caplog.records)


def test_table_has_anthropic_entry():
    # 兼容性回归：价格表必须含至少一个 anthropic 模型条目
    assert any(k.startswith("claude") for k in COST_PER_1M_TOKENS)
