"""洞察后处理工具：实体规范化、去重、top-k 截断。

纯函数，无 LLM 调用，供 llm_product_insights 在解析 LLM 输出后清洗数据。
"""
import re
import logging
from typing import Iterable, List

from ..models import InsightItem

logger = logging.getLogger(__name__)

# 实体名后缀停用词（去重时剥离）
_NORMALIZE_STOPWORDS = {
    "inc", "corp", "co", "llc", "ltd", "gmbh", "the",
    "公司", "有限", "股份有限公司", "有限公司",
}


def normalize_entity(name: str) -> str:
    """归一化实体名：去后缀(Inc/Corp/公司)、全角转半角、title-case。

    用于生成去重 key；显示形由 dedup_entities 保留首见原样。
    """
    if not name:
        return ""
    s = name.strip().strip("\"'.,;·")
    # 全角→半角
    s = s.translate(str.maketrans({chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}))
    s = re.sub(r"\s+", " ", s)
    # 剥离尾部公司后缀（中文无空格分词，英文停用词 split 抓不到）
    s = re.sub(r"(股份有限公司|有限责任公司|有限公司|公司)$", "", s)
    tokens = [t for t in s.split() if t.lower() not in _NORMALIZE_STOPWORDS]
    s = " ".join(tokens)
    # 纯 ASCII 产品名 title-case（OpenAI 而非 openai）；含 CJK 不动
    if s.isascii() and s:
        s = s.title()
    return s


def dedup_entities(names: Iterable[str]) -> List[str]:
    """按 normalize key 去重，保留首见的原始显示形。"""
    seen: dict = {}
    for n in names:
        if not isinstance(n, str):
            continue
        key = normalize_entity(n).lower()
        if key and key not in seen:
            seen[key] = n.strip()
    return list(seen.values())


def _tokenize_zh(text: str) -> List[str]:
    """简易分词：ASCII 按空白分词小写，CJK 按单字。"""
    tokens: List[str] = []
    for chunk in re.split(r"\s+", text):
        if not chunk:
            continue
        if chunk.isascii():
            tokens.append(chunk.lower())
        else:
            tokens.extend(list(chunk))
    return tokens


def jaccard_similarity(a: str, b: str) -> float:
    """两段文本的 Jaccard 相似度（基于 token 集合交集/并集）。"""
    sa = set(_tokenize_zh(a))
    sb = set(_tokenize_zh(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def dedup_insights(items: List[InsightItem], threshold: float = 0.7) -> List[InsightItem]:
    """同域内去重：与已保留的任一条 Jaccard > threshold 则丢弃后者。

    threshold=0.7 较保守，只抓高度相似的近重复。
    """
    kept: List[InsightItem] = []
    for item in items:
        if any(jaccard_similarity(item.text_zh, k.text_zh) > threshold for k in kept):
            logger.debug(f"Drop duplicate insight: {item.text_zh[:40]}")
            continue
        kept.append(item)
    return kept


def apply_topk(items: list, k) -> list:
    """取前 k 条保留原顺序。k 为 None 或 <=0 表示不截断。"""
    if not k or k <= 0:
        return items
    return items[:k]
