"""Write-side validation for LLM-generated derived data (chapters / summaries).

架构修复（systematic-debugging 根因层）：pipeline 旧设计把 LLM 产出的原始 dict
不经校验就落盘 + 入库，只在 LOAD 时用 all-or-nothing 列表推导对 Pydantic 模型
校验——于是单条坏数据(末章 end_ms 缺失、summary <50 字、key_points <2 项)会
静默进存储，加载时再把整组 outline / summaries 砸成 None → 前端章节 + 章内
bullets 全空。

修法：在「生成边界」(split_into_chapters / generate_chapter_summaries 返回前)
就按模型校验、丢掉坏条目、回填 index、返回 model-conformant 的 .model_dump() dict，
让存储(file + DB)永远只持有可加载的数据。loader 的 skip-and-warn 留作读侧兜底
(历史/异常数据)。本文件单测 validate_chapters / validate_summaries 这两个纯函数。
"""
import pytest

from app.llm_pipeline.derived_validation import validate_chapters, validate_summaries


# ============================== validate_chapters ==============================

_GOOD_CH = {  # OutlineEntry 全部必填字段齐备
    "title_zh": "开篇",
    "start_ms": 0,
    "end_ms": 1000,
    "start_segment_id": 0,
    "end_segment_id": 1,
}


@pytest.mark.unit
def test_validate_chapters_drops_entry_missing_required_field():
    """缺必填字段(title_zh)的 chapter 必须被丢弃，其余保留——不得因一条坏数据返回空。"""
    chapters = [
        {**_GOOD_CH, "index": 0},
        {"start_ms": 1000, "end_ms": 2000,
         "start_segment_id": 1, "end_segment_id": 2, "index": 1},  # 缺 title_zh
        {**_GOOD_CH, "start_ms": 2000, "end_ms": 3000,
         "start_segment_id": 2, "end_segment_id": 3, "index": 2},
    ]
    out = validate_chapters(chapters)
    assert len(out) == 2, f"应丢弃缺 title_zh 的中间条目，实际保留 {len(out)}"


@pytest.mark.unit
def test_validate_chapters_returns_model_conformant_dicts():
    """输出必须是 OutlineEntry.model_dump()——所有必填字段在位、无多余 key，
    这样 file(json.dump) 与 DB(json.dumps) 落盘后 load 不会再校验炸。"""
    out = validate_chapters([{**_GOOD_CH, "index": 0, "junk_extra": "x"}])
    assert len(out) == 1
    from app.models import OutlineEntry
    expected_keys = set(OutlineEntry.model_fields.keys())
    assert set(out[0].keys()) == expected_keys, (
        f"输出应只含 OutlineEntry 字段，实际: {set(out[0].keys())} vs {expected_keys}"
    )
    # 每条都能直接再构造成模型（round-trip）
    OutlineEntry(**out[0])


@pytest.mark.unit
def test_validate_chapters_reindexes_contiguous_after_drop():
    """丢掉中间条目后，index 必须重排为 0..n-1 连续，避免持久化的 outline 出现
    index 空洞（前端按 index 排序时空洞无害，但连续更干净、可调试）。"""
    chapters = [
        {**_GOOD_CH, "index": 0},
        {"start_ms": 1, "end_ms": 2, "start_segment_id": 1,
         "end_segment_id": 2, "index": 1},  # 坏：缺 title_zh
        {**_GOOD_CH, "index": 2},
    ]
    out = validate_chapters(chapters)
    assert [c["index"] for c in out] == [0, 1], (
        f"丢中间条目后 index 应连续 [0,1]，实际: {[c['index'] for c in out]}"
    )


@pytest.mark.unit
def test_validate_chapters_injects_index_when_missing():
    """LLM 原始产出可能还没有 index（split_into_chapters 的 index 注入与 validate
    的调用顺序不应耦合）。validate 必须容忍缺失并回填，否则会因缺 index 把整组
    全丢——这正是要避免的 fail-big。"""
    out = validate_chapters([{**_GOOD_CH}])  # 无 index
    assert len(out) == 1
    assert out[0]["index"] == 0


