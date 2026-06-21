"""
后台任务相关的辅助函数。

抽取自 main.py 以便 router 复用，避免 router 反向 import main。
包含：
- _log_task_exception / _create_background_task：asyncio 任务的标准封装
- _sync_episode_modules：字幕同步后台任务
- _load_*_fast / _prefetch_* / _load_episode_bundle：episode 数据快速加载助手
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..deps import data_dir, logger


# ==================== asyncio Task 封装 ====================

def log_task_exception(task: asyncio.Task) -> None:
    """asyncio.Task 完成回调：记录未捕获异常，避免被 GC 静默吞掉。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            f"Background task {task.get_name()} failed: {exc}",
            exc_info=exc,
        )


def create_background_task(coro, name: str) -> asyncio.Task:
    """创建后台任务并绑定异常回调。"""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(log_task_exception)
    return task


# ==================== 字幕同步后台任务 ====================

async def sync_episode_modules(
    episode_id: str,
    updated_segments: list,
    regenerate_paragraphs: bool = True,
) -> None:
    """
    同步字幕更改到所有模块（后台任务）。

    Args:
        episode_id: 节目ID
        updated_segments: 更新后的 segments
        regenerate_paragraphs: 是否重新生成 paragraph_mappings
            （默认 True；词库纠错时应为 False，因为纠错不改段落结构）

    目前仅同步 paragraph_mappings。outline / summaries / highlight 的重生成
    依赖 LLM，调用方应显式触发对应接口；此处不做隐式重建。
    """
    # 延迟 import 避免循环依赖
    from ..database import EpisodeRepository

    if not updated_segments:
        return

    try:
        if regenerate_paragraphs:
            episode = await EpisodeRepository.get_by_id(episode_id)
            if not episode:
                logger.warning(f"[Sync Modules] episode not found: {episode_id}")
                return

            title = episode.get("title") or "Unknown"
            language = episode.get("language") or "zh"

            from .llm_semantic_segmenter import split_into_semantic_segments

            paragraph_mappings = await split_into_semantic_segments(
                segments=updated_segments,
                title=title,
                language=language,
                batch_size=800,
                progress_cb=None,
            )

            if paragraph_mappings:
                await EpisodeRepository.update(
                    episode_id,
                    paragraph_mappings=paragraph_mappings,
                )
                logger.info(
                    f"[Sync Modules] updated paragraph_mappings for {episode_id}: "
                    f"{len(paragraph_mappings)} paragraphs"
                )

    except Exception as exc:
        # 后台任务失败时：
        # 1. ERROR 级别日志（带 episode_id），便于在日志聚合里被告警捕获；
        # 2. 写一份 sync_status.json 到 episode 数据目录，让排查 / 后续前端
        #    轮询能读到失败原因，而不是无声地"一直没有 paragraph_mappings"。
        logger.error(
            f"[Sync Modules] failed episode_id=%s error=%s: %s",
            episode_id, type(exc).__name__, exc,
            exc_info=exc,
            extra={"episode_id": episode_id, "error_type": type(exc).__name__},
        )
        try:
            status_file = data_dir / "media" / episode_id / "sync_status.json"
            status_file.parent.mkdir(parents=True, exist_ok=True)
            status_file.write_text(json.dumps({
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "failed_at": datetime.now().isoformat(),
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.debug("Could not write sync_status.json", exc_info=True)
