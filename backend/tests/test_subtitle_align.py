"""subtitle_align 纯函数单元测试。"""
from app.services.subtitle_align import (
    normalize, remove_fillers, semantic_ok, LCS_PRESERVE_MIN, LCS_ADD_MAX,
)


def test_normalize_strips_punctuation_whitespace_and_lowercases():
    assert normalize("Hello, World!  你好。") == "helloworld你好"


def test_remove_fillers_chinese_substring():
    # 删口水话, 保留实义内容
    assert remove_fillers("嗯然后呢我觉得这个浏览器") == "我觉得这个浏览器"


def test_remove_fillers_english_word_boundary():
    # 词边界删, 不误删子串(如 "like" 不应吃掉 "likely")
    assert remove_fillers("um you know the likely case") == " the likely case"


def test_semantic_ok_passes_clean_punctuation_only():
    original = "我觉得这个浏览器很好用"
    polished = "我觉得，这个浏览器很好用。"
    assert semantic_ok(polished, original) is True


def test_semantic_ok_passes_filler_removal():
    # 删口水话不应扣分(白名单已剔除后再算 LCS)
    original = "嗯然后呢我觉得这个浏览器很好用"
    polished = "我觉得这个浏览器很好用。"
    assert semantic_ok(polished, original) is True


def test_semantic_ok_rejects_drift_different_content():
    # drift: polished 是邻段内容, 与原文实义几乎不重叠
    original = "维护成本和移动端的商业模式"
    polished = "Craigslist 和 BAT 是新媒介的代表。"
    assert semantic_ok(polished, original) is False


def test_semantic_ok_rejects_content_loss():
    # 丢了实义内容("浏览器") → 保留率掉
    original = "我收到过一些收购的offer因为浏览器是谁的"
    polished = "我收到过一些。"  # 丢了大半实义内容
    assert semantic_ok(polished, original) is False


def test_semantic_ok_rejects_hallucination_addition():
    # 加了原文没有的实义内容 → 新增率升
    original = "浏览器是谁的"
    polished = "浏览器是谁的OpenAI和谷歌都在争夺这个入口"
    assert semantic_ok(polished, original) is False


def test_thresholds():
    assert LCS_PRESERVE_MIN == 0.90
    assert LCS_ADD_MAX == 0.15


def test_semantic_ok_pure_filler_original():
    # 原文去口水话后为空(纯口水话句) → 只要输出也很短即通过, 否则失败
    assert semantic_ok("", "嗯嗯") is True              # 输出空
    assert semantic_ok("嗯", "嗯嗯") is True             # 输出也很短(嗯 是 filler → p 为空)
    assert semantic_ok("这是很长的实义内容", "嗯") is False  # 输出凭空加了内容
