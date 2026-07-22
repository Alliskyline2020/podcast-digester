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


def test_deepseek_v4_flash_bills_nonzero():
    """回归：deepseek-v4-flash 必须在价格表里(原 P0-2 漏条目 → 选此模型时全程按 0 计费、
    预算守护失效)。官方定价(2026/07，cache miss 输入 $0.14/M、输出 $0.28/M)。"""
    c = cost("deepseek-v4-flash", 1_000_000, 1_000_000)
    assert c == 0.14 + 0.28


def test_deepseek_v4_pro_bills_nonzero():
    """deepseek-v4-pro 官方定价 $0.435/M 输入、$0.87/M 输出。"""
    c = cost("deepseek-v4-pro", 1_000_000, 1_000_000)
    assert c == 0.435 + 0.87


def test_deepseek_reasoner_priced_as_v4_flash_thinking():
    """deepseek-reasoner 旧名 2026/07/24 废弃后别名映射 v4-flash 思考模式，按 $0.14/$0.28 计费
    （原 R1 价 $0.55/$2.19 随 R1 下线作废；若仍按旧价会高估成本近 8 倍）。"""
    c = cost("deepseek-reasoner", 1_000_000, 1_000_000)
    assert c == 0.14 + 0.28
