"""ProductInsights 模型的旧/新 shape 兼容性测试。"""
import pytest

from app.models import (
    ProductInsights,
    InsightItem,
    InsightGroup,
    InsightCategory,
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
