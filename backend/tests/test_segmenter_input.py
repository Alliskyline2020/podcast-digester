"""
P1 regression: segmenter input must consume polished text.

The single convergence point `segments_for_segmenter` builds the dicts that
`SubtitleSegmenter().segment(...)` consumes. Before the P1 fix the pipeline
fed raw `text_original` AND called generation before polish ran, so subtitle
paragraphs showed raw ASR (e.g. "我觉得 我觉得") even after polish had
produced clean punctuated text in `text_with_punct`. These tests lock the fix.
"""
from typing import List, Optional

import pytest

from app.models import Segment, Transcript
from app.services.segmenter_input import segments_for_segmenter
from app.services.subtitle_segmenter import SubtitleSegmenter


def _make_transcript(
    *,
    episode_id: str = "ep_p1",
    text_original: str = "raw asr",
    text_with_punct: Optional[str] = "润色后文本。",
    text_translated: Optional[str] = None,
    language: str = "zh",
) -> Transcript:
    return Transcript(
        episode_id=episode_id,
        language=language,
        segments=[
            Segment(
                id=0,
                start_ms=0,
                end_ms=1000,
                text_original=text_original,
                text_translated=text_translated,
                text_with_punct=text_with_punct,
            )
        ],
    )


# ==================== helper unit tests ====================


class TestSegmentsForSegmenterUsesPolishedText:
    """P1 core: helper must feed text_with_punct when present."""

    def test_uses_text_with_punct_when_set(self):
        # Arrange — raw ASR exists alongside polished text
        transcript = _make_transcript(
            text_original="raw asr", text_with_punct="润色后文本。"
        )

        # Act
        result = segments_for_segmenter(transcript)

        # Assert — segmenter's VIEW of source text uses the polished variant
        assert len(result) == 1
        assert result[0]["text_original"] == "润色后文本。"

    def test_falls_back_to_text_original_when_punct_missing(self):
        # Arrange — no polish produced yet
        transcript = _make_transcript(
            text_original="raw asr", text_with_punct=None
        )

        # Act
        result = segments_for_segmenter(transcript)

        # Assert — falls back to raw source text (content-loss guarantee)
        assert result[0]["text_original"] == "raw asr"

    def test_falls_back_to_text_original_when_punct_empty(self):
        transcript = _make_transcript(
            text_original="raw asr", text_with_punct=""
        )
        result = segments_for_segmenter(transcript)
        assert result[0]["text_original"] == "raw asr"


class TestSegmentsForSegmenterPassthroughFields:
    """All fields the segmenter reads must pass through with original semantics."""

    def test_id_uses_seg_episode_segment_pattern(self):
        transcript = _make_transcript(episode_id="ep_42")
        result = segments_for_segmenter(transcript)
        assert result[0]["id"] == "seg_ep_42_0"

    def test_timestamps_pass_through(self):
        transcript = _make_transcript()
        result = segments_for_segmenter(transcript)
        assert result[0]["start_ms"] == 0
        assert result[0]["end_ms"] == 1000

    def test_text_translated_passes_through(self):
        transcript = _make_transcript(
            text_translated="translated text", language="en"
        )
        result = segments_for_segmenter(transcript)
        assert result[0]["text_translated"] == "translated text"

    def test_index_is_enumeration_position(self):
        transcript = Transcript(
            episode_id="ep_idx",
            language="zh",
            segments=[
                Segment(
                    id=i,
                    start_ms=i * 1000,
                    end_ms=(i + 1) * 1000,
                    text_original=f"seg{i}",
                    text_with_punct=f"润色{i}。",
                )
                for i in range(3)
            ],
        )
        result = segments_for_segmenter(transcript)
        assert [d["_index"] for d in result] == [0, 1, 2]
        assert [d["text_original"] for d in result] == ["润色0。", "润色1。", "润色2。"]


# ==================== P1 end-to-end regression ====================


class TestSegmenterConsumesPolishedText:
    """End-to-end: helper output → SubtitleSegmenter → paragraph_mappings.

    Proves the P1 data transformation without needing the full pipeline:
    a Transcript whose seg.text_original is raw ASR but whose
    text_with_punct holds polished text must yield paragraphs whose
    text_original is the polished variant, not the raw one.
    """

    def test_paragraph_text_uses_polished_not_raw(self):
        # Arrange — raw ASR present, but polish has run and filled text_with_punct
        transcript = _make_transcript(
            text_original="我觉得 我觉得 这个 这个",
            text_with_punct="我觉得，我觉得，这个，这个。",
        )

        # Act — the exact chain _generate_paragraph_mappings runs
        seg_dicts = segments_for_segmenter(transcript)
        paragraphs: List[dict] = SubtitleSegmenter().segment(seg_dicts)

        # Assert — the paragraph reflects POLISHED text, not raw ASR
        assert len(paragraphs) >= 1
        assert "我觉得 我觉得" not in paragraphs[0]["text_original"]
        assert "润色" in paragraphs[0]["text_original"] or "，" in paragraphs[0]["text_original"]


# ==================== sequencing assertion ====================


class TestRegenerateAfterPolishSequencing:
    """Lightweight sequencing guard: _generate_paragraph_mappings must run
    AFTER polish, so text_with_punct is populated when the final
    paragraph_mappings are produced.

    Polish + post-polish regeneration now live in `_clean_transcript`;
    `_process_internal` delegates to it. Translate (and its own regeneration)
    remain inline in `_process_internal`.

    Chosen approach (per brief deviation note): static code-level assertion
    via `inspect`. The full async pipeline has too many side-effecting
    dependencies (yt-dlp, ASR, LLM, DB) to spy on call order reliably
    without faking the whole world. A source-level guarantee that the
    regeneration call sites exist after the polish/translate awaits is
    stronger evidence than a brittle monkeypatch and survives refactors
    of the surrounding stages.
    """

    def test_clean_transcript_regenerates_after_polish(self):
        import inspect
        from app.pipeline import AudioProcessPipeline

        source = inspect.getsource(AudioProcessPipeline._clean_transcript)

        # Polish call ...
        assert ".polish(" in source, "_clean_transcript must call SubtitleProcessor().polish"
        # ... must precede a regeneration call to _generate_paragraph_mappings
        polish_idx = source.index(".polish(")
        regen_idx = source.index("_generate_paragraph_mappings", polish_idx)
        assert regen_idx > polish_idx, (
            "_generate_paragraph_mappings must run AFTER polish in _clean_transcript"
        )

    def test_process_internal_delegates_to_clean_transcript(self):
        import inspect
        from app.pipeline import AudioProcessPipeline

        source = inspect.getsource(AudioProcessPipeline._process_internal)
        assert "_clean_transcript" in source, (
            "_process_internal must delegate cleaning (polish+regen) to _clean_transcript"
        )

    def test_process_internal_calls_generate_after_translate(self):
        import inspect
        from app.pipeline import AudioProcessPipeline

        source = inspect.getsource(AudioProcessPipeline._process_internal)

        # Translate call ...
        assert ".translate(" in source, "_process_internal must call SubtitleProcessor().translate"
        translate_idx = source.index(".translate(")
        # ... must precede another regeneration call (translate block regenerates too)
        regen_idx = source.index("_generate_paragraph_mappings", translate_idx)
        assert regen_idx > translate_idx, (
            "_generate_paragraph_mappings must be re-invoked AFTER translate completes"
        )
