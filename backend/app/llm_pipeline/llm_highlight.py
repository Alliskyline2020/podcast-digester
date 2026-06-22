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
from ..prompts import HIGHLIGHT_SYSTEM, build_highlight_user
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

    # 选择内容最密集的章节获取原始字幕
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    dense_chapter_ids = _get_densest_chapters(chapters, transcript, max_chapters=8)
    raw_block = _build_raw_transcript(transcript, dense_chapter_ids, max_segments=LLM_HIGHLIGHT_MAX_SEGMENTS)

    user_input = build_highlight_user(
        title, duration_min, outline_block, summaries_block, raw_block
    )

    try:
        result = await chat_json(
            system=HIGHLIGHT_SYSTEM,
            user=user_input,
            temperature=0.3,
            response_format={"type": "json_object"},
            # Highlight 输出包含多条 quote/insight/fact/contrarian/story，
            # 每条都有 text_zh + why_zh + cited_segment_ids。长节目（3h+）容易
            # 超过 4K 默认上限被截断 → JSON 解析失败。DeepSeek-chat 上限 8192。
            max_tokens=8192,
        )

        # 解析 highlights，跳过无效项
        valid_highlights = []
        for h in result.get("highlights", []):
            try:
                # 检查是否有 cited_segment_ids（必填）
                segment_ids = h.get("cited_segment_ids", [])
                if not segment_ids:
                    logger.warning(f"Skipped highlight without cited_segment_ids: {h.get('text_zh', '')[:50]}...")
                    continue

                # 从 cited_segment_ids 计算 start_ms
                start_ms = None
                # 找到第一个引用的段落的时间
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
                # 只添加有实质内容的亮点
                if item.text_zh.strip():
                    valid_highlights.append(item)
                else:
                    logger.warning(f"Skipped highlight with empty text_zh: {h}")
            except Exception as e:
                logger.warning(f"Skipped invalid highlight item: {h}, error: {e}")

        highlight = HighlightCard(
            tldr_zh=result.get("tldr_zh", ""),
            worth_listening_verdict=VerdictType(result.get("worth_listening_verdict", "skim_outline")),
            verdict_confidence=ConfidenceType(result.get("verdict_confidence", "medium")),
            target_audience_zh=result.get("target_audience_zh", ""),
            highlights=valid_highlights,
            estimated_time_saved_min=result.get("estimated_time_saved_min"),
        )

        logger.info(f"Extracted {len(highlight.highlights)} valid highlights (from {len(result.get('highlights', []))} total)")

        if progress_cb:
            progress_cb(0.8)

        return highlight

    except Exception as e:
        logger.error(f"Highlight extraction failed: {e}")
        raise RuntimeError(f"Highlight extraction failed: {e}")


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
    max_segments: int = None,
) -> str:
    """构建原始字幕块"""
    from ..config import LLM_HIGHLIGHT_MAX_SEGMENTS
    if max_segments is None:
        max_segments = LLM_HIGHLIGHT_MAX_SEGMENTS

    lines = []
    count = 0
    for seg in transcript.segments:
        if count >= max_segments:
            break
        lines.append(f"{seg.id} | {seg.text_original}")
        count += 1
    return "\n".join(lines)
