"""
阶段 5: 高亮提取
这是整条管线最核心的价值提炼层，产出 HighlightCard 供前端直接渲染信息流。

特性：
- 下发策略：通过"章节摘要集合"作为上下文池，而非海量原始字幕
- 动态判决：模型需独立计算 worth_watching_verdict
- 严格约束：5 类亮点（quote/insight/fact/contrarian/story）
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from ..llm import chat_json
from ..prompts import (
    HIGHLIGHT_SYSTEM,
    HIGHLIGHT_VERIFY_SYSTEM,
    build_highlight_user,
    build_highlight_verify_user,
)
from ..models import HighlightCard, HighlightItem, VerdictType, ConfidenceType, HighlightKind

if TYPE_CHECKING:
    from ..models import Transcript


logger = logging.getLogger(__name__)


async def extract_highlights(
    title: str,
    duration_min: float,
    chapters: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    transcript: "Transcript",
    progress_cb: Optional[callable] = None,
) -> HighlightCard:
    """
    提取节目亮点

    Args:
        title: 节目标题
        duration_min: 节目时长（分钟）
        chapters: 章节列表
        summaries: 章节摘要列表
        transcript: 转录文本
        progress_cb: 进度回调

    Returns:
        HighlightCard 对象
    """
    if progress_cb:
        progress_cb(0.0)

    # 构建上下文
    outline_block = _build_outline_block(chapters)
    summaries_block = _build_summaries_block(summaries)

    # LLM 基于内容价值排序全部章节,然后按章节边界分批(不裂语义)。
    # 长播客会分多批,每批 ≤ max_segments_per_batch,保证不超 LLM context。
    # 高价值章节在前 → 前面批次含金量高,即使总批数多也不会漏重点。
    from ..config import (
        LLM_HIGHLIGHT_MAX_SEGMENTS,
        LLM_HIGHLIGHT_VERIFY_ENABLED,
        LLM_HIGHLIGHT_TOP_K,
    )
    ranked_chapter_ids = await _rank_chapters_by_value(title, duration_min, chapters, summaries)
    batches = _split_chapters_into_batches(
        transcript, ranked_chapter_ids, chapters,
        max_segments_per_batch=LLM_HIGHLIGHT_MAX_SEGMENTS,
    )
    logger.info(
        f"[highlight] {len(batches)} 批 (chapter-aware, max {LLM_HIGHLIGHT_MAX_SEGMENTS} segs/batch), "
        f"sizes: {[len(b) for b in batches]}"
    )
    if progress_cb:
        progress_cb(0.2)

    # 每批跑 highlight 提取(分批不裂语义,合并后 verify 去重)
    all_raw_highlights = []
    first_batch_result = {}  # tldr/verdict/target_audience 等整集元数据从第一批拿
    total = len(batches)
    for i, batch_segs in enumerate(batches):
        raw_block = "\n".join(f"{sid} | {text}" for sid, text in batch_segs)
        batch_info = f"第 {i+1}/{total} 批" if total > 1 else None
        user_input = build_highlight_user(
            title, duration_min, outline_block, summaries_block, raw_block, batch_info
        )
        try:
            result = await chat_json(
                system=HIGHLIGHT_SYSTEM,
                user=user_input,
                temperature=0.3,
                response_format={"type": "json_object"},
                model="deepseek-v4-flash",  # 金句提取需要 thinking(判断价值/洞察)
                max_tokens=16384,
            )
            if i == 0:
                first_batch_result = result
            batch_hs = result.get("highlights", [])
            all_raw_highlights.extend(batch_hs)
            logger.info(
                f"[highlight] 批 {i+1}/{total}: +{len(batch_hs)} (累计 {len(all_raw_highlights)})"
            )
        except Exception as batch_e:
            logger.warning(f"[highlight] 批 {i+1}/{total} 失败, 跳过: {batch_e}")
        if progress_cb:
            progress_cb(0.2 + 0.5 * (i + 1) / total)

    # 统一解析 highlights(跨批合并)
    valid_highlights = []
    for h in all_raw_highlights:
        try:
            segment_ids = h.get("cited_segment_ids", [])
            if not segment_ids:
                logger.warning(f"Skipped highlight without cited_segment_ids: {h.get('text_zh', '')[:50]}...")
                continue
            first_seg = next((s for s in transcript.segments if s.id == segment_ids[0]), None)
            if first_seg:
                start_ms = first_seg.start_ms
            else:
                logger.warning(f"Skipped highlight with invalid segment_ids {segment_ids}: {h.get('text_zh', '')[:50]}...")
                continue
            item = HighlightItem(
                kind=HighlightKind(h.get("kind", "insight")),
                text_zh=h.get("text_zh", ""),
                why_zh=h.get("why_zh", ""),
                cited_segment_ids=segment_ids,
                start_ms=start_ms,
            )
            if item.text_zh.strip():
                valid_highlights.append(item)
            else:
                logger.warning(f"Skipped highlight with empty text_zh: {h}")
        except Exception as e:
            logger.warning(f"Skipped invalid highlight item: {h}, error: {e}")

    # verify pass:二次 LLM 审核 keep/drop(跨批合并后统一 verify,天然去重)
    if LLM_HIGHLIGHT_VERIFY_ENABLED and valid_highlights:
        if progress_cb:
            progress_cb(0.85)
        valid_highlights = await _verify_highlights(valid_highlights, transcript)

    # top-k 截断(按时长动态,与 prompt 目标范围对齐)。
    # 原 LLM_HIGHLIGHT_TOP_K=10 是硬编码,289 分钟超长播客也只留 10 条太少。
    if duration_min < 30:
        top_k = 8
    elif duration_min < 60:
        top_k = 12
    elif duration_min < 120:
        top_k = 18
    else:
        top_k = 25
    pre_topk = len(valid_highlights)
    valid_highlights = _topk_highlights(valid_highlights, top_k)

    # HighlightCard:整集元数据从第一批(含高价值章节,代表性最强)
    highlight = HighlightCard(
        tldr_zh=first_batch_result.get("tldr_zh", ""),
        worth_listening_verdict=VerdictType(first_batch_result.get("worth_listening_verdict", "skim_outline")),
        verdict_confidence=ConfidenceType(first_batch_result.get("verdict_confidence", "medium")),
        target_audience_zh=first_batch_result.get("target_audience_zh", ""),
        highlights=valid_highlights,
        estimated_time_saved_min=first_batch_result.get("estimated_time_saved_min"),
    )

    logger.info(f"Extracted {len(highlight.highlights)} highlights "
                f"({len(batches)} batches, verify+topk applied, pre-topk={pre_topk})")

    if progress_cb:
        progress_cb(0.8)

    return highlight


async def _verify_highlights(
    highlights: List[HighlightItem],
    transcript: "Transcript",
) -> List[HighlightItem]:
    """二次 LLM 审核 keep/drop。失败时优雅降级（keep all），不阻塞 pipeline。"""
    if not highlights:
        return highlights
    review_block = _build_highlight_review_block(highlights, transcript)
    try:
        result = await chat_json(
            system=HIGHLIGHT_VERIFY_SYSTEM,
            user=build_highlight_verify_user(review_block),
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        kept = _apply_verdicts(highlights, result.get("reviews", []))
        logger.info(f"[verify:highlight] {len(highlights)} → {len(kept)} (dropped {len(highlights) - len(kept)})")
        return kept
    except Exception as e:
        logger.warning(f"[verify:highlight] failed, keep all {len(highlights)}: {e}")
        return highlights


def _apply_verdicts(
    highlights: List[HighlightItem],
    reviews: List[dict],
) -> List[HighlightItem]:
    """丢 verdict=drop 的条目；越界 index 和无效 review 忽略。"""
    drop_indices = {
        r.get("index") for r in reviews
        if isinstance(r, dict) and r.get("verdict") == "drop"
    }
    return [h for i, h in enumerate(highlights) if i not in drop_indices]


def _topk_highlights(highlights: List[HighlightItem], k: int) -> List[HighlightItem]:
    """取前 k 条保留原顺序。k<=0 或 None 表示不截断。"""
    if not k or k <= 0:
        return highlights
    return highlights[:k]


def _build_highlight_review_block(
    highlights: List[HighlightItem],
    transcript: "Transcript",
) -> str:
    """构建审核输入：每条 highlight + cited segments 原文。"""
    seg_by_id = {s.id: s for s in transcript.segments}
    lines = []
    for i, h in enumerate(highlights):
        cited_texts = []
        for sid in h.cited_segment_ids[:3]:
            seg = seg_by_id.get(sid)
            if seg:
                cited_texts.append(f"[{sid}] {seg.text_translated or seg.text_original}")
        lines.append(
            f"[{i}] kind={h.kind.value}\n"
            f"  text: {h.text_zh}\n"
            f"  why: {h.why_zh}\n"
            f"  cited: {' | '.join(cited_texts)}"
        )
    return "\n".join(lines)


def _get_densest_chapters(
    chapters: List[Dict[str, Any]],
    transcript: "Transcript",
    max_chapters: int = 8,
) -> List[str]:
    """
    获取内容最密集的章节 ID

    密集度定义：段落数量 / 时长
    """
    chapter_density = []
    for i, ch in enumerate(chapters):
        start = ch["start_segment_id"]
        end = ch["end_segment_id"]
        segment_count = end - start + 1
        chapter_density.append((segment_count, i, ch))

    # 按段数排序，取最密集的
    chapter_density.sort(key=lambda x: x[0], reverse=True)
    return [f"ch{i}" for _, i, _ in chapter_density[:max_chapters]]


async def _rank_chapters_by_value(
    title: str,
    duration_min: float,
    chapters: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
) -> List[str]:
    """LLM 基于内容价值排序全部章节。

    替代机械的 _get_densest_chapters(segment 密度排序)。LLM 看全部章节
    摘要,判断哪些含数据点/深度洞察/反共识/决策故事,按价值排序返回。

    失败时 fallback 到密度排序(全部章节),保证不丢内容。
    """
    from ..llm import chat_json
    from ..prompts import RANK_CHAPTERS_SYSTEM, build_rank_chapters_user

    outline_block = _build_outline_block(chapters)
    summaries_block = _build_summaries_block(summaries)

    try:
        result = await chat_json(
            system=RANK_CHAPTERS_SYSTEM,
            user=build_rank_chapters_user(title, duration_min, outline_block, summaries_block),
            temperature=0.2,
            model="deepseek-v4-flash",  # 章节价值排序需要 thinking(判断数据点/洞察)
            max_tokens=8000,  # 94 章排序列表长,4000 不够
        )
        ranked = result.get("ranked_chapter_ids", [])
        if ranked and len(ranked) > 0:
            logger.info(f"[rank_chapters] LLM 排序 {len(ranked)} 章, top5: {ranked[:5]}")
            return ranked
        logger.warning("[rank_chapters] LLM 返回空, fallback to density")
    except Exception as e:
        logger.warning(f"[rank_chapters] LLM 排序失败, fallback to density: {e}")

    # Fallback: 密度排序,返回全部章节(不截断)
    return _get_densest_chapters(chapters, None, max_chapters=len(chapters))


def _build_raw_transcript_ranked(
    transcript: "Transcript",
    ranked_chapter_ids: List[str],
    chapters: List[Dict[str, Any]],
    max_segments: int = None,
) -> str:
    """按 LLM 排序的章节顺序填充 raw_block。

    高价值章节的 segment 优先完整保留,直到达到 max_segments 上限。
    低价值章节可能被截断或排除(如果 max_segments 不够)。这保证有限
    预算下,最重要的内容一定能被 LLM 看到。

    与 _build_raw_transcript 的区别:那个按章节自然顺序,这个按价值排序。
    """
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    if max_segments is None:
        max_segments = LLM_HIGHLIGHT_MAX_SEGMENTS

    # 解析排序后的章节索引(按价值从高到低)
    ordered_indices: List[int] = []
    for cid in ranked_chapter_ids or []:
        if isinstance(cid, str) and cid.startswith("ch"):
            try:
                idx = int(cid[2:])
                if 0 <= idx < len(chapters):
                    ordered_indices.append(idx)
            except ValueError:
                pass

    # 兜底:LLM 排序解析失败,用自然顺序
    if not ordered_indices:
        ordered_indices = list(range(len(chapters)))

    seg_by_id = {s.id: s for s in transcript.segments}
    lines: List[str] = []
    count = 0
    covered_chapters = 0

    # 按价值顺序遍历章节,逐章填充直到 max_segments
    for idx in ordered_indices:
        ch = chapters[idx]
        start = ch.get("start_segment_id")
        end = ch.get("end_segment_id")
        if not (isinstance(start, int) and isinstance(end, int)):
            continue
        chapter_seg_count = 0
        for seg_id in range(start, end + 1):
            if count >= max_segments:
                break
            seg = seg_by_id.get(seg_id)
            if seg is None:
                continue
            text = seg.text_translated or seg.text_original
            lines.append(f"{seg.id} | {text}")
            count += 1
            chapter_seg_count += 1
        if chapter_seg_count > 0:
            covered_chapters += 1
        if count >= max_segments:
            break

    logger.info(
        f"[raw_block] {count} segments from {covered_chapters}/{len(ordered_indices)} ranked chapters "
        f"(max_segments={max_segments})"
    )
    return "\n".join(lines)


def _split_chapters_into_batches(
    transcript: "Transcript",
    ranked_chapter_ids: List[str],
    chapters: List[Dict[str, Any]],
    max_segments_per_batch: int = 600,
) -> List[List[tuple]]:
    """按章节边界把 raw transcript 分成多批(不裂语义)。

    保证:
    - 每批 ≤ max_segments_per_batch(不超 LLM context)
    - 不在章节中间切(每批是若干完整章节,语义不裂)
    - 按 LLM 排序顺序分批(高价值章节在前 → 前面批次含金量高)

    特殊情况:单个章节 > max_segments_per_batch 时,该章单独成批
    (会超上限,但不在章节中间切,由调用方决定是否接受)。

    Returns:
        List[批次],每批 = [(seg_id, text), ...]
    """
    # 解析排序后的章节索引
    ordered_indices: List[int] = []
    for cid in ranked_chapter_ids or []:
        if isinstance(cid, str) and cid.startswith("ch"):
            try:
                idx = int(cid[2:])
                if 0 <= idx < len(chapters):
                    ordered_indices.append(idx)
            except ValueError:
                pass
    if not ordered_indices:
        ordered_indices = list(range(len(chapters)))

    seg_by_id = {s.id: s for s in transcript.segments}

    def collect_chapter_segs(idx: int) -> List[tuple]:
        ch = chapters[idx]
        start, end = ch.get("start_segment_id"), ch.get("end_segment_id")
        if not (isinstance(start, int) and isinstance(end, int)):
            return []
        out = []
        for seg_id in range(start, end + 1):
            seg = seg_by_id.get(seg_id)
            if seg is not None:
                text = seg.text_translated or seg.text_original
                out.append((seg.id, text))
        return out

    batches: List[List[tuple]] = []
    current: List[tuple] = []
    current_count = 0

    for idx in ordered_indices:
        ch_segs = collect_chapter_segs(idx)
        ch_size = len(ch_segs)
        if ch_size == 0:
            continue

        # 加这章会超 max,且当前批不空 → 先切批
        if current and current_count + ch_size > max_segments_per_batch:
            batches.append(current)
            current = []
            current_count = 0

        current.extend(ch_segs)
        current_count += ch_size

    if current:
        batches.append(current)

    return batches


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
    chapter_ids: List[str],
    chapters: List[Dict[str, Any]],
    max_segments: int = None,
) -> str:
    """构建原始字幕块：从指定章节的 segment id 范围取段，截到 max_segments 为止。

    之前版本忽略 chapter_ids 直接遍历 transcript 取前 N 段，导致 LLM 实际
    只看到节目开头而非"内容最密集的章节"。现在按章节顺序合并选中章节的
    segment 范围，文本优先用翻译（如有）回退原文。
    """
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    if max_segments is None:
        max_segments = LLM_HIGHLIGHT_MAX_SEGMENTS

    # chapter_ids 形如 ["ch1", "ch3"] → 章节索引集合 {1, 3}
    selected_indices: set = set()
    for cid in chapter_ids or []:
        if isinstance(cid, str) and cid.startswith("ch"):
            try:
                selected_indices.add(int(cid[2:]))
            except ValueError:
                logger.warning(f"Unparseable chapter id: {cid}")

    # 按章节顺序收集选中章节的 segment id 范围
    target_ranges: List[tuple] = []
    for i, ch in enumerate(chapters):
        if i in selected_indices:
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
            text = seg.text_translated or seg.text_original
            lines.append(f"{seg.id} | {text}")
            count += 1
        if count >= max_segments:
            break
    return "\n".join(lines)
