"""
产品和技术洞察生成
从播客内容中提取产品策略、技术架构和行业洞察
"""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Callable

from ..llm import chat_json
from ..prompts import (
    PRODUCT_INSIGHTS_SYSTEM,
    PRODUCT_INSIGHTS_VERIFY_SYSTEM,
    build_product_insights_user,
    build_product_insights_verify_user,
)
from ..models import ProductInsights, InsightItem, InsightGroup, InsightCategory
from .insight_utils import dedup_insights, dedup_entities, apply_topk
from ._segtext import chinese_text

if TYPE_CHECKING:
    from ..models import Transcript, Outline, ChapterSummary, HighlightCard


logger = logging.getLogger(__name__)

# verify 阶段调参：保守的质量门，默认 keep。
_VERIFY_CONTEXT_HALF_WINDOW = 2    # 每条 cited 取 ±2 邻段作上下文，让 verify 看到主题是否真被讨论
_VERIFY_MAX_SEGMENTS_PER_ITEM = 6  # 单条 insight 喂给 verify 的段数上限（控 prompt 体积）
_VERIFY_DISTRUST_DROP_RATIO = 0.5  # 砍掉超过此比例且 batch 够大时判 verify 自身失灵
_VERIFY_DISTRUST_MIN_BATCH = 4     # 仅在 batch ≥ 此值时按比例兜底；小 batch 由 would-drop-all 兜底


async def extract_product_insights(
    title: str,
    duration_min: float,
    chapters: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    transcript: "Transcript",
    progress_cb: Optional[Callable[[float], None]] = None,
) -> ProductInsights:
    """
    提取产品和技术洞察

    Args:
        title: 节目标题
        duration_min: 节目时长（分钟）
        chapters: 章节列表
        summaries: 章节摘要列表
        transcript: 转录文本
        progress_cb: 进度回调

    Returns:
        ProductInsights 对象
    """
    if progress_cb:
        progress_cb(0.0)

    # 构建上下文
    outline_block = _build_outline_block(chapters)
    summaries_block = _build_summaries_block(summaries)

    # 选择内容最密集的章节获取原始字幕
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    dense_chapter_ids = _get_densest_chapters(chapters, transcript, max_chapters=8)
    raw_block = _build_raw_transcript(transcript, dense_chapter_ids, chapters, max_segments=LLM_HIGHLIGHT_MAX_SEGMENTS)

    user_input = build_product_insights_user(
        title, duration_min, outline_block, summaries_block, raw_block
    )

    try:
        result = await chat_json(
            system=PRODUCT_INSIGHTS_SYSTEM,
            user=user_input,
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=8192,
        )

        from ..config import LLM_INSIGHTS_TOP_K, LLM_INSIGHTS_VERIFY_ENABLED
        seg_ids = {s.id for s in transcript.segments}

        # 解析三个 domain 的结构化 items（校验 cited_segment_ids 真实存在）
        product_items = _parse_insight_items(result.get("product", {}).get("items", []), seg_ids, "product")
        technical_items = _parse_insight_items(result.get("technical", {}).get("items", []), seg_ids, "technical")
        market_items = _parse_insight_items(result.get("market", {}).get("items", []), seg_ids, "market")

        # 每 domain: 去重 → verify（可选）→ topk
        product_items = dedup_insights(product_items)
        technical_items = dedup_insights(technical_items)
        market_items = dedup_insights(market_items)

        if LLM_INSIGHTS_VERIFY_ENABLED:
            if progress_cb:
                progress_cb(0.6)
            product_items = await _verify_insights(product_items, transcript, "product")
            technical_items = await _verify_insights(technical_items, transcript, "technical")
            market_items = await _verify_insights(market_items, transcript, "market")

        product_items = apply_topk(product_items, LLM_INSIGHTS_TOP_K)
        technical_items = apply_topk(technical_items, LLM_INSIGHTS_TOP_K)
        market_items = apply_topk(market_items, LLM_INSIGHTS_TOP_K)

        companies = dedup_entities(result.get("mentioned_companies", []))
        technologies = dedup_entities(result.get("mentioned_technologies", []))

        insights = ProductInsights(
            product=InsightGroup(items=product_items),
            technical=InsightGroup(items=technical_items),
            market=InsightGroup(items=market_items),
            mentioned_companies=companies,
            mentioned_technologies=technologies,
        )

        logger.info(f"Extracted product insights: {len(product_items)} product, "
                    f"{len(technical_items)} technical, "
                    f"{len(market_items)} market, "
                    f"{len(companies)} companies, "
                    f"{len(technologies)} technologies")

        if progress_cb:
            progress_cb(1.0)

        return insights

    except Exception as e:
        logger.error(f"Product insights extraction failed: {e}")
        # 原样上抛，保留异常类型与 retryable 属性——worker._handle_episode_failure 用
        # getattr(exc, "retryable", False) 判定：LLMError→跨轮重试，永久错/逻辑 bug→failed。
        # 切勿 raise RuntimeError(...)，那会洗掉 retryable，让本可重试的瞬态错变成终态 failed。
        raise


