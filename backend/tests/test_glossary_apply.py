"""管线词库自动套用：纠正 segment 的所有文本字段。"""
from app.services.glossary_apply import apply_glossary_to_segments
from app.services.glossary_db import Glossary


class _StubGlossary(Glossary):
    """绕过 DB 的内存词库。"""

    def __init__(self, entries: dict):
        self.cache = dict(entries)


def _seg(
    text_original,
    text_with_punct=None,
    text_translated=None,
    text_zh=None,
    text_en=None,
):
    from app.models import Segment
    return Segment(
        id=0,
        start_ms=0,
        end_ms=1000,
        text_original=text_original,
        text_with_punct=text_with_punct,
        text_translated=text_translated,
        text_zh=text_zh,
        text_en=text_en,
    )


def test_corrects_all_five_text_fields():
    """纠正所有五个文本字段：text_original, text_with_punct, text_translated, text_zh, text_en"""
    g = _StubGlossary({"杨植麟": ["杨志林"]})
    # text_original 有 wrong，text_with_punct 有 wrong，text_zh 有 wrong
    # text_translated 是英文没有 wrong（不应被改），text_en 是英文没有 wrong（不应被改）
    segs = [
        _seg(
            text_original="杨志林是教授",
            text_with_punct="今天杨志林是教授",
            text_translated="Yang Zhilin is a professor",
            text_zh="杨志林是教授",
            text_en="Yang Zhilin is a professor",
        )
    ]
    transcript = type("T", (), {"segments": segs})()
    n = apply_glossary_to_segments(g, transcript)
    assert n == 1
    assert segs[0].text_original == "杨植麟是教授"
    assert segs[0].text_with_punct == "今天杨植麟是教授"
    # 英文翻译里没有 wrong，不应被改
    assert segs[0].text_translated == "Yang Zhilin is a professor"
    assert segs[0].text_zh == "杨植麟是教授"
    # 英文字段不应被改
    assert segs[0].text_en == "Yang Zhilin is a professor"


def test_idempotent_on_already_correct_text():
    """对已正确的文本不做任何修改（幂等）"""
    g = _StubGlossary({"杨植麟": ["杨志林"]})
    segs = [_seg(text_original="杨植麟是教授", text_with_punct="今天杨植麟是教授")]
    transcript = type("T", (), {"segments": segs})()
    assert apply_glossary_to_segments(g, transcript) == 0  # 没改任何段


def test_skips_none_fields():
    """跳过 None/空字段，仅处理存在的字段"""
    g = _StubGlossary({"杨植麟": ["杨志林"]})
    segs = [_seg(text_original="杨志林是教授")]  # 其他字段都是 None
    transcript = type("T", (), {"segments": segs})()
    n = apply_glossary_to_segments(g, transcript)
    assert n == 1
    assert segs[0].text_original == "杨植麟是教授"
    # 确保只处理了存在的字段
    assert segs[0].text_with_punct is None
    assert segs[0].text_translated is None
    assert segs[0].text_zh is None
    assert segs[0].text_en is None


def test_english_wrong_token_in_english_field():
    """英文字段的错误拼写应该被纠正"""
    g = _StubGlossary({"Sam Altman": ["Sam Altmen"]})
    segs = [
        _seg(
            text_original="Sam Altmen is CEO",
            text_with_punct="Sam Altmen is CEO",
            text_en="Sam Altmen is CEO",
        )
    ]
    transcript = type("T", (), {"segments": segs})()
    n = apply_glossary_to_segments(g, transcript)
    assert n == 1
    assert segs[0].text_original == "Sam Altman is CEO"
    assert segs[0].text_with_punct == "Sam Altman is CEO"
    assert segs[0].text_en == "Sam Altman is CEO"


def test_multiple_segments_count_correctly():
    """多个 segment 被修改时正确计数"""
    g = _StubGlossary({"杨植麟": ["杨志林"]})
    segs = [
        _seg(text_original="杨志林是教授"),
        _seg(text_original="杨志林去了硅谷"),
        _seg(text_original="张三是研究员"),  # 这个没改
    ]
    transcript = type("T", (), {"segments": segs})()
    n = apply_glossary_to_segments(g, transcript)
    assert n == 2  # 只有两个 segment 被改
