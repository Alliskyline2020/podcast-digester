"""llm_highlight 单元测试。

覆盖 _build_raw_transcript 章节过滤 + verify pass 的 keep/drop 应用 + top-k。
extract_highlights / _verify_highlights 的 LLM 集成测试需要 mock chat_json。
"""
from app.models import Transcript, Segment, HighlightItem, HighlightKind
from app.llm_pipeline.llm_highlight import (
    _build_raw_transcript,
    _apply_verdicts,
    _topk_highlights,
    _build_highlight_review_block,
)


def _make_transcript(n_segments: int) -> Transcript:
    return Transcript(
        episode_id="test",
        language="zh",
        segments=[
            Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"seg{i}")
            for i in range(n_segments)
        ],
    )


def _make_chapters(ranges):
    return [
        {"title_zh": f"ch{i}", "start_segment_id": s, "end_segment_id": e, "index": i}
        for i, (s, e) in enumerate(ranges)
    ]


def _extract_ids(result: str):
    return [line.split("|")[0].strip() for line in result.split("\n") if line.strip()]


class TestBuildRawTranscript:
    def test_only_selected_chapter_segments(self):
        chapters = _make_chapters([(0, 2), (3, 5), (6, 8)])
        t = _make_transcript(9)
        result = _build_raw_transcript(t, ["ch1"], chapters)
        assert _extract_ids(result) == ["3", "4", "5"]

    def test_multiple_chapters_in_chapter_order(self):
        chapters = _make_chapters([(0, 2), (3, 5), (6, 8)])
        t = _make_transcript(9)
        result = _build_raw_transcript(t, ["ch2", "ch0"], chapters)
        assert _extract_ids(result) == ["0", "1", "2", "6", "7", "8"]

    def test_max_segments_truncation(self):
        chapters = _make_chapters([(0, 2), (3, 9)])
        t = _make_transcript(10)
        result = _build_raw_transcript(t, ["ch1"], chapters, max_segments=3)
        assert len(_extract_ids(result)) == 3

    def test_unknown_chapter_id_no_crash(self):
        chapters = _make_chapters([(0, 2)])
        t = _make_transcript(3)
        result = _build_raw_transcript(t, ["ch99"], chapters)
        assert result == ""

    def test_unparseable_chapter_id_skipped(self):
        chapters = _make_chapters([(0, 2)])
        t = _make_transcript(3)
        result = _build_raw_transcript(t, ["foo"], chapters)
        assert result == ""

    def test_prefers_translated_text(self):
        t = Transcript(
            episode_id="t",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=1000, text_original="hello", text_translated="你好")
            ],
        )
        chapters = [{"start_segment_id": 0, "end_segment_id": 0}]
        result = _build_raw_transcript(t, ["ch0"], chapters)
        assert "你好" in result
        assert "hello" not in result

    def test_falls_back_to_original_when_no_translation(self):
        t = _make_transcript(2)
        chapters = _make_chapters([(0, 1)])
        result = _build_raw_transcript(t, ["ch0"], chapters)
        assert "seg0" in result
        assert "seg1" in result

    def test_empty_chapter_ids_returns_empty(self):
        chapters = _make_chapters([(0, 2)])
        t = _make_transcript(3)
        assert _build_raw_transcript(t, [], chapters) == ""


class TestApplyVerdicts:
    def _items(self, n):
        return [HighlightItem(text_zh=f"h{i}") for i in range(n)]

    def test_drops_marked_entries(self):
        items = self._items(3)
        reviews = [
            {"index": 1, "verdict": "drop"},
            {"index": 0, "verdict": "keep"},
            {"index": 2, "verdict": "drop"},
        ]
        kept = _apply_verdicts(items, reviews)
        assert len(kept) == 1
        assert kept[0].text_zh == "h0"

    def test_empty_reviews_keeps_all(self):
        items = self._items(3)
        assert _apply_verdicts(items, []) == items

    def test_out_of_range_index_ignored(self):
        items = self._items(2)
        reviews = [{"index": 99, "verdict": "drop"}]
        assert len(_apply_verdicts(items, reviews)) == 2

    def test_invalid_review_entries_ignored(self):
        items = self._items(2)
        reviews = [{"verdict": "drop"}, None, "x", {"index": 0, "verdict": "keep"}]
        kept = _apply_verdicts(items, reviews)
        assert len(kept) == 2


class TestTopkHighlights:
    def _items(self, n):
        return [HighlightItem(text_zh=f"h{i}") for i in range(n)]

    def test_truncates(self):
        assert len(_topk_highlights(self._items(5), 3)) == 3

    def test_preserves_order(self):
        items = self._items(3)
        kept = _topk_highlights(items, 2)
        assert [h.text_zh for h in kept] == ["h0", "h1"]

    def test_k_none_no_truncation(self):
        items = self._items(3)
        assert _topk_highlights(items, None) == items

    def test_k_zero_no_truncation(self):
        items = self._items(3)
        assert _topk_highlights(items, 0) == items

    def test_k_exceeds_length(self):
        items = self._items(2)
        assert _topk_highlights(items, 5) == items


class TestBuildHighlightReviewBlock:
    def test_includes_text_why_and_cited(self):
        t = Transcript(
            episode_id="t",
            language="zh",
            segments=[Segment(id=0, start_ms=0, end_ms=1000, text_original="原文内容")],
        )
        h = HighlightItem(
            text_zh="金句内容",
            why_zh="值得记的理由",
            cited_segment_ids=[0],
            kind=HighlightKind.QUOTE,
        )
        block = _build_highlight_review_block([h], t)
        assert "金句内容" in block
        assert "值得记的理由" in block
        assert "原文内容" in block
        assert "quote" in block

    def test_empty_highlights(self):
        t = _make_transcript(1)
        assert _build_highlight_review_block([], t) == ""

    def test_missing_segment_skipped(self):
        t = _make_transcript(1)  # 只有 seg id 0
        h = HighlightItem(text_zh="引用不存在的段", cited_segment_ids=[99])
        block = _build_highlight_review_block([h], t)
        assert "引用不存在的段" in block
        # cited 行不应包含不存在的 segment 文本
        assert "seg99" not in block
