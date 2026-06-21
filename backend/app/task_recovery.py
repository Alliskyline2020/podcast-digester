"""
任务恢复模块
服务重启后自动恢复未完成的任务
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .database import EpisodeRepository, IngestJobRepository
from .models import EpisodeStatus
from .ingest import pipeline


logger = logging.getLogger(__name__)


# 任务恢复检查间隔（秒）
RECOVERY_CHECK_INTERVAL = 5


async def recover_pending_tasks() -> None:
    """
    恢复所有未完成的任务

    在服务启动时调用，查找所有处于非完成状态的任务，
    根据 checkpoint 决定是恢复还是重置任务状态。
    """
    try:
        # 获取所有非终态的任务
        pending_episodes = await EpisodeRepository.get_by_statuses([
            EpisodeStatus.PENDING,
            EpisodeStatus.DOWNLOADING,
            EpisodeStatus.ASR_RUNNING,
            EpisodeStatus.LLM_RUNNING,
        ])

        if not pending_episodes:
            logger.info("No pending tasks to recover")
            return

        logger.info(f"Found {len(pending_episodes)} pending tasks, recovering...")

        for ep in pending_episodes:
            episode_id = ep["id"]
            current_status = ep["status"]

            try:
                # 尝试恢复任务
                await _recover_single_task(episode_id, current_status)

            except Exception as e:
                logger.error(f"Failed to recover task {episode_id}: {e}")
                # 标记为失败
                await EpisodeRepository.update_status(
                    episode_id,
                    EpisodeStatus.FAILED,
                    error_msg=f"任务恢复失败: {e}",
                )

        logger.info("Task recovery completed")

    except Exception as e:
        logger.error(f"Task recovery failed: {e}")


async def _recover_single_task(episode_id: str, current_status: str) -> None:
    """
    恢复单个任务

    根据当前状态和 checkpoint 决定恢复策略：
    - 如果有 transcript.json，跳过 ASR，直接进入 LLM
    - 如果没有 transcript，从头开始 ASR
    """
    logger.info(f"Recovering task {episode_id} from status {current_status}")

    from .config import DATA_DIR
    media_dir = DATA_DIR / "media" / episode_id

    # 检查 checkpoint 文件
    transcript_file = media_dir / "transcript.json"
    highlight_file = media_dir / "highlight.json"

    # 获取 ingest_job 信息
    job_data = await IngestJobRepository.get_by_id(episode_id)

    if job_data:
        current_stage = job_data.get("current_stage", "pending")
    else:
        current_stage = "pending"

    # 决定恢复策略
    if highlight_file.exists():
        # 任务实际已完成，只是状态未更新
        logger.info(f"Task {episode_id} already completed (highlight exists)")
        await EpisodeRepository.update_status(episode_id, EpisodeStatus.READY)
        return

    if transcript_file.exists():
        # ASR 已完成，从 LLM 阶段恢复
        logger.info(f"Task {episode_id} resuming from LLM stage (transcript exists)")
        await EpisodeRepository.update_status(episode_id, EpisodeStatus.LLM_RUNNING)
        # 重新加载 transcript 并运行 LLM 流水线
        await _resume_llm_from_checkpoint(episode_id, job_data)
    else:
        # 从头开始
        logger.info(f"Task {episode_id} restarting from beginning")
        await EpisodeRepository.update_status(episode_id, EpisodeStatus.PENDING)
        # 需要原始输入才能重新启动，这里暂时不处理
        logger.warning(f"Cannot restart task {episode_id} without original input")


async def _resume_llm_from_checkpoint(episode_id: str, job_data: Optional[dict]) -> None:
    """
    从 transcript checkpoint 恢复 LLM 流水线

    Args:
        episode_id: 节目 ID
        job_data: ingest_job 数据（可能为 None）
    """
    from .llm_pipeline import run_llm_pipeline
    from .asr import Transcript

    from .config import DATA_DIR
    media_dir = DATA_DIR / "media" / episode_id

    try:
        # 加载 transcript
        transcript_data = _load_json_file(media_dir / "transcript.json")
        if not transcript_data:
            raise ValueError("Failed to load transcript checkpoint")

        transcript = Transcript(**transcript_data)

        # 获取标题
        ep_data = await EpisodeRepository.get_by_id(episode_id)
        title = ep_data.get("title", "Unknown")

        # 进度回调
        def on_progress(stage: str, progress: float):
            logger.debug(f"LLM progress for {episode_id}: {stage} = {progress}")

        # 运行 LLM 流水线
        await run_llm_pipeline(episode_id, title, transcript, on_progress)

        logger.info(f"LLM pipeline resumed and completed for {episode_id}")

    except Exception as e:
        logger.error(f"Failed to resume LLM pipeline for {episode_id}: {e}")
        raise


def _load_json_file(file_path: Path) -> Optional[dict]:
    """加载 JSON 文件"""
    from .utils.io import safe_read_json
    return safe_read_json(file_path)


async def start_recovery_daemon() -> None:
    """
    启动任务恢复守护进程

    定期检查并恢复未完成的任务
    """
    logger.info("Starting task recovery daemon")

    while True:
        try:
            await recover_pending_tasks()
        except Exception as e:
            logger.error(f"Recovery daemon error: {e}")

        await asyncio.sleep(RECOVERY_CHECK_INTERVAL)
