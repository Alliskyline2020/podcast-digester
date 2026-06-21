"""
阶段 7: 持久化与状态移交
实现原子性写入策略和 EpisodeBundle 数据流。

原子性写入策略：
- 所有 JSON 文件生成后，先写入 .tmp 后缀文件
- 全部写入成功后，通过 os.rename 瞬间覆盖
- 最后更新 SQLite 中的 status = "ready"
- 确保前端轮询 API 永远不会读取到损坏或写了一半的 JSON

EpisodeBundle 数据流：
- 管线各级节点通过文件系统句柄进行解耦
- EpisodeManager 汇集所有 JSON 产物供前端 O(1) 获取
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, TYPE_CHECKING, List
from datetime import datetime


logger = logging.getLogger(__name__)


class EpisodeManager:
    """
    节目管理器
    负责汇集该 ID 目录下的所有 JSON 产物
    供前端 GET /api/episode/{id} 接口进行 O(1) 的极速组装和返回
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def get_bundle(self, episode_id: str):
        """
        汇集该 ID 目录下的所有 JSON 产物

        Args:
            episode_id: 节目 ID

        Returns:
            EpisodeBundle 对象
        """
        from app.models import Episode, EpisodeBundle
        from app.database import EpisodeRepositorySync, IngestJobRepositorySync

        # 加载基础信息
        ep_data = EpisodeRepositorySync.get_by_id_sync(episode_id)
        if not ep_data:
            raise ValueError(f"Episode {episode_id} not found")

        episode = Episode(**ep_data)

        # 加载各阶段产物
        from app.models import Transcript, Outline, HighlightCard
        transcript = self._load_json(
            episode_id, "transcript.json", Transcript
        )
        outline = self._load_json(
            episode_id, "outline.json", Outline
        )

        # 加载章节摘要
        summaries_data = self._load_json_file(episode_id, "summaries.json")
        chapter_summaries = []
        if summaries_data:
            from app.models import ChapterSummary
            chapter_summaries = [
                ChapterSummary(**s) for s in summaries_data
            ]

        # 加载亮点卡
        highlight = self._load_json(
            episode_id, "highlight.json", HighlightCard
        )

        # 加载处理任务（如果还在进行中）
        ingest_job = None
        if episode.status.value in ["pending", "downloading", "asr_running", "llm_running"]:
            job_data = IngestJobRepositorySync.get_by_id_sync(episode_id)
            if job_data:
                from app.models import IngestJob, IngestStage
                ingest_job = IngestJob(
                    episode_id=job_data["episode_id"],
                    current_stage=job_data["current_stage"],
                    stages=[IngestStage(**s) for s in job_data.get("stages", [])],
                    created_at=datetime.fromisoformat(job_data["created_at"]),
                    updated_at=datetime.fromisoformat(job_data["updated_at"]),
                )

        return EpisodeBundle(
            episode=episode,
            transcript=transcript,
            outline=outline,
            chapter_summaries=chapter_summaries,
            highlight=highlight,
            ingest_job=ingest_job,
        )

    def _load_json(self, episode_id: str, filename: str, model_class):
        """加载并解析 JSON 文件为 Pydantic 模型"""
        data = self._load_json_file(episode_id, filename)
        if data:
            # 添加 episode_id
            if "episode_id" in model_class.model_fields:
                data["episode_id"] = episode_id
            return model_class(**data)
        return None

    def _load_json_file(self, episode_id: str, filename: str) -> Optional[Dict]:
        """加载 JSON 文件"""
        from .utils.io import safe_read_json

        file_path = self.data_dir / "media" / episode_id / filename
        return safe_read_json(file_path)


class AtomicWriter:
    """
    原子性写入管理器
    确保文件写入的原子性，避免读取到损坏或写了一半的数据
    """

    def __init__(self, episode_id: str, media_dir: Path):
        self.episode_id = episode_id
        self.media_dir = media_dir
        self.temp_files = []

    def write(self, filename: str, data: Any) -> Path:
        """
        写入临时文件

        Args:
            filename: 目标文件名
            data: 要写入的数据（将被 JSON 序列化）

        Returns:
            临时文件路径
        """
        self.media_dir.mkdir(parents=True, exist_ok=True)

        temp_path = self.media_dir / f"{filename}.tmp"
        final_path = self.media_dir / filename

        # 写入临时文件
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.temp_files.append((temp_path, final_path))
        return temp_path

    def commit(self) -> None:
        """
        提交所有写入：原子性重命名所有临时文件为正式文件

        原子性：os.rename 在 POSIX 系统上是原子操作
        """
        errors = []

        for temp_path, final_path in self.temp_files:
            try:
                # 原子性重命名
                os.replace(temp_path, final_path)
                logger.debug(f"Committed {final_path.name}")
            except Exception as e:
                errors.append((final_path.name, str(e)))

        # 清理失败的临时文件
        for temp_path, _ in self.temp_files:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

        self.temp_files = []

        if errors:
            error_msg = "; ".join([f"{name}: {err}" for name, err in errors])
            raise IOError(f"Failed to commit files: {error_msg}")

        logger.info(f"All files committed for episode {self.episode_id}")

    def rollback(self) -> None:
        """回滚：删除所有临时文件"""
        for temp_path, _ in self.temp_files:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
        self.temp_files = []
        logger.info(f"Rolled back episode {self.episode_id}")


def save_episode_bundle(
    episode_id: str,
    data_dir: Path,
    transcript: Optional["Transcript"] = None,
    outline: Optional[Dict] = None,
    summaries: Optional[List] = None,
    highlight: Optional["HighlightCard"] = None,
) -> None:
    """
    保存完整的 EpisodeBundle 数据（原子性写入）

    Args:
        episode_id: 节目 ID
        data_dir: 数据目录
        transcript: 转录文本
        outline: 章节大纲
        summaries: 章节摘要
        highlight: 亮点卡
    """
    media_dir = data_dir / "media" / episode_id
    writer = AtomicWriter(episode_id, media_dir)

    try:
        # 写入所有数据到临时文件
        if transcript:
            writer.write("transcript.json", transcript.model_dump())

        if outline:
            writer.write("outline.json", outline)

        if summaries:
            writer.write("summaries.json", summaries)

        if highlight:
            writer.write("highlight.json", highlight.model_dump())

        # 原子性提交
        writer.commit()

        # 更新数据库状态为 ready
        from app.database import EpisodeRepositorySync
        EpisodeRepositorySync.update_status_sync(episode_id, "ready")

        logger.info(f"Episode bundle saved for {episode_id}")

    except Exception as e:
        writer.rollback()
        # 更新数据库状态为 failed
        from app.database import EpisodeRepositorySync
        EpisodeRepositorySync.update_status_sync(episode_id, "failed", str(e))
        raise
