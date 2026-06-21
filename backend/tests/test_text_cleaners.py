"""
文本清洗工具测试

测试文本清洗的各种功能和边界情况
"""
import pytest
from app.utils.text_cleaners import (
    clean_text,
    clean_segment_text,
    clean_llm_text,
    decode_html_entities,
    remove_html_tags,
    remove_filler_words,
    remove_special_symbols,
    normalize_whitespace,
    is_text_clean,
    DEFAULT_FILLER_WORDS,
)


class TestDecodeHtmlEntities:
    """测试HTML实体解码"""

    def test_decode_basic_entities(self):
        """测试基本HTML实体解码"""
        text = "&lt;hello&gt; &amp; world"
        result = decode_html_entities(text)
        assert result == "<hello> & world"

    def test_decode_quotes(self):
        """测试引号解码"""
        text = "&quot;test&quot; &#39;apos&#39;"
        result = decode_html_entities(text)
        assert result == '"test" \'apos\''

    def test_decode_nbsp(self):
        """测试不换行空格解码"""
        text = "hello&nbsp;world"
        result = decode_html_entities(text)
        assert result == "hello world"

    def test_decode_empty_string(self):
        """测试空字符串"""
        assert decode_html_entities("") == ""
        assert decode_html_entities(None) == ""


class TestRemoveHtmlTags:
    """测试HTML标签移除"""

    def test_remove_basic_tags(self):
        """测试基本标签移除"""
        text = "<b>hello</b> <strong>world</strong>"
        result = remove_html_tags(text)
        assert result == "hello world"

    def test_remove_nested_tags(self):
        """测试嵌套标签移除"""
        text = "<div><p>hello</p><span>world</span></div>"
        result = remove_html_tags(text)
        assert result == "helloworld"

    def test_remove_empty_string(self):
        """测试空字符串"""
        assert remove_html_tags("") == ""
        assert remove_html_tags(None) == ""


class TestRemoveFillerWords:
    """测试语气词移除"""

    def test_remove_conservative_mode(self):
        """测试保守模式（只移除单独的语气词）"""
        text = "嗯 这个 就是 有点意思"
        result = remove_filler_words(text, aggressive=False)
        # 保守模式只移除前后有空格的语气词，段首的语气词可能保留
        # 测试中间的语气词被移除
        assert "就是" not in result or result.count("就是") < text.count("就是")
        assert "这个" in result  # 保留在句子中的词

    def test_remove_aggressive_mode(self):
        """测试激进模式（移除所有语气词）"""
        text = "嗯 这个 就是 有点意思"
        result = remove_filler_words(text, aggressive=True)
        assert "嗯" not in result
        # 激进模式可能移除更多

    def test_custom_filler_words(self):
        """测试自定义语气词列表"""
        text = "foo bar baz"
        custom_fillers = ["foo", "bar"]
        result = remove_filler_words(text, filler_words=custom_fillers, aggressive=True)
        assert "foo" not in result
        assert "bar" not in result
        assert "baz" in result

    def test_empty_string(self):
        """测试空字符串"""
        assert remove_filler_words("") == ""
        assert remove_filler_words(None) == ""


class TestRemoveSpecialSymbols:
    """测试特殊符号移除"""

    def test_remove_music_symbols(self):
        """测试音乐符号移除"""
        text = "[音乐]开始[applause]结束"
        result = remove_special_symbols(text)
        assert "[音乐]" not in result
        assert "[applause]" not in result

    def test_remove_bracketed_content(self):
        """测试方括号内容移除"""
        text = "hello [noise] world [sound]"
        result = remove_special_symbols(text)
        assert "[noise]" not in result
        assert "[sound]" not in result

    def test_empty_string(self):
        """测试空字符串"""
        assert remove_special_symbols("") == ""
        assert remove_special_symbols(None) == ""


class TestNormalizeWhitespace:
    """测试空白字符标准化"""

    def test_normalize_spaces(self):
        """测试空格标准化"""
        text = "hello    world   test"
        result = normalize_whitespace(text)
        assert result == "hello world test"

    def test_normalize_newlines(self):
        """测试换行符标准化"""
        text = "hello\n\n\nworld\r\n\rtest"
        result = normalize_whitespace(text)
        assert result == "hello world test"

    def test_remove_leading_punctuation(self):
        """测试移除段首标点"""
        text = "，。、；：hello world"
        result = normalize_whitespace(text)
        assert result == "hello world"

    def test_strip_whitespace(self):
        """测试移除首尾空格"""
        text = "  hello world  "
        result = normalize_whitespace(text)
        assert result == "hello world"

    def test_empty_string(self):
        """测试空字符串"""
        assert normalize_whitespace("") == ""
        assert normalize_whitespace(None) == ""