def _parse_insight_items(
    raw_items: List[Dict[str, Any]],
    valid_seg_ids: set,
    domain: str,
) -> List[InsightItem]:
    """解析 LLM 返回的 dict 列表为 InsightItem。

    - 校验 cited_segment_ids 真实存在（过滤无效 id）
    - 非法 category 回退 OTHER（不抛异常，保证管道不中断）
    - 无有效 cited 的条目跳过
    """
    items: List[InsightItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        text = (raw.get("text_zh") or "").strip()
        if not text:
            continue
        cited = [
            i for i in (raw.get("cited_segment_ids") or [])
            if isinstance(i, int) and i in valid_seg_ids
        ]
        if not cited:
            logger.warning(f"Skip {domain} insight without valid cited_segment_ids: {text[:40]}")
            continue
        try:
            category = InsightCategory(raw.get("category", "other"))
        except ValueError:
            logger.warning(f"Invalid category '{raw.get('category')}' for {domain}, fallback OTHER")
            category = InsightCategory.OTHER
        items.append(InsightItem(
            text_zh=text,
            cited_segment_ids=cited,
            rationale_zh=(raw.get("rationale_zh") or "").strip(),
            category=category,
        ))
    return items


async def _verify_insights(
    items: List[InsightItem],
    transcript: "Transcript",
    domain: str,
) -> List[InsightItem]:
    """二次 LLM 审核 keep/drop。

    设计原则：verify 是「保守的质量门」，**默认 keep**。只在能明确指出缺陷时才 drop
    （hallucinated 实体 / 纯空洞废话）。dedup_insights 已在 verify 前去掉近重复，
    故 verify 不再判 duplicate。失败时优雅降级（keep all）。

    Guardrail：提取 prompt 自带「宁缺毋滥」质量门 + dedup 已去重，若 verify 仍要砍
    >50%（batch≥4）或 would-drop-all，几乎必是 verify 自身对 ASR 综合洞察失灵
    （见 ep_1785889603768 实例：7→0 / 7→1 / 7→0）——此时 distrust verify 保留全部。
    """
    if not items:
        return items
    review_block = _build_insight_review_block(items, transcript, domain)
    try:
        result = await chat_json(
            system=PRODUCT_INSIGHTS_VERIFY_SYSTEM,
            user=build_product_insights_verify_user(review_block),
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        drop_indices = {
            r.get("index") for r in result.get("reviews", [])
            if r.get("verdict") == "drop" and r.get("domain") == domain
        }
        kept = [it for i, it in enumerate(items) if i not in drop_indices]
        dropped = len(items) - len(kept)

        # Guardrail 1: would-drop-all → 几乎必是 verify 失灵（提取已过质量门）
        if not kept:
            logger.warning(
                f"[verify:{domain}] would drop all {len(items)} — likely verify misfire "
                f"(extraction is pre-quality-gated), keeping all"
            )
            return items
        # Guardrail 2: 大 batch 下砍 >50% → verify 失灵信号
        if (len(items) >= _VERIFY_DISTRUST_MIN_BATCH
                and dropped > len(items) * _VERIFY_DISTRUST_DROP_RATIO):
            logger.warning(
                f"[verify:{domain}] dropped {dropped}/{len(items)} (>50%) — likely verify "
                f"misfire, keeping all"
            )
            return items

        logger.info(f"[verify:{domain}] {len(items)} → {len(kept)} (dropped {dropped})")
        return kept
    except Exception as e:
        logger.warning(f"[verify:{domain}] failed, keep all {len(items)}: {e}")
        return items


def _build_insight_review_block(
    items: List[InsightItem],
    transcript: "Transcript",
    domain: str,
) -> str:
    """构建审核输入：每条 insight + cited segments 及其邻段原文。

    邻段窗口(_VERIFY_CONTEXT_HALF_WINDOW)给 verify 足够上下文判断「该主题是否
    真的被讨论」，避免只看孤立的 1-3 条 cited 误判跨段综合洞察为 unsupported。
    单条 insight 总段数被 _VERIFY_MAX_SEGMENTS_PER_ITEM 封顶，控制 prompt 体积。
    """
    seg_by_id = {s.id: s for s in transcript.segments}
    lines = []
    for i, it in enumerate(items):
        # cited + ±邻段 并集，按 id 排序后封顶
        candidate_ids: set = set()
        for sid in it.cited_segment_ids:
            if not isinstance(sid, int):
                continue
            for delta in range(-_VERIFY_CONTEXT_HALF_WINDOW, _VERIFY_CONTEXT_HALF_WINDOW + 1):
                nid = sid + delta
                if nid >= 0 and nid in seg_by_id:
                    candidate_ids.add(nid)
        ordered_ids = sorted(candidate_ids)[:_VERIFY_MAX_SEGMENTS_PER_ITEM]
        cited_texts = [f"[{sid}] {chinese_text(seg_by_id[sid])}" for sid in ordered_ids]
        lines.append(
            f"[{domain}:{i}] category={it.category.value}\n"
            f"  text: {it.text_zh}\n"
            f"  rationale: {it.rationale_zh}\n"
            f"  cited: {' | '.join(cited_texts)}"
        )
    return "\n".join(lines)


async def run_product_insights_stage(
    episode_id: str,
    data_dir: Path,
    progress_cb: Optional[Callable[[float], None]] = None,
) -> ProductInsights:
    """
    运行产品洞察生成阶段

    Args:
        episode_id: 节目 ID
        data_dir: 数据目录
        progress_cb: 进度回调

    Returns:
        ProductInsights 对象
    """
    from ..utils.io import safe_read_json
    from ..models import Transcript, Outline

    # 加载数据
    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    transcript_data = safe_read_json(transcript_file)

    outline_file = data_dir / "media" / episode_id / "outline.json"
    outline_data = safe_read_json(outline_file)

    summaries_file = data_dir / "media" / episode_id / "summaries.json"
    summaries_data = safe_read_json(summaries_file) or []

    highlight_file = data_dir / "media" / episode_id / "highlight.json"
    highlight_data = safe_read_json(highlight_file)

    # 构建模型
    transcript = Transcript(**transcript_data)

    # 获取标题和时长
    title = highlight_data.get("tldr_zh", "Unknown")[:50]  # 使用摘要的前50字作为标题
    duration_min = int(transcript.segments[-1].end_ms / 1000 / 60) if transcript.segments else 0

    # 提取洞察
    insights = await extract_product_insights(
        title=title,
        duration_min=duration_min,
        chapters=outline_data.get("entries", []),
        summaries=summaries_data,
        transcript=transcript,
        progress_cb=progress_cb,
    )

    # 保存结果
    output_file = data_dir / "media" / episode_id / "product_insights.json"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(insights.model_dump_json(indent=2))

    logger.info(f"Product insights saved to {output_file}")

    return insights


def _get_densest_chapters(
    chapters: List[Dict[str, Any]],
    transcript: "Transcript",
    max_chapters: int = 8,
) -> List[int]:
    """获取内容最密集的章节索引"""
    chapter_density = []
    for i, ch in enumerate(chapters):
        start = ch["start_segment_id"]
        end = ch["end_segment_id"]
        segment_count = end - start + 1
        chapter_density.append((segment_count, i, ch))

    chapter_density.sort(key=lambda x: x[0], reverse=True)
    return [idx for _, idx, _ in chapter_density[:max_chapters]]


def _build_outline_block(chapters: List[Dict[str, Any]]) -> str:
    """构建大纲文本块"""
    lines = []
    for i, ch in enumerate(chapters):
        lines.append(f"ch{i}: {ch.get('title_zh', 'Unknown')} ({ch['start_segment_id']}-{ch['end_segment_id']})")
    return "\n".join(lines)


def _build_summaries_block(summaries: List[Dict[str, Any]]) -> str:
    """构建摘要文本块"""
    lines = []
    for s in summaries:
        lines.append(f"{s.get('chapter_id', '?')}: {s.get('content_zh', '')}")
        for kp in s.get("key_points_zh", []):
            lines.append(f"  - {kp}")
    return "\n".join(lines)


def _build_raw_transcript(
    transcript: "Transcript",
    chapter_indices: List[int],
    chapters: List[Dict[str, Any]],
    max_segments: int = None,
) -> str:
    """构建原始字幕块：从指定章节的 segment id 范围取段。

    之前忽略 chapter_indices 直接遍历 transcript 取前 N 段，导致 LLM 只看到
    节目开头而非"内容最密集的章节"。现在按章节顺序取选中章节的 segment 范围，
    文本优先用翻译（如有）回退原文。
    """
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    if max_segments is None:
        max_segments = LLM_HIGHLIGHT_MAX_SEGMENTS

    selected = set(chapter_indices or [])
    target_ranges: List[tuple] = []
    for i, ch in enumerate(chapters):
        if i in selected:
            start = ch.get("start_segment_id")
            end = ch.get("end_segment_id")
            if isinstance(start, int) and isinstance(end, int):
                target_ranges.append((start, end))

    seg_by_id = {s.id: s for s in transcript.segments}
    lines: List[str] = []
    count = 0
    for start_id, end_id in target_ranges:
        for seg_id in range(start_id, end_id + 1):
            if count >= max_segments:
                break
            seg = seg_by_id.get(seg_id)
            if seg is None:
                continue
            text = chinese_text(seg)
            lines.append(f"{seg.id} | {text}")
            count += 1
        if count >= max_segments:
            break
    return "\n".join(lines)
