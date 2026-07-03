"""Segment text-selection helper for downstream LLM prompts.

下游 LLM(highlight / product_insight / summary / split)的 prompt 都是中文,需要喂
每条 segment 的中文文本。语言命名重构后中文文本的权威字段是 `text_zh`;迁移未覆盖
或 en-source 翻译产物的 legacy 字段是 `text_translated`;`text_original` 是不可变
的源文本兜底。

为什么需要这个 helper:旧代码处处写 `seg.text_translated or seg.text_original`。
对 en-source 播客正确(text_translated 是中文译文),但对 zh-source 播客在
text_translated 为空时会回退到 text_original——而中文播客的 text_original 可能是
错误 locale 下的英文 ASR 残留(见姚顺雨回归)。集中走 `text_zh` 优先可消除这个隐患。
"""

from __future__ import annotations

from typing import Protocol


class _Texted(Protocol):
    """Segment 上读取的文本字段子集——避免与 Segment 硬耦合,方便测试用桩。"""

    text_zh: str | None
    text_translated: str | None
    text_original: str | None


def chinese_text(seg: _Texted) -> str:
    """Return the best available Chinese text of a segment for LLM prompts.

    Preference: text_zh > text_translated (legacy) > text_original (source) > "".
    Empty strings are treated as missing (falsy) and skipped.
    """
    return seg.text_zh or seg.text_translated or seg.text_original or ""
