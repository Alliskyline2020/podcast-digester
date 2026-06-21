"""
产品和技术洞察生成
从播客内容中提取产品策略、技术架构和行业洞察
"""
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING, Callable

from ..llm import chat_json
from ..prompts import PRODUCT_INSIGHTS_SYSTEM, build_product_insights_user
from ..models import ProductInsights

if TYPE_CHECKING:
    from ..models import Transcript, Outline, ChapterSummary, HighlightCard


logger = logging.getLogger(__name__)


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
    raw_block = _build_raw_transcript(transcript, dense_chapter_ids, max_segments=LLM_HIGHLIGHT_MAX_SEGMENTS)

    user_input = build_product_insights_user(
        title, duration_min, outline_block, summaries_block, raw_block
    )

    try:
        result = await chat_json(
            system=PRODUCT_INSIGHTS_SYSTEM,
            user=user_input,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        insights = ProductInsights(
            product_insights_zh=result.get("product_insights_zh", []),
            technical_insights_zh=result.get("technical_insights_zh", []),
            market_insights_zh=result.get("market_insights_zh", []),
            mentioned_companies=result.get("mentioned_companies", []),
            mentioned_technologies=result.get("mentioned_technologies", []),
        )

        logger.info(f"Extracted product insights: {len(insights.product_insights_zh)} product, "
                    f"{len(insights.technical_insights_zh)} technical, "
                    f"{len(insights.market_insights_zh)} market, "
                    f"{len(insights.mentioned_companies)} companies, "
                    f"{len(insights.mentioned_technologies)} technologies")

        if progress_cb:
            progress_cb(1.0)

        return insights

    except Exception as e:
        logger.error(f"Product insights extraction failed: {e}")
        raise RuntimeError(f"Product insights extraction failed: {e}")


async def run_product_insights_stage(
    episode_id: str,
    data_dir: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> ProductInsights:
    """
    运行产品洞察生成阶段

    Args:
        episode_id: 节目 ID
        data_dir: 数据目录
        on_progress: 进度回调

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
        progress_cb=on_progress,
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
