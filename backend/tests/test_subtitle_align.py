"""subtitle_align 纯函数单元测试。"""
from app.services.subtitle_align import (
    normalize, remove_fillers, semantic_ok, collapse_repetition,
    LCS_PRESERVE_MIN, LCS_ADD_MAX,
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


def test_name_correction_passes_with_entity_variants():
    # ASR "姚顺雨" 被矫正为 "姚顺宇" —— 有实体表时应通过
    variants = {"姚顺雨": "姚顺宇"}
    assert semantic_ok("姚顺宇说了", "姚顺雨说了", entity_variants=variants) is True


def test_name_correction_rejected_without_entity_variants():
    # 无实体表: 同样矫正被判漂移(默认行为不变, 防过度纠正)
    assert semantic_ok("姚顺宇说了", "姚顺雨说了") is False


def test_real_drift_still_rejected_with_entities():
    # 实体表只放行表内矫正; 真正丢内容仍判漂移
    variants = {"姚顺雨": "姚顺宇"}
    assert semantic_ok("姚顺宇", "姚顺雨说了很重要的事情", entity_variants=variants) is False


def test_term_correction_english_case_insensitive():
    # normalize 小写化: 变体按小写归一, 大小写差异不触发漂移
    variants = {"open ai": "openai", "openai": "openai"}
    assert semantic_ok("OpenAI launched", "open ai launched", entity_variants=variants) is True


def test_no_entity_variants_backward_compatible():
    # 原两参签名行为不变
    assert semantic_ok("你好世界", "你好世界") is True


# ---------- 口吃/叠词折叠容忍 ----------

def test_collapse_repetition_folds_three_plus():
    # ≥3 连续相同 → 1
    assert collapse_repetition("我我我觉得") == "我觉得"
    assert collapse_repetition("嗯嗯嗯然后") == "嗯然后"


def test_collapse_repetition_preserves_double_chars():
    # 2 连(中文合法叠字)不动
    assert collapse_repetition("爸爸来了") == "爸爸来了"
    assert collapse_repetition("慢慢走") == "慢慢走"


def test_semantic_ok_passes_stutter_folding():
    # LLM 把 "我我我" 折叠成 "我" —— 不应判漂移
    original = "我我我觉得 这个很好"
    polished = "我觉得这个很好。"
    assert semantic_ok(polished, original) is True


def test_semantic_ok_still_rejects_content_loss_after_collapse():
    # 折叠容忍不放松对真正丢内容的检测
    original = "我我我觉得这个浏览器"
    polished = "我觉得。"  # 丢了 "这个浏览器"
    assert semantic_ok(polished, original) is False
