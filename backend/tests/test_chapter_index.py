"""Regression tests for the resume-landmine in _load_intermediate_results.

Architectural invariant: `_load_intermediate_results` (resume path) must return the
SAME types as `_process_internal` (first run), because its output feeds
`save_episode_bundle`, which json-serializes `outline` and `summaries` directly
(storage.py: writer.write(..., outline) / writer.write(..., summaries) — NO
.model_dump()). Only `transcript`/`highlight` get .model_dump().

Two early implementations broke this:
  - chapters constructed as `OutlineEntry(...)` → "OutlineEntry is not JSON serializable"
  - summaries constructed as `ChapterSummary(...)` → "ChapterSummary is not JSON serializable"

These tests pin the invariant: resume-loaded chapters/summaries are list[dict] and
the whole intermediate dict round-trips through json.dumps (the save_episode_bundle
contract).

Related: split_into_chapters must inject positional `index` before the outline
checkpoint, so a run that crashes between the checkpoint and the index-injecting
summarize stage still leaves outline.json safe to resume from.
"""
import json

import pytest

from app.models import Segment, Transcript


@pytest.mark.unit
async def test_split_into_chapters_injects_positional_index(monkeypatch):
    """split_into_chapters must inject a 0-based positional `index` into each
    chapter dict so the outline.json checkpoint (written before summarize adds
    index) is safe to resume from."""
    from app.llm_pipeline import llm_split

    async def fake_chat_json(*args, **kwargs):
        return {
            "chapters": [
                {"title_zh": "一", "start_segment_id": 0, "end_segment_id": 1},
                {"title_zh": "二", "start_segment_id": 1, "end_segment_id": 3},
                {"title_zh": "三", "start_segment_id": 3, "end_segment_id": 5},
            ]
        }

    monkeypatch.setattr(llm_split, "chat_json", fake_chat_json)

    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"seg {i}")
        for i in range(5)
    ]
    transcript = Transcript(episode_id="ep_idx_1", language="zh", segments=segs)

    chapters = await llm_split.split_into_chapters(transcript)

    assert [c.get("index") for c in chapters] == [0, 1, 2]


# ===== 末章 end_ms off-by-one（章节分段整体消失的根因）=====
#
# 回归（systematic-debugging）：split_into_chapters 用 `if end_id < len(segments)`
# 守卫 end_ms 写入。末章的 end_segment_id 常为 len(segments)（LLM 用排他边界表示
# 「直到结尾」，ep_1784870551970 实测：356 段、末章 end_segment_id=356）→ `356 < 356`
# 为 False → end_ms 不写入 → OutlineEntry(end_ms 必填) 校验失败 → loader 的列表推导
# 整体抛错 → outline 归 None → 前端 chapters=[] → 章节列表 + 章内 key_points 全消失。
# 修复：抽出 _stamp_chapter_timings，end_id 越界时钳到末段取 end_ms。

@pytest.mark.unit
def test_stamp_chapter_timings_clamps_past_end_boundary():
    """末章 end_segment_id == len(segments)（排他越界边界）时必须钳到末段，
    写入 end_ms，而非跳过（跳过会让 OutlineEntry 校验失败、整章归 None）。"""
    from app.llm_pipeline import llm_split
    from app.models import Segment

    # 5 段，索引 0..4
    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"s{i}")
        for i in range(5)
    ]
    chapters = [
        # 内章节：合法 end_id
        {"title_zh": "一", "start_segment_id": 0, "end_segment_id": 2},
        # 末章：end_segment_id == len(segments) （排他越界边界，ep_1784870551970 实况）
        {"title_zh": "末", "start_segment_id": 2, "end_segment_id": 5},
    ]

    llm_split._stamp_chapter_timings(chapters, segs)

    # 内章节不受影响：end_ms = segs[2].end_ms
    assert chapters[0]["start_ms"] == 0
    assert chapters[0]["end_ms"] == 3000
    # 末章越界边界被钳到末段 segs[4]：end_ms 必须被写入（回归核心）
    assert chapters[1]["start_ms"] == 2000
    assert chapters[1]["end_ms"] == 5000, "末章 end_ms 不能缺，否则 OutlineEntry 校验炸、整 outline 归 None"


