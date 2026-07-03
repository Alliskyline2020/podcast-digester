"""chinese_text helper 单元测试。

chinese_text(seg) 返回喂下游 LLM(highlight/insight/summary/split)的最佳中文文本。
优先级遵循语言命名重构后的字段语义:
  text_zh (显式中文,迁移后/双语合并后的正确值)
  > text_translated (legacy 中文译文,未迁移数据或 en-source 翻译产物)
  > text_original (源文本,不可变,兜底——必填字段,正常非空)
  > ""

契约:
- en-source 播客:text_zh=中文译文 → 喂中文(与旧 text_translated or text_original 等价)
- zh-source 播客:text_zh=中文原文 → 喂中文(修正:旧逻辑在 text_translated 为空时会
  回退到 text_original,而中文播客的 text_original 可能是错误 locale 下的英文残留)
- 未迁移数据:text_zh=None → 回退 text_translated(等价旧行为)
"""
from app.models import Segment
from app.llm_pipeline._segtext import chinese_text


def _seg(text_original="源", text_zh=None, text_translated=None, text_en=None):
    return Segment(
        id=0,
        start_ms=0,
        end_ms=1000,
        text_original=text_original,
        text_zh=text_zh,
        text_translated=text_translated,
        text_en=text_en,
    )


def test_prefers_text_zh_when_present():
    # text_zh 同时存在 text_translated/text_original 时优先
    seg = _seg(text_zh="中文", text_translated="旧中文", text_original="en")
    assert chinese_text(seg) == "中文"


def test_falls_back_to_text_translated_without_text_zh():
    # 未迁移数据 / en-source 翻译后:text_zh 缺失,用 legacy 中文译文
    seg = _seg(text_translated="旧中文", text_original="en")
    assert chinese_text(seg) == "旧中文"


def test_falls_back_to_text_original_without_any_chinese():
    # 既无 text_zh 也无 text_translated → 兜底源文本
    seg = _seg(text_original="source only")
    assert chinese_text(seg) == "source only"


def test_returns_empty_when_all_empty_strings():
    # 全空串 → ""(text_original 必填但允许空串;理论兜底)
    seg = _seg(text_original="", text_zh="", text_translated="")
    assert chinese_text(seg) == ""


def test_yao_regression_zh_source_feeds_chinese_not_english_remnant():
    # 姚顺雨回归场景:language=zh 但 text_original 是错误 locale 下的英文 ASR 残留,
    # text_zh 是 content-routed 的中文原文。helper 必须喂中文,绝不喂英文残留。
    seg = _seg(text_original="Hello everyone", text_translated="大家好", text_zh="大家好")
    assert chinese_text(seg) == "大家好"


def test_en_source_feeds_chinese_translation():
    # 英文播客:text_zh=中文译文,text_en=英文原文 → 喂中文译文
    seg = _seg(text_original="Hello", text_zh="你好", text_en="Hello")
    assert chinese_text(seg) == "你好"


def test_empty_string_text_zh_is_skipped():
    # 空串(非 None)应被视为 falsy 跳过,回退到下一优先级
    seg = _seg(text_zh="", text_translated="fallback", text_original="src")
    assert chinese_text(seg) == "fallback"
