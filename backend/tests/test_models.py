"""ProductInsights 模型的旧/新 shape 兼容性测试 + Segment text_zh/text_en 测试。"""
import pytest

from app.models import (
    ProductInsights,
    InsightItem,
    InsightGroup,
    InsightCategory,
    Segment,
    Transcript,
    TranscriptResponse,
)


class TestProductInsightsCompat:
    def test_legacy_list_str_upgrades(self):
        """旧 product_insights_zh: list[str] 自动升级为 InsightItem(category=other)。"""
        data = {
            "product_insights_zh": ["产品洞察一", "产品洞察二"],
            "technical_insights_zh": ["技术洞察"],
            "market_insights_zh": ["市场洞察"],
            "mentioned_companies": ["OpenAI"],
            "mentioned_technologies": ["Python"],
        }
        pi = ProductInsights(**data)
        assert len(pi.product.items) == 2
        assert pi.product.items[0].text_zh == "产品洞察一"
        assert pi.product.items[0].category == InsightCategory.OTHER
        assert len(pi.technical.items) == 1
        assert len(pi.market.items) == 1
        assert pi.mentioned_companies == ["OpenAI"]
        assert pi.mentioned_technologies == ["Python"]
        assert pi.schema_version == 3

    def test_new_shape_parses(self):
        """新 shape dict 直接解析，category 映射到枚举。"""
        data = {
            "product": {"items": [
                {"text_zh": "结构化产品洞察", "category": "product_strategy", "cited_segment_ids": [1, 2]},
            ]},
            "technical": {"items": [
                {"text_zh": "架构选型洞察", "category": "tech_architecture"},
            ]},
            "market": {"items": []},
        }
        pi = ProductInsights(**data)
        assert len(pi.product.items) == 1
        assert pi.product.items[0].category == InsightCategory.PRODUCT_STRATEGY
        assert pi.product.items[0].cited_segment_ids == [1, 2]
        assert pi.technical.items[0].category == InsightCategory.TECH_ARCHITECTURE

    def test_mixed_shape_new_keys_win(self):
        """新 key 存在时 validator 不处理旧 key（避免覆盖新数据）。"""
        data = {
            "product": {"items": [{"text_zh": "新结构洞察"}]},
            "product_insights_zh": ["应该被忽略"],
        }
        pi = ProductInsights(**data)
        assert len(pi.product.items) == 1
        assert pi.product.items[0].text_zh == "新结构洞察"

    def test_empty_legacy_lists(self):
        data = {"product_insights_zh": [], "technical_insights_zh": [], "market_insights_zh": []}
        pi = ProductInsights(**data)
        assert pi.product.items == []
        assert pi.technical.items == []
        assert pi.market.items == []

    def test_legacy_filters_empty_strings(self):
        data = {"product_insights_zh": ["有效洞察", "", "   "]}
        pi = ProductInsights(**data)
        assert len(pi.product.items) == 1

    def test_invalid_category_raises(self):
        """模型层对非法 category 严格报错（代码层兜底在 extract 阶段做）。"""
        with pytest.raises(Exception):
            ProductInsights(product={"items": [{"text_zh": "测试洞察", "category": "not_a_real_category"}]})

    def test_insight_item_rejects_empty_text(self):
        with pytest.raises(Exception):
            InsightItem(text_zh="")  # min_length=1，非空即可

    def test_default_construction(self):
        pi = ProductInsights()
        assert pi.product.items == []
        assert pi.technical.items == []
        assert pi.market.items == []
        assert pi.schema_version == 3
        assert pi.mentioned_companies == []

    def test_roundtrip_serialization(self):
        """新结构 model_dump → 重新构造应等价。"""
        pi = ProductInsights(
            product={"items": [{"text_zh": "往返测试洞察", "category": "product_ux", "rationale_zh": "因为..."}]}
        )
        dumped = pi.model_dump()
        pi2 = ProductInsights(**dumped)
        assert pi2.product.items[0].text_zh == "往返测试洞察"
        assert pi2.product.items[0].category == InsightCategory.PRODUCT_UX


class TestSegmentLanguageFields:
    """测试 Segment 新增的 text_zh / text_en 字段（Task 2, Phase 2）。"""

    def test_new_fields_default_to_none(self):
        """新建 Segment 时，text_zh 和 text_en 默认为 None。"""
        seg = Segment(id=0, start_ms=0, end_ms=10, text_original="hi")
        assert seg.text_zh is None
        assert seg.text_en is None

    def test_roundtrip_preserves_new_fields(self):
        """Segment 的 text_zh/text_en 在 model_dump → 重建后保持不变。"""
        seg = Segment(
            id=0,
            start_ms=0,
            end_ms=10,
            text_original="你好",
            text_zh="你好",
            text_en="hello",
        )
        dumped = seg.model_dump()
        seg2 = Segment(**dumped)
        assert seg2.text_zh == "你好"
        assert seg2.text_en == "hello"

    def test_old_data_compatibility(self):
        """只有旧字段（text_original/text_translated）的 dict 也能构造 Segment，新字段默认 None。"""
        old_dict = {
            "id": 0,
            "start_ms": 0,
            "end_ms": 10,
            "text_original": "hello",
            "text_translated": "你好",
        }
        seg = Segment(**old_dict)
        assert seg.text_zh is None
        assert seg.text_en is None
        assert seg.text_original == "hello"
        assert seg.text_translated == "你好"

    def test_transcript_roundtrip_carries_new_fields(self):
        """Transcript 的 Segment 中携带 text_zh，经 model_dump → 重建后保留。"""
        transcript = Transcript(
            episode_id="ep_test",
            language="zh",
            segments=[
                Segment(
                    id=0,
                    start_ms=0,
                    end_ms=10,
                    text_original="你好",
                    text_zh="你好",
                    text_en="hello",
                )
            ],
        )
        dumped = transcript.model_dump()
        transcript2 = Transcript(**dumped)
        assert transcript2.segments[0].text_zh == "你好"
        assert transcript2.segments[0].text_en == "hello"

    def test_transcript_response_exposes_new_fields(self):
        """TranscriptResponse 包含 Segment，model_dump 后输出 text_zh/text_en。"""
        response = TranscriptResponse(
            segments=[
                Segment(
                    id=0,
                    start_ms=0,
                    end_ms=10,
                    text_original="你好",
                    text_zh="你好",
                    text_en="hello",
                )
            ]
        )
        dumped = response.model_dump()
        assert "segments" in dumped
        assert dumped["segments"][0]["text_zh"] == "你好"
        assert dumped["segments"][0]["text_en"] == "hello"
