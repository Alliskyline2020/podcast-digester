"""entity_harvest 单测: mock chat_json, 不触网。"""
import pytest

from app.services.entity_harvest import (
    expand_glossary,
    harvest_entities,
)


def test_expand_glossary_maps_wrongs_and_self():
    cache = {"姚顺宇": ["姚顺雨", "姚顺于"], "OpenAI": ["open ai"]}
    out = expand_glossary(cache)
    assert out["姚顺雨"] == "姚顺宇"
    assert out["姚顺于"] == "姚顺宇"
    assert out["姚顺宇"] == "姚顺宇"  # 规范写法自身也映射
    assert out["open ai"] == "OpenAI"
    assert out["OpenAI"] == "OpenAI"


@pytest.mark.asyncio
async def test_harvest_merges_llm_and_glossary_glossary_priority(monkeypatch):
    async def fake_chat_json(**kwargs):
        return {"entities": [
            {"canonical": "Transformer", "variants": ["传思我们", "变形金刚"]},
            {"canonical": "姚顺宇", "variants": ["姚顺雨"]},  # 与 glossary 重叠
        ]}

    monkeypatch.setattr("app.services.entity_harvest.chat_json", fake_chat_json)

    glossary_variants = {"姚顺雨": "姚顺宇", "姚顺宇": "姚顺宇"}
    out = await harvest_entities("一些文本", glossary_variants=glossary_variants)

    # LLM 新增
    assert out["传思我们"] == "Transformer"
    assert out["变形金刚"] == "Transformer"
    # glossary 优先(LLM 也给了 姚顺宇, 不冲突则共存)
    assert out["姚顺雨"] == "姚顺宇"


@pytest.mark.asyncio
async def test_harvest_fallback_to_glossary_only_on_llm_failure(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("network")

    monkeypatch.setattr("app.services.entity_harvest.chat_json", boom)
    glossary_variants = {"姚顺雨": "姚顺宇"}
    out = await harvest_entities("文本", glossary_variants=glossary_variants)
    assert out == {"姚顺雨": "姚顺宇"}  # LLM 挂了就只用 glossary


@pytest.mark.asyncio
async def test_harvest_empty_text_returns_glossary_only(monkeypatch):
    called = {"n": 0}

    async def fake_chat_json(**kwargs):
        called["n"] += 1
        return {"entities": []}

    monkeypatch.setattr("app.services.entity_harvest.chat_json", fake_chat_json)
    out = await harvest_entities("", glossary_variants={"a": "a"})
    assert out == {"a": "a"}
    assert called["n"] == 0  # 空文本不调 LLM
