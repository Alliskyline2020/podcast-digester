"""
LLM Pipeline Legacy Compatibility Layer

提供向后兼容的 run_llm_pipeline 函数，供 task_recovery.py 使用

注意：这是遗留代码的兼容层，新代码应直接使用 pipeline.py 的流程
"""
import logging
from typing import Optional, Callable

from . import (
    split_into_chapters,
    generate_chapter_summaries,
    translate_segments,
    extract_highlights,
)
from ..utils.io import atomic_write_json
from ..config import DEEPSEEK_MODEL


logger = logging.getLogger(__name__)


async def run_llm_pipeline(
    episode_id: str,
    title: str,
    transcript,
    on_progress: Optional[Callable] = None,
    stages: list = None,
) -> None:
    """
    运行完整的 LLM 流水线（兼容层）

    这是 task_recovery.py 使用的遗留接口。
    新代码应通过 pipeline.py 的 AudioProcessPipeline.process_episode() 运行。

    Args:
        episode_id: 节目 ID
        title: 节目标题
        transcript: Transcript 对象
        on_progress: 进度回调 (stage_id, progress)
        stages: 阶段列表引用（兼容参数，未使用）
    """
    from pathlib import Path
    from ..models import Outline

    def update_progress(stage_id: str, progress: float):
        if on_progress:
            on_progress(stage_id, progress)

    from ..config import DATA_DIR
    media_dir = DATA_DIR / "media" / episode_id

    # === 阶段 1: Chapterize（分章）===
    update_progress("chapterize", 0.0)
    chapters = await split_into_chapters(
        transcript,
        progress_cb=lambda p: update_progress("chapterize", p),
    )

    # 保存 outline
    outline = Outline(
        episode_id=episode_id,
        entries=[
            {
                "title_zh": ch.get("title_zh", ch.get("title", "")),
                "start_ms": ch.get("start_ms", 0),
                "end_ms": ch.get("end_ms", 0),
                "chapter_summary_id": f"ch{i}",
            }
            for i, ch in enumerate(chapters)
        ],
    )
    # 保存到文件系统
    atomic_write_json(media_dir / "outline.json", outline.model_dump())
    # 保存到数据库
    try:
        from app.repositories import OutlineRepository
        await OutlineRepository.set(episode_id, outline.model_dump()['entries'])
    except Exception as e:
        logger.warning(f"Failed to save outline to database: {e}")
    update_progress("chapterize", 1.0)

    # === 阶段 2: Summarize（章节摘要）===
    update_progress("summarize", 0.0)
    summaries = await generate_chapter_summaries(
        chapters,
        transcript,
        progress_cb=lambda p, c=None, t=None: update_progress("summarize", p),
    )

    # 保存 summaries
    atomic_write_json(media_dir / "summaries.json", summaries)
    # 保存到数据库
    try:
        from app.repositories import SummariesRepository
        await SummariesRepository.set(episode_id, summaries)
    except Exception as e:
        logger.warning(f"Failed to save summaries to database: {e}")
    update_progress("summarize", 1.0)

    # === 阶段 3: Translate（翻译，非中文时执行）===
    if transcript.language != "zh":
        update_progress("translate", 0.0)
        translations = await translate_segments(
            transcript,
            progress_cb=lambda p: update_progress("translate", p),
        )
        # 应用翻译
        for t in translations:
            if t["id"] < len(transcript.segments):
                transcript.segments[t["id"]].text_translated = t["text_zh"]

        # 保存 transcript
        atomic_write_json(media_dir / "transcript.json", transcript.model_dump())
        update_progress("translate", 1.0)
    else:
        update_progress("translate", 1.0)

    # === 阶段 4: Highlight（亮点提炼）===
    update_progress("highlight", 0.0)

    duration_min = sum(
        (seg.end_ms - seg.start_ms) for seg in transcript.segments
    ) / 1000 / 60

    highlight = await extract_highlights(
        title,
        duration_min,
        chapters,
        summaries,
        transcript,
        progress_cb=lambda p: update_progress("highlight", p),
    )

    # 保存 highlight
    atomic_write_json(media_dir / "highlight.json", highlight.model_dump())
    # 保存到数据库
    try:
        from app.repositories import HighlightRepository
        await HighlightRepository.set(episode_id, highlight.model_dump())
    except Exception as e:
        logger.warning(f"Failed to save highlight to database: {e}")
    update_progress("highlight", 1.0)

    logger.info(f"LLM pipeline completed for {episode_id}")
