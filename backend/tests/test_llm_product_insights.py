"""llm_product_insights 单元测试。

覆盖 _build_raw_transcript 章节过滤 + _parse_insight_items 结构化解析 +
_verify_insights guardrail（防止 verify 把整域洞察砍光）+
_build_insight_review_block 邻段上下文。
verify pass / extract_product_insights 的 LLM 集成测试需要 mock chat_json。
"""
import pytest

from app.models import Transcript, Segment, InsightItem, InsightCategory
from app.llm_pipeline import llm_product_insights as lpi
from app.llm_pipeline.llm_product_insights import (
    _build_raw_transcript,
    _parse_insight_items,
    _build_insight_review_block,
    _verify_insights,
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


def _item(text: str, cited, category="product_strategy", rationale="r") -> InsightItem:
    return InsightItem(
        text_zh=text,
        cited_segment_ids=list(cited),
        category=InsightCategory(category),
        rationale_zh=rationale,
    )


def _transcript_with_text(n: int) -> Transcript:
    """每段 text_zh = '第{i}句'，便于断言 review block 出现了哪些邻段。"""
    return Transcript(
        episode_id="t",
        language="zh",
        segments=[
            Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000,
                    text_original=f"第{i}句内容", text_zh=f"第{i}句内容")
            for i in range(n)
        ],
    )


class TestBuildInsightReviewBlockContext:
    """verify 必须看到 cited segment 周围的上下文，否则无法判断跨段综合洞察是否真实。"""

    def test_includes_neighbor_segments_around_citation(self):
        t = _transcript_with_text(10)
        items = [_item("某综合洞察", cited=[5])]
        block = _build_insight_review_block(items, t, "product")
        # cited 5 + 邻居 3,4,6,7 都应出现
        for sid in (3, 4, 5, 6, 7):
            assert f"第{sid}句内容" in block
        # 远离的段不应出现
        assert "第0句内容" not in block
        assert "第9句内容" not in block

    def test_boundary_citation_only_has_neighbors_on_one_side(self):
        t = _transcript_with_text(10)
        items = [_item("开头洞察", cited=[0])]
        block = _build_insight_review_block(items, t, "product")
        assert "第0句内容" in block
        assert "第1句内容" in block
        assert "第2句内容" in block
        # 0 的左侧没有，不应崩溃也不应出现负 id
        assert "-1" not in block

    def test_caps_total_segments_per_item(self):
        """引用很多段时，单条 insight 给 verify 的段数有上限，避免 prompt 爆炸。"""
        t = _transcript_with_text(40)
        items = [_item("引用很多", cited=[10, 20, 30])]
        block = _build_insight_review_block(items, t, "product")
        # cap = 6（默认）：无论 cited+neighbor 并集多大，最多喂 6 段原文
        # 用 "第N句内容" 计数实际出现的段 id 数
        appeared = sum(1 for i in range(40) if f"第{i}句内容" in block)
        assert appeared <= 6

    def test_missing_segment_skipped_gracefully(self):
        t = _transcript_with_text(5)  # 只有 0-4
        items = [_item("引用越界", cited=[4, 99])]
        block = _build_insight_review_block(items, t, "product")
        assert "第4句内容" in block


class TestVerifyInsightsGuardrail:
    """
    回归：120 分钟播客曾出现 [verify:product] 7→0 / [verify:technical] 7→1 /
    [verify:market] 7→0 —— verify 把整域砍光。提取 prompt 已自带「宁缺毋滥」质量门
    且 dedup_insights 已在 verify 前去重，verify 再砍 >50% 几乎必是其自身失灵。
    guardrail：would-drop-all 或 (>50% 且 batch≥4) 时 distrust，保留全部。
    """

    @staticmethod
    async def _fake_chat_json_returning(reviews):
        async def _fake(system, user, **kw):
            return {"reviews": reviews}
        return _fake

    @pytest.mark.asyncio
    async def test_distrusts_when_verify_drops_everything(self, monkeypatch):
        """7 条全判 drop → guardrail 必须保留全部 7 条。"""
        items = [_item(f"洞察{i}", cited=[i]) for i in range(7)]
        monkeypatch.setattr(
            lpi, "chat_json",
            await self._fake_chat_json_returning(
                [{"domain": "product", "index": i, "verdict": "drop",
                  "reason": "too_generic"} for i in range(7)]
            ),
        )
        kept = await _verify_insights(items, _transcript_with_text(7), "product")
        assert len(kept) == 7

    @pytest.mark.asyncio
    async def test_distrusts_when_verify_drops_majority_of_large_batch(self, monkeypatch):
        """batch=6, drop 4 (>50%) → guardrail 保留全部。"""
        items = [_item(f"洞察{i}", cited=[i]) for i in range(6)]
        monkeypatch.setattr(
            lpi, "chat_json",
            await self._fake_chat_json_returning(
                [{"domain": "technical", "index": i, "verdict": "drop",
                  "reason": "unsupported"} for i in [0, 1, 3, 5]]
            ),
        )
        kept = await _verify_insights(items, _transcript_with_text(6), "technical")
        assert len(kept) == 6

    @pytest.mark.asyncio
    async def test_applies_minority_drops_normally(self, monkeypatch):
        """batch=5, drop 2 (≤50%) → 正常应用，保留 3。"""
        items = [_item(f"洞察{i}", cited=[i]) for i in range(5)]
        monkeypatch.setattr(
            lpi, "chat_json",
            await self._fake_chat_json_returning(
                [{"domain": "product", "index": 1, "verdict": "drop",
                  "reason": "hallucinated"},
                 {"domain": "product", "index": 3, "verdict": "drop",
                  "reason": "too_generic"}]
            ),
        )
        kept = await _verify_insights(items, _transcript_with_text(5), "product")
        assert len(kept) == 3
        kept_texts = {it.text_zh for it in kept}
        assert kept_texts == {"洞察0", "洞察2", "洞察4"}

    @pytest.mark.asyncio
    async def test_keeps_all_when_llm_raises(self, monkeypatch):
        """verify LLM 调用失败 → 优雅降级保留全部（既有行为，锁定）。"""
        items = [_item(f"洞察{i}", cited=[i]) for i in range(4)]

        async def boom(system, user, **kw):
            raise RuntimeError("upstream 500")

        monkeypatch.setattr(lpi, "chat_json", boom)
        kept = await _verify_insights(items, _transcript_with_text(4), "product")
        assert len(kept) == 4

    @pytest.mark.asyncio
    async def test_empty_items_short_circuits(self, monkeypatch):
        async def should_not_be_called(system, user, **kw):
            raise AssertionError("chat_json should not be called for empty input")
        monkeypatch.setattr(lpi, "chat_json", should_not_be_called)
        assert await _verify_insights([], _transcript_with_text(3), "product") == []

    @pytest.mark.asyncio
    async def test_drop_all_in_small_batch_also_guarded(self, monkeypatch):
        """batch=2（<4）全 drop → would-drop-all 兜底仍保留全部。"""
        items = [_item("洞察0", cited=[0]), _item("洞察1", cited=[1])]
        monkeypatch.setattr(
            lpi, "chat_json",
            await self._fake_chat_json_returning(
                [{"domain": "market", "index": 0, "verdict": "drop", "reason": "x"},
                 {"domain": "market", "index": 1, "verdict": "drop", "reason": "y"}]
            ),
        )
        kept = await _verify_insights(items, _transcript_with_text(2), "market")
        assert len(kept) == 2
