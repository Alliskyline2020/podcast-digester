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
