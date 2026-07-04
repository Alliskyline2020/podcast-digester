"""Progress tracking: in-stage progress + counts must reach the DB.

Root cause (systematic-debugging Phase 1): `_update_stage_progress_sync` was
`async def` but invoked from a sync lambda (`progress_cb=lambda p: ...`) at 9
call sites. The returned coroutine was never awaited → neither the in-memory
`stages` update nor the `IngestJobRepository.update_stages` write ever ran
mid-stage. Confirmed in DB: a transcribe stage sat at progress 0.0 while polish
was actually at ~44%. Only `_complete_stage` (which does `await sync_fn()`)
persisted anything, and only at stage boundaries (→ 1.0).

The working reference is `download_progress` (pipeline.py ~L205), which already
bridges the sync→async gap with `asyncio.create_task(...)`. The fix mirrors it:
`_make_db_progress_cb` returns a SYNC cb that updates the in-memory stage and
fire-and-forgets the DB write, and optionally carries `current`/`total` counts
so the UI can show "440/1000"-style detail.
"""
import asyncio

import pytest

from app.pipeline import AudioProcessPipeline


def _stage(stage_id: str, progress: float = 0.0) -> dict:
    """A stage dict shaped like the pipeline's in-memory `stages` entries."""
    return {
        "id": stage_id,
        "name": stage_id,
        "status": "running",
        "progress": progress,
        "started_at": "2026-07-04T00:00:00",
        "completed_at": None,
        "error": None,
    }


@pytest.mark.unit
async def test_make_db_progress_cb_updates_in_memory_and_writes_db(
    monkeypatch, temp_data_dir
):
    """cb(p) updates the in-memory stage progress and fire-and-forgets a DB write
    (mirroring download_progress). This is the core regression: previously the
    async update was discarded and progress stayed frozen at 0.0."""
    calls = []

    async def fake_update_stages(episode_id, stages, current_stage):
        calls.append((episode_id, stages, current_stage))

    monkeypatch.setattr(
        "app.pipeline.IngestJobRepository.update_stages", fake_update_stages
    )

    pipe = AudioProcessPipeline(temp_data_dir)
    stages = [_stage("transcribe")]
    cb = pipe._make_db_progress_cb(stages, "transcribe", "ep_1")

    cb(0.5)
    # create_task scheduled the DB write; yield so it runs
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert stages[0]["progress"] == 0.5
    assert len(calls) == 1
    assert calls[0][0] == "ep_1"
    written = calls[0][1][0]
    assert written["name"] == "transcribe"
    assert written["progress"] == 0.5


@pytest.mark.unit
async def test_make_db_progress_cb_carries_counts(monkeypatch, temp_data_dir):
    """cb(p, current, total) stamps current/total on the in-memory stage AND on
    the formatted DB row, so the UI can render '440/1000'-style detail."""
    calls = []

    async def fake_update_stages(episode_id, stages, current_stage):
        calls.append(stages)

    monkeypatch.setattr(
        "app.pipeline.IngestJobRepository.update_stages", fake_update_stages
    )

    pipe = AudioProcessPipeline(temp_data_dir)
    stages = [_stage("transcribe")]
    cb = pipe._make_db_progress_cb(stages, "transcribe", "ep_1")

    cb(0.44, current=440, total=1000)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert stages[0]["current"] == 440
    assert stages[0]["total"] == 1000
    written = calls[0][0]
    assert written["current"] == 440
    assert written["total"] == 1000


@pytest.mark.unit
async def test_make_db_progress_cb_counts_optional(monkeypatch, temp_data_dir):
    """cb(p) without counts leaves current/total unset (stages without natural
    counts, e.g. chapterize, must not emit bogus 0/0)."""
    calls = []

    async def fake_update_stages(episode_id, stages, current_stage):
        calls.append(stages)

    monkeypatch.setattr(
        "app.pipeline.IngestJobRepository.update_stages", fake_update_stages
    )

    pipe = AudioProcessPipeline(temp_data_dir)
    stages = [_stage("chapterize")]
    cb = pipe._make_db_progress_cb(stages, "chapterize", "ep_1")

    cb(0.3)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # no counts provided → not invented
    assert "current" not in stages[0] or stages[0]["current"] is None
    written = calls[0][0]
    assert written.get("current") is None
    assert written.get("total") is None


@pytest.mark.unit
async def test_polish_emits_segment_counts(monkeypatch):
    """polish must call progress_cb with (p, current, total) where current =
    segments polished so far and total = segment count, so the UI can render
    '440/4045 段'-style detail for the transcribe stage."""
    from app.services import subtitle_processor as sp
    from app.services.subtitle_processor import SubtitleProcessor
    from app.models import Segment, Transcript

    # Mock the LLM: return no polished rows → every segment falls back to its
    # original text (still processed, still counted). Avoids real API calls.
    async def fake_chat_json(*args, **kwargs):
        return {"polished": []}

    monkeypatch.setattr(sp, "chat_json", fake_chat_json)

    total = 35
    segs = [
        Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"seg {i}")
        for i in range(total)
    ]
    transcript = Transcript(episode_id="ep_polish", language="en", segments=segs)

    calls = []

    def cb(p, current=None, total=None):
        calls.append((p, current, total))

    await SubtitleProcessor().polish(transcript, progress_cb=cb)

    assert calls, "progress_cb was never called"
    # every call carries the segment total
    assert all(c[2] == total for c in calls), "total must be the segment count"
    # current is monotonic non-decreasing and reaches total on the last batch
    currents = [c[1] for c in calls]
    assert currents == sorted(currents)
    assert currents[-1] == total


