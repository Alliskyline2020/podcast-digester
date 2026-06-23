"""llm_product_insights 单元测试。

覆盖 _build_raw_transcript 章节过滤 + _parse_insight_items 结构化解析。
verify pass / extract_product_insights 的 LLM 集成测试需要 mock chat_json。
"""
from app.models import Transcript, Segment, InsightItem, InsightCategory
from app.llm_pipeline.llm_product_insights import (
    _build_raw_transcript,
    _parse_insight_items,
)


def _make_transcript(n: int) -> Transcript:
    return Transcript(
        episode_id="t",
        language="zh",
        segments=[
            Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"s{i}")
            for i in range(n)
        ],
    )


def _make_chapters(ranges):
    return [{"start_segment_id": s, "end_segment_id": e} for s, e in ranges]


def _ids(result: str):
    return [line.split("|")[0].strip() for line in result.split("\n") if line.strip()]


class TestBuildRawTranscriptProduct:
    def test_only_selected_indices(self):
        chapters = _make_chapters([(0, 2), (3, 5), (6, 8)])
        t = _make_transcript(9)
        result = _build_raw_transcript(t, [1], chapters)
        assert _ids(result) == ["3", "4", "5"]

    def test_multiple_indices_in_chapter_order(self):
        chapters = _make_chapters([(0, 2), (3, 5), (6, 8)])
        t = _make_transcript(9)
        result = _build_raw_transcript(t, [2, 0], chapters)
        assert _ids(result) == ["0", "1", "2", "6", "7", "8"]

    def test_max_segments_truncation(self):
        chapters = _make_chapters([(0, 2), (3, 9)])
        t = _make_transcript(10)
        result = _build_raw_transcript(t, [1], chapters, max_segments=3)
        assert len(_ids(result)) == 3

    def test_empty_indices(self):
        chapters = _make_chapters([(0, 2)])
        t = _make_transcript(3)
        assert _build_raw_transcript(t, [], chapters) == ""

    def test_out_of_range_index_ignored(self):
        chapters = _make_chapters([(0, 2)])
        t = _make_transcript(3)
        result = _build_raw_transcript(t, [5], chapters)
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
        result = _build_raw_transcript(t, [0], chapters)
        assert "你好" in result
        assert "hello" not in result


class TestParseInsightItems:
    def _raw(self, text, category="other", cited=None, rationale=""):
        return {
            "text_zh": text,
            "category": category,
            "cited_segment_ids": cited or [],
            "rationale_zh": rationale,
        }

    def test_parses_valid_items(self):
        valid = {0, 1, 2}
        items = _parse_insight_items([
            self._raw("产品洞察一", "product_strategy", [0, 1]),
            self._raw("技术架构洞察", "tech_architecture", [2]),
        ], valid, "product")
        assert len(items) == 2
        assert items[0].category == InsightCategory.PRODUCT_STRATEGY
        assert items[0].cited_segment_ids == [0, 1]
        assert items[1].category == InsightCategory.TECH_ARCHITECTURE

    def test_skips_without_valid_cited(self):
        valid = {0, 1}
        items = _parse_insight_items([
            self._raw("有效洞察", cited=[0]),
            self._raw("无引用洞察", cited=[]),
            self._raw("非法引用", cited=[99]),
        ], valid, "product")
        assert len(items) == 1
        assert items[0].text_zh == "有效洞察"

    def test_invalid_category_falls_back_to_other(self):
        items = _parse_insight_items([
            self._raw("洞察", category="not_a_real_category", cited=[0]),
        ], {0}, "product")
        assert len(items) == 1
        assert items[0].category == InsightCategory.OTHER

    def test_empty_text_skipped(self):
        items = _parse_insight_items([
            self._raw("", cited=[0]),
            self._raw("   ", cited=[0]),
        ], {0}, "product")
        assert items == []

    def test_filters_invalid_cited_ids(self):
        # 99 不在 valid 集合，"x" 非整数，都应被过滤
        items = _parse_insight_items([
            self._raw("洞察", cited=[0, 99, 1, "x"]),
        ], {0, 1}, "product")
        assert items[0].cited_segment_ids == [0, 1]

    def test_non_dict_entries_skipped(self):
        items = _parse_insight_items(["string", None, 42], {0}, "product")
        assert items == []

    def test_rationale_parsed(self):
        items = _parse_insight_items([
            self._raw("洞察", cited=[0], rationale="因为具体案例"),
        ], {0}, "product")
        assert items[0].rationale_zh == "因为具体案例"

    def test_market_category(self):
        items = _parse_insight_items([
            self._raw("市场洞察", "market_trend", [0]),
        ], {0}, "market")
        assert items[0].category == InsightCategory.MARKET_TREND
