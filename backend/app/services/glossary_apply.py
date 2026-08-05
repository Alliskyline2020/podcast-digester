"""管线词库自动套用：对新播客的 transcript 做确定性字符串替换。

在 polish 之后、下游 LLM 阶段（chapterize/summarize/highlight/insights）之前调用。
下游读干净文本生成 → 自动继承正确人名/术语，无需对每个下游模块单独套用。
"""
from typing import Protocol


class _TranscriptLike(Protocol):
    segments: list


def apply_glossary_to_segments(glossary, transcript) -> int:
    """对 transcript 的所有 segment 的文本字段套用词库纠错。

    纠正五个字段（存在才纠）：text_original、text_with_punct、text_translated、text_zh、text_en。
    幂等：已正确的文本不会被重复修改。

    Args:
        glossary: Glossary 实例，需提供 correct_text(text: str) -> str 方法
        transcript: Transcript 类或具有 segments 属性的对象

    Returns:
        任何一个字段被改过的 segment 数量。
    """
    count = 0
    for seg in transcript.segments:
        changed = False
        # 五个可能需要纠正的文本字段
        for field in ("text_original", "text_with_punct", "text_translated", "text_zh", "text_en"):
            val = getattr(seg, field, None)
            if not val:
                continue
            new = glossary.correct_text(val)
            if new != val:
                setattr(seg, field, new)
                changed = True
        if changed:
            count += 1
    return count
