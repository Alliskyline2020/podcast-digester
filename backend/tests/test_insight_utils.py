"""insight_utils 工具函数单元测试。"""
from app.models import InsightItem
from app.llm_pipeline.insight_utils import (
    normalize_entity,
    dedup_entities,
    jaccard_similarity,
    dedup_insights,
    apply_topk,
)


class TestNormalizeEntity:
    def test_strips_suffixes(self):
        assert normalize_entity("OpenAI Inc") == "Openai"  # title-case after strip
        assert normalize_entity("Anthropic Corp") == "Anthropic"

    def test_case_insensitive_dedup_key(self):
        assert normalize_entity("openai").lower() == normalize_entity("OpenAI").lower()

    def test_fullwidth_to_halfwidth(self):
        assert normalize_entity("ＯｐｅｎＡＩ") == "Openai"

    def test_chinese_suffix_stripped(self):
        # "公司" 被剥离
        result = normalize_entity("字节跳动公司")
        assert "公司" not in result

    def test_empty(self):
        assert normalize_entity("") == ""
        assert normalize_entity(None) == ""


class TestDedupEntities:
    def test_case_insensitive(self):
        result = dedup_entities(["OpenAI", "openai", "OPENAI"])
        assert len(result) == 1

    def test_preserves_first_display_form(self):
        result = dedup_entities(["openai", "OpenAI"])
        assert result == ["openai"]  # 首见形保留

    def test_different_entities_kept(self):
        result = dedup_entities(["OpenAI", "Anthropic", "DeepMind"])
        assert len(result) == 3

    def test_suffix_variant_merged(self):
        result = dedup_entities(["OpenAI Inc", "OpenAI"])
        assert len(result) == 1

    def test_empty_filtered(self):
        result = dedup_entities(["", "  ", "OpenAI", None])
        assert result == ["OpenAI"]


class TestJaccard:
    def test_identical(self):
        assert jaccard_similarity("产品策略", "产品策略") == 1.0

    def test_disjoint(self):
        assert jaccard_similarity("完全不同内容", "毫无关联文字") == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity("产品策略与增长", "产品增长策略")
        assert 0 < sim < 1.0

    def test_empty(self):
        assert jaccard_similarity("", "abc") == 0.0


class TestDedupInsights:
    def _item(self, text):
        return InsightItem(text_zh=text)

    def test_keeps_distinct(self):
        items = [self._item("洞察甲"), self._item("洞察乙")]
        assert len(dedup_insights(items)) == 2

    def test_drops_near_duplicate(self):
        items = [
            self._item("OpenAI 的 GPT 模型在多模态理解上取得突破"),
            self._item("OpenAI 的 GPT 模型在多模态理解上取得突破性进展"),  # 高度相似
        ]
        assert len(dedup_insights(items, threshold=0.7)) == 1

    def test_keeps_first_on_duplicate(self):
        items = [self._item("甲洞察"), self._item("甲洞察")]
        kept = dedup_insights(items)
        assert len(kept) == 1
        assert kept[0].text_zh == "甲洞察"


class TestApplyTopk:
    def test_truncates(self):
        assert len(apply_topk([1, 2, 3, 4, 5], 3)) == 3

    def test_preserves_order(self):
        assert apply_topk(["a", "b", "c"], 2) == ["a", "b"]

    def test_no_truncation_when_k_none(self):
        assert apply_topk([1, 2, 3], None) == [1, 2, 3]

    def test_no_truncation_when_k_zero(self):
        assert apply_topk([1, 2, 3], 0) == [1, 2, 3]

    def test_k_exceeds_length(self):
        assert apply_topk([1, 2], 5) == [1, 2]
