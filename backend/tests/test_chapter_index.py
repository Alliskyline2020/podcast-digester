"""Regression tests for the OutlineEntry resume-landmine.

Root cause (found via systematic-debugging): `split_into_chapters` returns chapter
dicts WITHOUT an `index` field. In `_process_internal` the L284 `_checkpoint_json`
writes outline.json BEFORE `generate_chapter_summaries` (L290) mutates the chapters
to add `ch["index"] = i`. If a run crashes between L284 and the final save at L350,
outline.json is left without `index`, and any later `_load_intermediate_results`
(resume path, pipeline.py ~L650) raises `OutlineEntry index Field required` — the
stale error observed on Yao.

Two fix points, one test each:
  1. split_into_chapters injects positional `index` before returning  (root cause)
  2. _load_intermediate_results tolerates a legacy index-less outline.json (defense)
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
    assert [c.index for c in chapters] == [0, 1]