@pytest.mark.unit
async def test_summarize_emits_chapter_counts(monkeypatch):
    """generate_chapter_summaries must call progress_cb with (p, completed,
    total_chapters) so the UI can render '12/48 章'-style detail. Completion
    order is concurrent (semaphore), so assert by set, not call order."""
    from app.llm_pipeline import llm_summary
    from app.models import Segment, Transcript

    # Patch the per-chapter call (the concurrent loop calls this, not chat_json).
    async def fake_summarize_one(chapter, transcript):
        return {"title_zh": chapter["title_zh"], "summary": "x"}

    monkeypatch.setattr(llm_summary, "generate_chapter_summary", fake_summarize_one)

    segs = [Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original="s") for i in range(6)]
    transcript = Transcript(episode_id="ep_sum", language="zh", segments=segs)
    chapters = [
        {"index": i, "title_zh": f"ch {i}", "start_segment_id": 0, "end_segment_id": 5,
         "start_ms": 0, "end_ms": 6000}
        for i in range(4)
    ]

    calls = []

    def cb(p, current=None, total=None):
        calls.append((p, current, total))

    await llm_summary.generate_chapter_summaries(chapters, transcript, progress_cb=cb)

    assert len(calls) == 4
    assert all(c[2] == 4 for c in calls), "total must be chapter count"
    # completed covers every chapter exactly once (order is concurrent)
    assert sorted(c[1] for c in calls) == [1, 2, 3, 4]


# ===== load_progress_fast: overall_progress must be monotonic & correct =====
#
# Regression (systematic-debugging): load_progress_fast decided a stage was
# "completed" via `progress >= 1.0`. But progress is written fire-and-forget
# through asyncio.create_task (pipeline._make_db_progress_cb), so a stale
# overwrite can momentarily leave a *completed* stage's progress != 1.0.
# That stage's weight then got dropped entirely → overall_progress regressed
# (user-visible as "progress % resets to 0 after a step finishes").
#
# Fix: delegate overall to `calculate_overall_progress` — POSITION-based
# (current stage + everything before it = full weight), monotonic regardless
# of transient progress-field values. Also drops the divergent local
# STAGE_WEIGHTS copy (which omitted product_insights → premature 100%).

from app.services.episode_loader import load_progress_fast  # noqa: E402


def _patch_ingest_job(monkeypatch, job_data):
    async def fake_get(episode_id):
        return job_data
    monkeypatch.setattr(
        "app.services.episode_loader.IngestJobRepository.get_by_id",
        staticmethod(fake_get),
    )


@pytest.mark.unit
async def test_load_progress_monotonic_when_completed_stage_progress_stale(
    monkeypatch, temp_data_dir
):
    """transcribe is done but its progress field reads 0.0 (stale overwrite);
    chapterize is current at 30%. overall must still count transcribe's weight
    (position-based), not drop it and regress."""
    _patch_ingest_job(
        monkeypatch,
        {
            "current_stage": "chapterize",
            "stages": [
                {"name": "download", "status": "downloading", "progress": 1.0},
                {"name": "transcribe", "status": "asr_running", "progress": 0.0},
                {"name": "chapterize", "status": "llm_running", "progress": 0.3},
            ],
        },
    )

    result = await load_progress_fast("ep_1")

    # download(20) + transcribe(20) + chapterize(10)*0.3 = 43%
    assert result["overall_progress"] == pytest.approx(0.43, abs=0.01)


@pytest.mark.unit
async def test_load_progress_product_insights_not_premature_full(
    monkeypatch, temp_data_dir
):
    """product_insights current at 50%. Local STAGE_WEIGHTS used to omit it,
    so overall hit 100% the moment highlight finished. Must now reflect the
    remaining 15%."""
    _patch_ingest_job(
        monkeypatch,
        {
            "current_stage": "product_insights",
            "stages": [
                {"name": "download", "progress": 1.0},
                {"name": "transcribe", "progress": 1.0},
                {"name": "chapterize", "progress": 1.0},
                {"name": "summarize", "progress": 1.0},
                {"name": "highlight", "progress": 1.0},
                {"name": "product_insights", "progress": 0.5},
            ],
        },
    )

    result = await load_progress_fast("ep_1")

    # 85 (all prior, translate=0) + 15*0.5 = 92.5% — not 100%
    assert result["overall_progress"] == pytest.approx(0.925, abs=0.01)


@pytest.mark.unit
async def test_load_progress_done_is_full(monkeypatch, temp_data_dir):
    """current_stage == done → overall 100%."""
    _patch_ingest_job(
        monkeypatch,
        {
            "current_stage": "done",
            "stages": [
                {"name": n, "progress": 1.0}
                for n in (
                    "download", "transcribe", "chapterize",
                    "summarize", "highlight", "product_insights", "done",
                )
            ],
        },
    )

    result = await load_progress_fast("ep_1")

    assert result["overall_progress"] == pytest.approx(1.0)