@pytest.mark.unit
def test_stamp_chapter_timings_clamps_negative_and_huge_end_id():
    """极端 end_id 也要钳到合法区间，不得缺 end_ms、不得越界取 segments[idx]。"""
    from app.llm_pipeline import llm_split
    from app.models import Segment

    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"s{i}")
        for i in range(3)
    ]
    chapters = [
        {"title_zh": "A", "start_segment_id": 0, "end_segment_id": 99},   # 远超长
        {"title_zh": "B", "start_segment_id": 0, "end_segment_id": -1},    # 负数
    ]
    llm_split._stamp_chapter_timings(chapters, segs)

    assert chapters[0]["end_ms"] == 3000   # 钳到末段 segs[2].end_ms
    # 负 end_id 钳后仍 < 0 → 不写 end_ms（由 loader 容错兜底），但绝不能取 segs[-1]
    assert "end_ms" not in chapters[1] or chapters[1]["end_ms"] != 1000


@pytest.mark.unit
async def test_split_into_chapters_last_chapter_keeps_end_ms(monkeypatch):
    """端到端：fake LLM 给末章返回 end_segment_id=len(segments)，split_into_chapters
    必须为每章都写入 end_ms（旧行为会让末章丢 end_ms）。"""
    from app.llm_pipeline import llm_split
    from app.models import Segment, Transcript

    async def fake_chat_json(*args, **kwargs):
        return {
            "chapters": [
                {"title_zh": "一", "start_segment_id": 0, "end_segment_id": 1},
                # 末章 end_segment_id == 段数（排他越界）
                {"title_zh": "末", "start_segment_id": 1, "end_segment_id": 5},
            ]
        }

    monkeypatch.setattr(llm_split, "chat_json", fake_chat_json)
    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"seg {i}")
        for i in range(5)
    ]
    transcript = Transcript(episode_id="ep_endms", language="zh", segments=segs)

    chapters = await llm_split.split_into_chapters(transcript)

    assert len(chapters) == 2
    assert all("end_ms" in c for c in chapters), "每章都必须有 end_ms（末章不能丢）"
    assert chapters[-1]["end_ms"] == 5000   # 末段 segs[4].end_ms