@pytest.mark.unit
def test_validate_chapters_does_not_mutate_input():
    """不得就地修改入参 dict（pipeline 可能还会用到原始结构）。"""
    src = [{**_GOOD_CH, "index": 0}]
    src_snapshot = {k: dict(v) for k, v in enumerate(src)}
    validate_chapters(src)
    assert src == [{**_GOOD_CH, "index": 0}], "validate_chapters 不得就地改入参"
    assert src == [dict(v) for _, v in src_snapshot.items()]


# ============================== validate_summaries ==============================

_GOOD_SUM = {  # ChapterSummary 必填字段 + 约束齐备(content_zh>=50, key_points>=2)
    "chapter_id": "ch0",
    "content_zh": (
        "本章深入介绍了节目的核心主题与嘉宾背景，全面覆盖了主要讨论线索、"
        "关键论点以及最终得出的重要结论，帮助听众快速把握全貌。"
    ),
    "key_points_zh": ["要点一", "要点二"],
    "cited_segment_ids": [0, 1, 2],
}


@pytest.mark.unit
def test_validate_summaries_drops_short_content():
    """content_zh < min_length=50 的 summary 必须丢弃，其余保留。"""
    summaries = [
        {**_GOOD_SUM, "chapter_id": "ch0"},
        {**_GOOD_SUM, "chapter_id": "ch1", "content_zh": "太短了"},  # 坏
        {**_GOOD_SUM, "chapter_id": "ch2"},
    ]
    out = validate_summaries(summaries)
    assert [s["chapter_id"] for s in out] == ["ch0", "ch2"], (
        f"应丢弃 ch1(<50 字)，实际: {[s['chapter_id'] for s in out]}"
    )


@pytest.mark.unit
def test_validate_summaries_drops_too_few_key_points():
    """key_points_zh < min_items=2 的 summary 必须丢弃。"""
    summaries = [
        {**_GOOD_SUM, "chapter_id": "ch0"},
        {**_GOOD_SUM, "chapter_id": "ch1", "key_points_zh": ["仅一条"]},  # 坏
    ]
    out = validate_summaries(summaries)
    assert [s["chapter_id"] for s in out] == ["ch0"]


@pytest.mark.unit
def test_validate_summaries_returns_model_conformant_dicts():
    """输出是 ChapterSummary.model_dump()，可直接 round-trip 重构。"""
    out = validate_summaries([{**_GOOD_SUM, "stray": "x"}])
    assert len(out) == 1
    from app.models import ChapterSummary
    expected_keys = set(ChapterSummary.model_fields.keys())
    assert set(out[0].keys()) == expected_keys
    ChapterSummary(**out[0])


# ===== 集成：generate_chapter_summaries 返回前丢弃非法摘要 =====

@pytest.mark.unit
async def test_generate_chapter_summaries_drops_invalid(monkeypatch):
    """端到端：generate_chapter_summaries 返回前必须经 validate_summaries 丢弃
    <50 字的非法摘要，只保留合法的（write-side 校验，防落盘后 load 炸整组 →
    章内 bullets 全空）。"""
    from app.llm_pipeline import llm_summary
    from app.models import Segment, Transcript

    good = (
        "本章深入介绍了节目的核心主题与嘉宾背景，全面覆盖了主要讨论线索、"
        "关键论点以及最终得出的重要结论，帮助听众快速把握全貌。"
    )

    async def fake_one(chapter, transcript):
        # index==1 的章返回非法短摘要；其余合法
        if chapter.get("index") == 1:
            return {"chapter_id": "ch1", "content_zh": "太短",
                    "key_points_zh": ["x"], "cited_segment_ids": []}
        cid = f"ch{chapter.get('index')}"
        return {"chapter_id": cid, "content_zh": good,
                "key_points_zh": ["a", "b"], "cited_segment_ids": [0]}

    monkeypatch.setattr(llm_summary, "generate_chapter_summary", fake_one)
    chapters = [
        {"title_zh": f"c{i}", "start_segment_id": 0, "end_segment_id": 1, "index": i}
        for i in range(3)
    ]
    segs = [Segment(id=0, start_ms=0, end_ms=1000, text_original="x")]
    transcript = Transcript(episode_id="ep_sum_drop", language="zh", segments=segs)

    summaries = await llm_summary.generate_chapter_summaries(chapters, transcript)

    ids = [s["chapter_id"] for s in summaries]
    assert ids == ["ch0", "ch2"], f"应丢弃 ch1(<50 字)，实际: {ids}"
