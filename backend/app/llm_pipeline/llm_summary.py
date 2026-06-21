"""
阶段 3: 章节摘要
并发生成各章节的摘要。

特性：
- 并发模型：Semaphore(5) 控制最大并发数
- 独立处理：各章节摘要任务彼此独立
- 严格约束：120-220 字 + 3-6 个关键点
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from ..llm import chat_json
from ..prompts import SUMMARIZE_SYSTEM, build_summarize_user

if TYPE_CHECKING:
    from ..models import Transcript


logger = logging.getLogger(__name__)


async def generate_chapter_summary(
    chapter: Dict[str, Any],
    transcript: "Transcript",
    force_translate: bool = False,
) -> Dict[str, Any]:
    """
    生成单个章节的摘要

    Args:
        chapter: 章节数据 {"title_zh": "...", "start_segment_id": 0, "end_segment_id": 120}
        transcript: 完整转录文本
        force_translate: 是否强制翻译（即使原文是中文）

    Returns:
        ChapterSummary 数据
    """
    start_id = chapter["start_segment_id"]
    end_id = chapter["end_segment_id"]

    # 获取该章节的段落
    chapter_segs = transcript.segments[start_id:end_id + 1]

    # 如果段数过多，采样
    if len(chapter_segs) > 400:
        step = len(chapter_segs) // 400 + 1
        chapter_segs = chapter_segs[::step]

    seg_block = "\n".join(
        f"{seg.id} | {seg.text_original if not force_translate or not seg.text_translated else seg.text_translated}"
        for seg in chapter_segs
    )

    user_input = build_summarize_user(chapter["title_zh"], seg_block)

    try:
        result = await chat_json(
            system=SUMMARIZE_SYSTEM,
            user=user_input,
            temperature=0.4,
            response_format={"type": "json_object"},
        )

        return {
            "chapter_id": f"ch{chapter.get('index', '?')}",
            "content_zh": result["content_zh"],
            "key_points_zh": result["key_points_zh"],
            "cited_segment_ids": result["cited_segment_ids"],
        }

    except Exception as e:
        logger.error(f"Chapter summary failed: {e}")
        raise


async def generate_chapter_summaries(
    chapters: List[Dict[str, Any]],
    transcript: "Transcript",
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    并发生成所有章节摘要

    Args:
        chapters: 章节列表
        transcript: 完整转录文本
        progress_cb: 进度回调

    Returns:
        章节摘要列表
    """
    semaphore = asyncio.Semaphore(5)  # 最大并发 5

    async def summarize_one(chapter: Dict[str, Any]) -> Dict[str, Any]:
        async with semaphore:
            result = await generate_chapter_summary(chapter, transcript)
            if progress_cb:
                # 更新进度
                completed = chapters.index(chapter) + 1
                progress_cb(completed / len(chapters))
            return result

    # 为每个章节添加索引
    for i, ch in enumerate(chapters):
        ch["index"] = i

    results = await asyncio.gather(*[
        summarize_one(ch) for ch in chapters
    ])

    logger.info(f"Generated {len(results)} chapter summaries")

    return results