@pytest.mark.unit
async def test_load_intermediate_results_tolerates_outline_missing_index(temp_data_dir):
    """_load_intermediate_results (resume path) must not crash on an outline.json
    whose entries lack `index` (e.g. left by a run that crashed between the
    chapterize checkpoint and the index-injecting summarize stage). It injects a
    positional index instead of raising OutlineEntry validation."""
    from app.pipeline import AudioProcessPipeline

    ep = "ep_idx_resume"
    media = temp_data_dir / "media" / ep
    media.mkdir(parents=True)
    (media / "transcript.json").write_text(
        json.dumps(
            {
                "episode_id": ep,
                "language": "zh",
                "segments": [
                    {"id": 0, "start_ms": 0, "end_ms": 1000, "text_original": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    # outline.json as a crashed-mid-chapterize run would leave it: NO `index`.
    (media / "outline.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "title_zh": "一",
                        "start_segment_id": 0,
                        "end_segment_id": 0,
                        "start_ms": 0,
                        "end_ms": 1000,
                    },
                    {
                        "title_zh": "二",
                        "start_segment_id": 0,
                        "end_segment_id": 0,
                        "start_ms": 1000,
                        "end_ms": 2000,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    pipeline = AudioProcessPipeline(temp_data_dir)
    result = await pipeline._load_intermediate_results(ep)

    chapters = result["chapters"]
    assert chapters is not None
    # returns list[dict] (aligned with split_into_chapters), not OutlineEntry
    assert [c["index"] for c in chapters] == [0, 1]


@pytest.mark.unit
async def test_load_intermediate_results_handles_outline_with_existing_index(temp_data_dir):
    """_load_intermediate_results (resume path) must not crash when outline.json
    entries ALREADY carry `index` — the post-ee5194f shape, since
    split_into_chapters now injects positional index before the checkpoint.

    The pipeline.py fallback `OutlineEntry(**{'index': i}, **e)` passes `index`
    twice in that case and raises 'got multiple values for keyword argument index'
    — observed on ep_1783159780018 resume (2026-07-04). Must keep the stored index,
    not overwrite and not crash."""
    from app.pipeline import AudioProcessPipeline

    ep = "ep_idx_resume_existing"
    media = temp_data_dir / "media" / ep
    media.mkdir(parents=True)
    (media / "transcript.json").write_text(
        json.dumps(
            {
                "episode_id": ep,
                "language": "zh",
                "segments": [
                    {"id": 0, "start_ms": 0, "end_ms": 1000, "text_original": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    # outline.json as Task #5 (ee5194f) writes it: entries WITH `index`.
    # Intentionally non-zero (5/6) to prove we keep the stored value.
    (media / "outline.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "title_zh": "一",
                        "start_segment_id": 0,
                        "end_segment_id": 0,
                        "start_ms": 0,
                        "end_ms": 1000,
                        "index": 5,
                    },
                    {
                        "title_zh": "二",
                        "start_segment_id": 0,
                        "end_segment_id": 0,
                        "start_ms": 1000,
                        "end_ms": 2000,
                        "index": 6,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    pipeline = AudioProcessPipeline(temp_data_dir)
    result = await pipeline._load_intermediate_results(ep)

    chapters = result["chapters"]
    assert chapters is not None
    # returns list[dict] aligned with _process_internal; keeps stored index, no crash
    assert [c["index"] for c in chapters] == [5, 6]


@pytest.mark.unit
async def test_load_intermediate_results_round_trips_through_json(temp_data_dir):
    """save_episode_bundle contract: outline and summaries are written via
    writer.write(..., value) with NO .model_dump() (storage.py ~L225/L229), so they
    must be plain JSON-serializable dict sequences. Any Pydantic instance in
    result['chapters'] / result['summaries'] makes resume crash with
    'Object of type X is not JSON serializable'. Pin the contract end-to-end."""
    import json as _json

    from app.pipeline import AudioProcessPipeline

    ep = "ep_idx_contract"
    media = temp_data_dir / "media" / ep
    media.mkdir(parents=True)
    (media / "transcript.json").write_text(
        _json.dumps(
            {
                "episode_id": ep,
                "language": "zh",
                "segments": [
                    {"id": 0, "start_ms": 0, "end_ms": 1000, "text_original": "x"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (media / "outline.json").write_text(
        _json.dumps(
            {
                "entries": [
                    {
                        "title_zh": "一",
                        "start_segment_id": 0,
                        "end_segment_id": 0,
                        "start_ms": 0,
                        "end_ms": 1000,
                        "index": 0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (media / "summaries.json").write_text(
        _json.dumps(
            [{"chapter_index": 0, "summary_zh": "摘要一", "worth_listening": "deep_listen"}]
        ),
        encoding="utf-8",
    )

    pipeline = AudioProcessPipeline(temp_data_dir)
    result = await pipeline._load_intermediate_results(ep)

    # chapters / summaries are list[dict] (not Pydantic instances)
    assert all(isinstance(c, dict) for c in result["chapters"])
    assert all(isinstance(s, dict) for s in result["summaries"])

    # the save_episode_bundle contract: both survive json.dumps without raising
    _json.dumps({"entries": result["chapters"]})
    _json.dumps(result["summaries"])


# ===== write-side 校验：生成器边界丢弃非法条目（架构修复集成）=====
#
# split_into_chapters 返回前经 validate_chapters 按 OutlineEntry 校验。LLM 若返回
# 缺必填字段(如 title_zh)的章节，必须在此丢弃——否则会落盘/入库，加载时让整组
# outline 归 None（fail-big）。本测试端到端验证生成器不再向下游泄漏非法章节。

@pytest.mark.unit
async def test_split_into_chapters_drops_malformed_chapter(monkeypatch):
    """fake LLM 返回一条缺 title_zh 的非法章节，split_into_chapters 经 validate_chapters
    丢弃它，只返回合法章节，且 index 连续重排。"""
    from app.llm_pipeline import llm_split

    async def fake_chat_json(*args, **kwargs):
        return {
            "chapters": [
                {"title_zh": "好章", "start_segment_id": 0, "end_segment_id": 1},
                {"start_segment_id": 1, "end_segment_id": 2},  # 缺 title_zh → 非法
                {"title_zh": "好章2", "start_segment_id": 2, "end_segment_id": 4},
            ]
        }

    monkeypatch.setattr(llm_split, "chat_json", fake_chat_json)
    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"s{i}")
        for i in range(5)
    ]
    transcript = Transcript(episode_id="ep_drop", language="zh", segments=segs)

    chapters = await llm_split.split_into_chapters(transcript)

    titles = [c["title_zh"] for c in chapters]
    assert titles == ["好章", "好章2"], f"应丢弃缺 title_zh 的中间章，实际: {titles}"
    assert [c["index"] for c in chapters] == [0, 1], "丢弃后 index 应连续重排"
