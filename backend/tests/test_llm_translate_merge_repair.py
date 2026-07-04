"""
translate_segments 的"合并组修复"测试。

症状:ASR 把一句话切成多段(分片),LLM 批量翻译时把若干分片合并成一句完整中文、
写到首段(leader),其余段(follower)原样回显英文。补漏逻辑只重试"缺失 id",
漏掉了"存在但回显英文"的段,导致前端显示"中文完整句 + 英文残尾"。

修复:新增 _has_cjk / _merge_group_ids 识别"回显段 + 其 leader",
在 translate_segments 主流程后对每个合并组按 1:1 重译(各自独立翻译),
保证每段都有自己的中文、与自身英文/时间戳对齐。
"""
import pytest

from app.llm_pipeline.llm_translate import _has_cjk, _merge_group_ids


class _S:
    """最小 segment 替身:只要 .id"""
    def __init__(self, sid):
        self.id = sid


def test_has_cjk_detects_chinese():
    assert _has_cjk("这是中文") is True
    assert _has_cjk("使用 LLM 和 API") is True  # 夹杂英文术语仍有中文


def test_has_cjk_rejects_non_chinese():
    assert _has_cjk("sponsors in the description") is False
    assert _has_cjk("LLM API GPU") is False
    assert _has_cjk("") is False


def test_merge_group_ids_leader_plus_echoes():
    # 79=leader(中文完整句), 80/81=回显英文
    segs = [_S(79), _S(80), _S(81)]
    trans = {79: "这是完整句中文。", 80: "sponsors in the description", 81: "to contact me"}
    assert _merge_group_ids(segs, trans) == {79, 80, 81}


def test_merge_group_ids_no_echo_returns_empty():
    segs = [_S(0), _S(1)]
    trans = {0: "中文零", 1: "中文一"}
    assert _merge_group_ids(segs, trans) == set()


def test_merge_group_ids_missing_not_treated_as_echo():
    # 缺失(无翻译)交给现有 fill 处理,不算回显,不把 leader 拉进来
    segs = [_S(0), _S(1), _S(2)]
    trans = {0: "中文零", 2: "中文二"}  # id=1 缺失
    assert _merge_group_ids(segs, trans) == set()


def test_merge_group_ids_consecutive_echoes_walk_back_to_leader():
    segs = [_S(10), _S(11), _S(12), _S(13)]
    trans = {10: "中文leader", 11: "english echo1", 12: "english echo2", 13: "中文独立"}
    assert _merge_group_ids(segs, trans) == {10, 11, 12}


def test_merge_group_ids_echo_at_start_has_no_leader():
    # 回显段在最前、前面没有 leader:只含它自己(不向前拉不存在的段)
    segs = [_S(0), _S(1)]
    trans = {0: "english only", 1: "中文一"}
    assert _merge_group_ids(segs, trans) == {0}


# ---------------------------------------------------------------------------
# 集成：translate_segments 端到端修复合并组
# ---------------------------------------------------------------------------

import re as _re2
from app.models import Segment, Transcript


def _parse_user_rows(user):
    """从 translate user input 里解析出 (id, text) 行。"""
    rows = []
    for line in (user or "").splitlines():
        m = _re2.match(r"\s*(\d+)\s*\|\s*(.*)", line)
        if m:
            rows.append((int(m.group(1)), m.group(2)))
    return rows


@pytest.mark.asyncio
async def test_translate_segments_repairs_merged_echo_followers(monkeypatch):
    """主批 LLM 把 79+80+81 合并到 79、80/81 原样回显英文 →
    合并组修复应逐段重译，最终三段都拿到自己的中文。"""
    from app.llm_pipeline import llm_translate

    async def fake_chat_json(system, user, **kw):
        rows = _parse_user_rows(user)
        if len(rows) >= 3:
            # 主批：模拟合并 + 回显
            return {"translations": [
                {"id": 79, "text_zh": "这是Lex Fridman播客。要支持它，请查看描述中的赞助商，那里也有联系我、提问、反馈等的链接。"},
                {"id": 80, "text_zh": "sponsors in the description, where you can also find links"},
                {"id": 81, "text_zh": "to contact me, ask questions, give feedback, and so on."},
            ]}
        if len(rows) == 1:
            sid, src = rows[0]
            return {"translations": [{"id": sid, "text_zh": f"（中文{sid}）{src[:8]}"}]}
        return {"translations": []}

    monkeypatch.setattr(llm_translate, "chat_json", fake_chat_json)

    segs = [
        Segment(id=79, start_ms=316600, end_ms=320020, text_original="This is the Lex Fridman Podcast. To support it, please check out our"),
        Segment(id=80, start_ms=320040, end_ms=323800, text_original="sponsors in the description, where you can also find links"),
        Segment(id=81, start_ms=323980, end_ms=327960, text_original="to contact me, ask questions, give feedback, and so on."),
    ]
    t = Transcript(episode_id="ep_test", language="en", segments=segs)

    out = await llm_translate.translate_segments(t)
    by_id = {r["id"]: r["text_zh"] for r in out}  # last-wins

    # 三段最终都含中文
    for sid in (79, 80, 81):
        assert _has_cjk(by_id.get(sid, "")), f"seg {sid} 仍无中文: {by_id.get(sid)!r}"
    # 80/81 不再是英文原文回显
    assert by_id[80] != "sponsors in the description, where you can also find links"
    assert by_id[81] != "to contact me, ask questions, give feedback, and so on."


# ---------------------------------------------------------------------------
# apply_translations: 剥离 LLM 误把 "id | " 前缀当正文译出的泄漏
# ---------------------------------------------------------------------------

from app.llm_pipeline.llm_translate import _strip_id_prefix, apply_translations  # noqa: E402


def test_strip_id_prefix_removes_leading_id_pipe():
    assert _strip_id_prefix("350 | 之类的说法。") == "之类的说法。"
    assert _strip_id_prefix("1608 | 我8，也就是9。") == "我8，也就是9。"


def test_strip_id_prefix_leaves_clean_text_alone():
    # 普通中文/英文不该被误删
    assert _strip_id_prefix("这是没有前缀的中文。") == "这是没有前缀的中文。"
    assert _strip_id_prefix("") == ""
    assert _strip_id_prefix("IE 8、IE 9。") == "IE 8、IE 9。"


def test_apply_translations_strips_id_prefix_leak():
    """LLM 把 "id | text" 前缀当正文译出时,apply_translations 应剥掉前缀。"""
    segs = [Segment(id=0, start_ms=0, end_ms=1000, text_original="hello")]
    t = Transcript(episode_id="ep_test", language="en", segments=segs)
    translations = [{"id": 0, "text_zh": "0 | 你好"}]
    apply_translations(t, translations)
    assert segs[0].text_translated == "你好"

