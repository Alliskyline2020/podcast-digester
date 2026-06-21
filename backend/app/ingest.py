"""
Ingest 处理管道
完整的下载 → ASR → LLM 流程

使用新的模块化 pipeline (app/pipeline.py)
"""
import logging
from typing import Optional, Callable, Any

from .errors import ConcurrencyError


logger = logging.getLogger(__name__)


class IngestPipeline:
    """Ingest 处理管道 - 完全委托给 AudioProcessPipeline

    注意：此类是一个轻量级包装器，所有任务管理都由 AudioProcessPipeline 处理。
    不维护独立的任务列表，避免竞态条件。
    """

    async def run_ingest(
        self,
        episode_id: str,
        raw_input: str,
        on_progress: Optional[Callable[[str, float, float], Any]] = None,
        replace_existing: bool = False,
    ) -> None:
        """
        运行完整的 ingest 流程

        使用新的模块化 pipeline (AudioProcessPipeline)

        Args:
            episode_id: 节目 ID
            raw_input: 用户输入的 URL 或路径
            on_progress: 进度回调 (stage_id, stage_progress, overall_progress)
            replace_existing: 如果任务已存在，是否取消旧任务并创建新任务

        Raises:
            ConcurrencyError: 当任务已存在且replace_existing=False时
        """
        from .pipeline import pipeline as audio_pipeline

        # 直接委托给 AudioProcessPipeline
        # 所有任务管理（锁、取消、清理）都在 AudioProcessPipeline 中处理
        await audio_pipeline.process_episode(
            episode_id, raw_input, on_progress, replace_existing
        )

    async def cancel(self, episode_id: str) -> bool:
        """取消正在进行的任务（委托给 AudioProcessPipeline）"""
        from .pipeline import pipeline as audio_pipeline
        return await audio_pipeline.cancel(episode_id)


# 全局管道实例
pipeline = IngestPipeline()


async def run_ingest(
    episode_id: str,
    raw_input: str,
    on_progress: Optional[Callable[[str, float, float], Any]] = None,
) -> None:
    """运行 ingest 任务（便捷函数）"""
    await pipeline.run_ingest(episode_id, raw_input, on_progress)
