from app.utils.text_cleaners import preclean_mechanical


def test_decodes_html_entities():
    # &lt;b&gt; 解码成 <b>(已知标签)→ 被剥掉, 剩正文
    assert preclean_mechanical("a &lt;b&gt; c") == "a c"


def test_strips_html_tags():
    assert preclean_mechanical("<b>hello</b> world") == "hello world"


def test_strips_zero_width_chars():
    assert preclean_mechanical("foo​bar﻿") == "foobar"


def test_normalizes_whitespace():
    assert preclean_mechanical("a   b\n\tc") == "a b c"


def test_preserves_filler_words_and_repetition():
    # 关键: 机械预清洗不删口水话/叠词(那是 LLM 的活)
    assert preclean_mechanical("嗯 我我我 然后") == "嗯 我我我 然后"


def test_empty_and_non_string():
    assert preclean_mechanical("") == ""
    assert preclean_mechanical(None) == ""  # type: ignore[arg-type]


def test_removes_audio_markers():
    # [音乐]/[掌声] 标记被移除, 正文保留
    assert preclean_mechanical("[音乐]开讲 [掌声]") == "开讲"
