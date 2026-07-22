"""实体收割: 每集一次廉价 LLM 调用, 抽取人名/术语的 {变体: 规范写法}。

用途: 让逐段 LLM 清洗按统一规范矫正人名/术语(避免跨批拼法不一), 并作为
semantic_ok 的授权表(只放行表内矫正, 防过度纠正)。
"""
import logging
from typing import Dict, Optional

from ..llm import chat_json

logger = logging.getLogger(__name__)

HARVEST_MAX_CHARS = 12000  # 喂给 LLM 的全文上限(超长截断, 够抽实体)
# 实体表是逐段清洗「人名/术语矫正」的授权来源，JSON 被截断会导致表空 → 人名不纠正。
# 8000 预算留足余量，避免实体多时长文输出被 max_tokens 截断。对齐 polish 的 8000。
HARVEST_MAX_TOKENS = 8000

HARVEST_SYSTEM = """你从播客转录文本里抽取【专有名词的规范写法】。只抽明确出现过的, 不臆造。

输出 JSON:
{
  "entities": [
    {"canonical": "规范写法", "variants": ["ASR 可能的错写变体1", "变体2"]}
  ]
}

范围:
- 人名(说话人或被提及者): 如 canonical="姚顺宇", variants=["姚顺雨","姚顺于"]
- 专业术语/产品名/公司名: 如 canonical="Transformer", variants=["传思我们","变形金刚"]

铁律:
- canonical 必须是该名词在该领域最规范的写法
- variants 是 ASR 可能听错的变体(必须与 canonical 不同)
- 不确定的就不写, 宁缺毋滥
- 不输出普通词, 只输出专有名词"""


def _build_harvest_user(text: str) -> str:
    import json
    snippet = text[:HARVEST_MAX_CHARS]
    return (
        f"以下是播客转录文本(可能截断), 从中抽取专有名词规范写法:\n\n"
        f"{json.dumps(snippet, ensure_ascii=False)}"
    )


def expand_glossary(glossary_cache: dict) -> Dict[str, str]:
    """把 Glossary.cache({correct: [wrongs]}) 展开成 {variant: correct}。

    规范写法自身也映射(correct→correct), 便于两侧统一归一。
    """
    out: Dict[str, str] = {}
    for correct, wrongs in (glossary_cache or {}).items():
        if not correct:
            continue
        out[correct] = correct
        for w in wrongs or []:
            if w:
                out[w] = correct
    return out


async def harvest_entities(
    text: str,
    glossary_variants: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """抽全文实体, 与 glossary_variants 合并(glossary 优先)。返回 {variant: canonical}。

    LLM 失败/空文本 → 只返回 glossary_variants(可能为 {})。永不抛异常。
    """
    merged: Dict[str, str] = dict(glossary_variants or {})
    if not (text or "").strip():
        return merged
    try:
        result = await chat_json(
            system=HARVEST_SYSTEM,
            user=_build_harvest_user(text),
            temperature=0.0,
            max_tokens=HARVEST_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.warning(f"[harvest] LLM 失败, 仅用 glossary({len(merged)} 条): {e}")
        return merged
    for ent in result.get("entities", []):
        canonical = (ent.get("canonical") or "").strip()
        if not canonical:
            continue
        for v in ent.get("variants", []) or []:
            v = (v or "").strip()
            if v and v != canonical and v not in merged:  # glossary 已有的不覆盖
                merged[v] = canonical
        if canonical not in merged:
            merged[canonical] = canonical
    logger.info(f"[harvest] 实体表 {len(merged)} 条(glossary 种子 + LLM 抽取)")
    return merged