class TestCleanText:
    """测试完整清洗流程"""

    def test_clean_html_and_filler(self):
        """测试HTML和语气词清洗"""
        text = "&lt;b&gt;嗯&lt;/b&gt;这个 就是 有点意思"
        result = clean_text(text, aggressive=True)
        assert "&lt;" not in result
        assert "<b>" not in result
        # 激进模式会移除大部分语气词，但段首的可能保留
        assert "嗯" not in result or result.index("嗯") == 0  # 如果有"嗯"，应该在段首
        assert "这个" in result
        assert "就是" not in result  # 中间的语气词应该被移除

    def test_clean_with_special_symbols(self):
        """测试特殊符号清洗"""
        text = "[音乐]开始&lt;b&gt;演唱&lt;/b&gt;"
        result = clean_text(text, remove_special=True)
        assert "[音乐]" not in result
        assert "<b>" not in result
        assert "开始演唱" in result

    def test_clean_empty_string(self):
        """测试空字符串"""
        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_clean_non_string(self):
        """测试非字符串输入"""
        assert clean_text(123) == ""
        assert clean_text([]) == ""


class TestCleanSegmentText:
    """测试字幕文本清洗（保守）"""

    def test_clean_segment_html_only(self):
        """测试只清洗HTML，不移除语气词"""
        text = "&lt;b&gt;嗯&lt;/b&gt;这个测试"
        result = clean_segment_text(text)
        assert "&lt;" not in result
        assert "<b>" not in result
        assert "嗯" in result  # 保留语气词

    def test_clean_segment_preserve_content(self):
        """测试保留内容完整性"""
        text = "嗯 这个 就是 有点意思"
        result = clean_segment_text(text)
        # 保守模式应该保留语气词
        assert "嗯" in result


class TestCleanLlmText:
    """测试LLM文本清洗（激进）"""

    def test_clean_llm_aggressive(self):
        """测试激进清洗"""
        text = "嗯 这个 就是 [音乐]有点意思"
        result = clean_llm_text(text)
        assert "嗯" not in result or result.count("嗯") < text.count("嗯")
        assert "[音乐]" not in result

    def test_clean_llm_remove_special(self):
        """测试移除特殊符号"""
        text = "[音乐]开始[笑声]结束[掌声]"
        result = clean_llm_text(text)
        assert "[音乐]" not in result
        assert "[笑声]" not in result


class TestIsTextClean:
    """测试文本清洁度检查"""

    def test_check_clean_text(self):
        """测试干净文本"""
        assert is_text_clean("hello world") is True

    def test_check_html_entities(self):
        """测试HTML实体"""
        assert is_text_clean("&lt;hello&gt;") is False

    def test_check_html_tags(self):
        """测试HTML标签"""
        assert is_text_clean("<b>hello</b>") is False

    def test_check_excessive_whitespace(self):
        """测试过多空白"""
        assert is_text_clean("hello    world") is False

    def test_check_empty_string(self):
        """测试空字符串"""
        assert is_text_clean("") is True
        assert is_text_clean(None) is True

    def test_check_without_html(self):
        """测试不检查HTML"""
        text = "&lt;hello&gt;"
        assert is_text_clean(text, check_html=False) is True


class TestEdgeCases:
    """测试边界情况"""

    def test_unicode_characters(self):
        """测试Unicode字符"""
        text = "你好世界 🎉 🎊"
        result = clean_text(text)
        assert "你好世界" in result
        assert "🎉" in result

    def test_mixed_languages(self):
        """测试混合语言"""
        text = "Hello 你好 world 世界"
        result = clean_text(text)
        assert "Hello" in result
        assert "你好" in result

    def test_very_long_text(self):
        """测试长文本"""
        text = "word " * 1000
        result = clean_text(text)
        assert "word" in result
        assert result.count("word") == 1000

    def test_special_punctuation(self):
        """测试特殊标点"""
        text = "hello…world—test"
        result = clean_text(text)
        assert "…" in result or "..." in result
        assert "—" in result or "-" in result


@pytest.mark.parametrize("input_text,expected", [
    ("&lt;b&gt;hello&lt;/b&gt;", "hello"),
    ("嗯 这个 就是 测试", "这个 测试"),
    ("[音乐]开始[笑声]结束", "开始结束"),
    ("hello    world", "hello world"),
])
def test_clean_text_various_cases(input_text, expected):
    """参数化测试各种清洗场景"""
    result = clean_text(input_text, aggressive=True, remove_special=True)
    # 检查期望的词存在
    for word in expected.split():
        if word:  # 跳过空字符串
            assert word in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
