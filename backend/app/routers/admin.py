"""Admin router: 保护性的运营端点。

Routes:
- POST /api/admin/batch-sync-subtitles   批量字幕段落同步

所有路由通过 verify_admin 依赖强制认证：
- 配置了 PODCAST_DIGESTER_ADMIN_TOKEN 时校验 X-Admin-Token 头；
- 未配置时仅允许 loopback 访问。
"""
import logging
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import deps
from ..deps import verify_admin
from ..utils.io import safe_read_json


router = APIRouter(dependencies=[Depends(verify_admin)])
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class BatchSyncRequest(BaseModel):
    """批量字幕同步请求"""
    episode_ids: list[str] = Field(..., description="要同步的节目ID列表")


class BatchSyncResponse(BaseModel):
    """批量字幕同步响应"""
    total: int = Field(..., description="总数")
    successful: list[str] = Field(..., description="成功的节目ID列表")
    failed: list[dict[str, str]] = Field(..., description="失败的节目ID和错误信息")
    duration_ms: int = Field(..., description="处理耗时（毫秒）")


# ==================== Routes ====================

@router.post(
    "/api/admin/batch-sync-subtitles",
    response_model=BatchSyncResponse,
)
async def batch_sync_subtitle_segments(request: BatchSyncRequest) -> BatchSyncResponse:
    """
    批量同步字幕分段

    对多个已有节目进行字幕段落合并处理，无需重新下载音频或重新转录。
    """
    start_time = time.time()
    successful = []
    failed = []

    # 延迟 import：避免 router 加载时硬依赖 database
    from ..database import EpisodeRepository

    # 验证输入
    if not request.episode_ids:
        raise HTTPException(status_code=400, detail="episode_ids 列表不能为空")

    # 验证episode_ids格式
    if not isinstance(request.episode_ids, list):
        raise HTTPException(status_code=400, detail="episode_ids 必须是数组")

    # 验证数量限制
    if len(request.episode_ids) > 100:
        raise HTTPException(status_code=400, detail="单次批量操作不能超过100个节目")

    # 验证每个episode_id格式
    for ep_id in request.episode_ids:
        if not isinstance(ep_id, str) or not ep_id.startswith("ep_"):
            raise HTTPException(
                status_code=400,
                detail=f"无效的episode_id格式: {ep_id}"
            )

    # 准备 LLM 处理器
    llm_processor = None
    segmenter = None
    use_llm = True

    try:
        from ..services.llm_subtitle_processor import LLMSubtitleProcessor
        llm_processor = LLMSubtitleProcessor()
        logger.info("Batch sync: using LLM segmentation")
    except Exception as e:
        logger.warning(f"Batch sync: LLM initialization failed, using rule-based: {e}")
        use_llm = False

    if not use_llm:
        from ..services.subtitle_segmenter import SubtitleSegmenter
        segmenter = SubtitleSegmenter(max_chars=500, min_chars=200)
        logger.info(f"Batch sync: using rule-based segmentation")

    # 处理每个节目
    for episode_id in request.episode_ids:
        try:
            # 1. 获取节目数据
            episode = await EpisodeRepository.get_by_id(episode_id)
            if not episode:
                failed.append({"episode_id": episode_id, "error": "节目不存在"})
                logger.warning(f"Batch sync: episode {episode_id} not found")
                continue

            # 2. 读取字幕文件
            transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
            if not transcript_file.exists():
                failed.append({"episode_id": episode_id, "error": "字幕文件不存在"})
                logger.warning(f"Batch sync: transcript file not found for {episode_id}")
                continue

            transcript_data = safe_read_json(transcript_file)
            if not transcript_data or not transcript_data.get("segments"):
                failed.append({"episode_id": episode_id, "error": "字幕数据为空或格式错误"})
                logger.warning(f"Batch sync: invalid transcript data for {episode_id}")
                continue

            # 3. 为 segments 添加索引（用于映射）
            segments = transcript_data["segments"]
            for i, seg in enumerate(segments):
                if "id" not in seg:
                    seg["id"] = f"seg_{episode_id}_{i}"
                seg["_index"] = i

            # 4. 执行分段
            if use_llm:
                try:
                    paragraph_mappings = await llm_processor.segment_transcript(segments, episode_id)
                except Exception as e:
                    logger.error(f"Batch sync: LLM failed for {episode_id}, falling back to rule-based: {e}")
                    from ..services.subtitle_segmenter import SubtitleSegmenter
                    fallback_segmenter = SubtitleSegmenter(max_chars=500, min_chars=200)
                    paragraph_mappings = fallback_segmenter.segment(segments)
            else:
                paragraph_mappings = segmenter.segment(segments)

            # 5. 持久化到数据库
            await EpisodeRepository.update(episode_id, paragraph_mappings=paragraph_mappings)

            # 6. 记录成功
            successful.append(episode_id)
            logger.info(f"Batch sync: synced {episode_id} - {len(paragraph_mappings)} paragraphs from {len(segments)} segments")

        except HTTPException:
            # 重新抛出HTTP异常（验证错误）
            raise
        except Exception as e:
            # 捕获其他异常，继续处理其他节目
            failed.append({"episode_id": episode_id, "error": str(e)})
            logger.error(f"Batch sync: error processing {episode_id}: {e}", exc_info=True)

    # 计算耗时
    duration_ms = int((time.time() - start_time) * 1000)

    logger.info(f"Batch sync completed: {len(successful)}/{len(request.episode_ids)} successful, {len(failed)} failed, {duration_ms}ms")

    return BatchSyncResponse(
        total=len(request.episode_ids),
        successful=successful,
        failed=failed,
        duration_ms=duration_ms
    )
