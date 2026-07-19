"""Episodes router: CRUD + 状态管理 + insights 触发。

Routes:
- POST   /api/paste                       提交新节目（触发完整 pipeline）
- GET    /api/episodes                    节目列表（带搜索/筛选/进度）
- GET    /api/episode/{id}                节目详情 bundle
- DELETE /api/episode/{id}                删除节目
- POST   /api/episode/{id}/play           标记播放位置
- POST   /api/episode/{id}/cancel         取消处理中任务
- POST   /api/episode/{id}/resume         恢复失败任务
- POST   /api/episode/{id}/insights       生成产品/技术洞察
"""
import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import deps
from ..config import DB_PATH, settings
from ..database import EpisodeRepository, UsageLogRepository
from ..ingest import run_ingest
from ..models import (
    ConfidenceType,
    EpisodeBundle,
    EpisodeCard,
    Episode,
    EpisodeStatus,
    PasteRequest,
    PasteResponse,
    PlayRequest,
    PlayResponse,
    ProductInsights,
    StageInfo,
    VerdictType,
)
from ..rate_limit import rate_limit
from ..services.background_tasks import create_background_task
from ..services.episode_loader import (
    load_episode_bundle,
    load_highlight_fast,
    prefetch_card_meta,
    load_progress_fast,
)
from ..utils.validation import validate_raw_input


router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class ListEpisodesResponse(BaseModel):
    """节目列表响应"""
    episodes: list[EpisodeCard]


class EpisodeResponse(BaseModel):
    """节目详情响应"""
    episode: EpisodeBundle


class DeleteResponse(BaseModel):
    """删除响应"""
    success: bool
    episode_id: str


class CancelResponse(BaseModel):
    """取消响应"""
    success: bool
    episode_id: str
    status: str


class ResumeRequest(BaseModel):
    """恢复请求"""
    raw_input: Optional[str] = Field(None, description="原始输入（可选；不提供则从 source 表读取）")


class ResumeResponse(BaseModel):
    """恢复响应"""
    success: bool
    episode_id: str
    status: str


class GenerateInsightsResponse(BaseModel):
    """洞察生成响应"""
    episode_id: str
    product_insights: Optional[ProductInsights] = None
    llm_processed: bool = True
    error: Optional[str] = None


@router.post("/api/paste", response_model=PasteResponse, dependencies=[Depends(rate_limit(5, 60))])
async def paste_episode(
    request: PasteRequest,
    background_tasks: BackgroundTasks,
) -> PasteResponse:
    """
    粘贴新节目 URL

    接受 URL 或本地路径，自动识别来源并开始处理
    """
    import logging
    logger = logging.getLogger(__name__)

    # 验证并清理输入（防止命令注入、路径遍历等）
    try:
        raw_input = validate_raw_input(request.raw_input)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 生成 episode ID
    timestamp_ms = int(time.time() * 1000)
    episode_id = f"ep_{timestamp_ms}"

    # 创建 episode 记录
    episode = Episode(
        id=episode_id,
        title="处理中...",
        status=EpisodeStatus.PENDING,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # 使用事务确保创建操作的原子性
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN")

            # 创建 episode 记录
            await db.execute("""
                INSERT INTO episode (
                    id, title, status, language, media_path, is_fixture, error_msg,
                    source_type, created_at, updated_at, paragraph_mappings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.id, episode.title, episode.status.value,
                None, None, 0, None, None,
                episode.created_at.isoformat(), episode.updated_at.isoformat(), None
            ))

            # 记录使用日志（存储完整 raw_input 供 Worker 使用）
            await db.execute("""
                INSERT INTO usage_log (ts, event_type, episode_id, payload_json)
                VALUES (?, ?, ?, ?)
            """, (datetime.now().isoformat(), "paste", episode_id, raw_input))

            await db.commit()
            logger.info(f"Episode {episode_id} created (transaction committed)")

    except aiosqlite.IntegrityError as e:
        logger.error(f"Database integrity error creating episode {episode_id}: {e}")
        raise HTTPException(status_code=409, detail="节目ID冲突，请重试")
    except aiosqlite.DatabaseError as e:
        logger.error(f"Database error creating episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="数据库错误，请稍后重试")
    except Exception as e:
        logger.error(f"Unexpected error creating episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="创建节目失败")

    # Worker 进程会自动处理 pending 状态的任务
    logger.info(f"Episode {episode_id} created, waiting for Worker to process")

    # 返回卡片
    return PasteResponse(
        episode=EpisodeCard(
            id=episode.id,
            title=episode.title,
            status=episode.status,
            created_at=episode.created_at,
            is_fixture=False,
        )
    )




def _source_label_from(raw_input: str, source_type_db: Optional[str] = None) -> str:
    """从 raw_input URL 或 source_type 数据库字段推断来源平台标签。

    优先按 URL 域名匹配（更准确），匹配不到时 fallback 到 DB 里的 source_type。
    返回人类可读的标签：YouTube / B站 / 小宇宙 / 抖音 / 本地。
    """
    if raw_input:
        raw = raw_input.lower()
        if "youtube.com" in raw or "youtu.be" in raw:
            return "YouTube"
        if "bilibili.com" in raw:
            return "B站"
        if "xiaoyuzhou.com" in raw or "xiaoyuzhoufm.com" in raw:
            return "小宇宙"
        if "douyin.com" in raw:
            return "抖音"
        if raw.startswith(("/", "./", "../")) or os.path.exists(raw_input):
            return "本地"
    # URL 匹配不到，fallback 到 DB 字段（youtube/bilibili/...）
    if source_type_db:
        mapping = {
            "youtube": "YouTube",
            "bilibili": "B站",
            "xiaoyuzhou": "小宇宙",
            "xiao_yu_zhou": "小宇宙",
            "douyin": "抖音",
            "local": "本地",
        }
        return mapping.get(source_type_db.lower(), source_type_db)
    return ""


async def _batch_load_source_labels(
    episode_ids: List[str],
) -> Dict[str, tuple[Optional[str], Optional[str]]]:
    """批量加载 episode 的来源标签和原始 URL。

    先查 source 表（解析器登记），未命中的再 fallback 到 usage_log 的 paste 事件
    （历史 episode 可能没在 source 表登记，但 paste 时一定记录过 raw_input）。

    Returns:
        {episode_id: (source_label, raw_input)}。未找到的 episode 不在 dict 里。
    """
    if not episode_ids:
        return {}

    result: Dict[str, tuple[Optional[str], Optional[str]]] = {}
    placeholders = ",".join("?" * len(episode_ids))

    async with aiosqlite.connect(DB_PATH) as db:
        # 1. source 表：解析器登记的来源
        async with db.execute(
            f"SELECT episode_id, source_type, raw_input FROM source WHERE episode_id IN ({placeholders})",
            episode_ids,
        ) as cursor:
            rows = await cursor.fetchall()
        for episode_id, source_type_db, raw_input in rows:
            result[episode_id] = (source_type_db, raw_input)

        # 2. usage_log fallback：历史 episode 的 paste 事件
        missing = [eid for eid in episode_ids if eid not in result]
        if missing:
            placeholders2 = ",".join("?" * len(missing))
            async with db.execute(
                f"""SELECT episode_id, payload_json FROM usage_log
                    WHERE event_type='paste' AND episode_id IN ({placeholders2})
                    ORDER BY ts DESC""",
                missing,
            ) as cursor:
                rows2 = await cursor.fetchall()
            for episode_id, payload_json in rows2:
                if episode_id not in result:  # 取最新一条 paste
                    result[episode_id] = (None, payload_json)

    # 解析域名得到 label
    return {
        eid: (_source_label_from(raw, stype), raw)
        for eid, (stype, raw) in result.items()
    }


@router.get("/api/episodes", response_model=ListEpisodesResponse)
async def list_episodes() -> ListEpisodesResponse:
    """
    获取节目列表

    返回所有节目，按最后活动时间降序排列
    """
    episodes_data = await EpisodeRepository.list_all()

    # 批量加载处理进度的episode IDs（避免N+1查询）
    progress_episode_ids = [
        ep["id"] for ep in episodes_data
        if ep.get("status") in ["pending", "downloading", "asr_running", "llm_running"]
    ]

    # 批量加载所有进度信息
    progress_cache = {}
    if progress_episode_ids:
        from ..database import IngestJobRepository
        for ep_id in progress_episode_ids:
            progress_info = await load_progress_fast(ep_id)
            if progress_info:
                progress_cache[ep_id] = progress_info

    # 预构造 card 列表，确定每条是否需要 duration（避免在循环里判断时卡事件循环）
    cards = [EpisodeCard(**ep_data) for ep_data in episodes_data]

    # 并发预取所有 highlight/duration（FS 读推到线程池，不阻塞事件循环）
    meta_results = await asyncio.gather(
        *[prefetch_card_meta(c.id, need_duration=not c.duration_min) for c in cards]
    )
    meta_cache = {c.id: meta_results[i] for i, c in enumerate(cards)}

    # 批量加载来源标签（URL 域名解析：YouTube/B站/小宇宙/抖音/本地）
    source_labels = await _batch_load_source_labels([c.id for c in cards])

    # 用预取结果填充 card
    episodes = []
    for card in cards:
        highlight, duration = meta_cache.get(card.id, (None, None))

        if highlight:
            card.tldr_zh = highlight.get("tldr_zh")
            # highlight 来自 load_highlight_fast（raw dict），verdict/confidence 是 str；
            # 显式转 enum，避免 FastAPI 序列化 enum 字段收到 str 触发 pydantic 警告
            verdict_raw = highlight.get("worth_listening_verdict")
            card.worth_listening_verdict = VerdictType(verdict_raw) if verdict_raw else None
            confidence_raw = highlight.get("verdict_confidence")
            card.verdict_confidence = ConfidenceType(confidence_raw) if confidence_raw else None
            card.target_audience_zh = highlight.get("target_audience_zh")
            card.highlights_count = len(highlight.get("highlights", []))

        if not card.duration_min and duration is not None:
            card.duration_min = duration

        # 填充来源标签（语种/时长已有字段，来源需要从 source/usage_log 推断）
        source_label, raw_input = source_labels.get(card.id, ("", ""))
        if source_label:
            card.source_type = source_label
        if raw_input:
            card.source_url = raw_input

        # 从缓存加载处理进度（进行中时）
        if card.id in progress_cache:
            progress_info = progress_cache[card.id]
            card.current_stage = progress_info.get("current_stage")
            card.stages = [StageInfo(**s) for s in progress_info.get("stages", [])]
            card.overall_progress = progress_info.get("overall_progress", 0.0)

        episodes.append(card)

    return ListEpisodesResponse(episodes=episodes)




@router.get("/api/episode/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: str) -> EpisodeResponse:
    """
    获取节目完整数据

    返回 EpisodeBundle 包含所有关联数据
    """
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 加载完整数据
    bundle = await load_episode_bundle(episode_id)

    # 填充来源标签（与 list_episodes 保持一致，DB 里 source_type 字段对历史 episode 是空）
    source_labels = await _batch_load_source_labels([episode_id])
    source_label, raw_input = source_labels.get(episode_id, ("", ""))
    if source_label:
        bundle.episode.source_type = source_label
    if raw_input and hasattr(bundle.episode, "source_url"):
        bundle.episode.source_url = raw_input

    return EpisodeResponse(episode=bundle)




@router.delete("/api/episode/{episode_id}", response_model=DeleteResponse)
async def delete_episode(episode_id: str) -> DeleteResponse:
    """
    删除节目

    删除数据库记录和本地媒体文件（事务处理）
    """
    import logging
    logger = logging.getLogger(__name__)

    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    if ep_data.get("is_fixture"):
        raise HTTPException(status_code=403, detail="内置示例节目不能删除")

    # 使用事务确保删除操作的原子性
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN")

            # 删除数据库记录（会级联删除相关记录）
            cursor = await db.execute(
                "DELETE FROM episode WHERE id = ?", (episode_id,)
            )
            deleted = cursor.rowcount > 0

            if not deleted:
                await db.rollback()
                raise HTTPException(status_code=500, detail="删除失败")

            # 记录使用日志
            await db.execute("""
                INSERT INTO usage_log (ts, event_type, episode_id, payload_json)
                VALUES (?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                "delete",
                episode_id,
                None
            ))

            await db.commit()

            logger.info(f"Episode {episode_id} deleted successfully (transaction committed)")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete episode {episode_id}: {e}")
        raise HTTPException(status_code=500, detail="删除失败")

    # 删除媒体文件（在事务成功后）
    media_dir = deps.data_dir / "media" / episode_id
    if media_dir.exists():
        import shutil
        try:
            shutil.rmtree(media_dir, ignore_errors=True)
            logger.info(f"Media files deleted for {episode_id}")
        except Exception as e:
            logger.warning(f"Failed to delete media files for {episode_id}: {e}")

    return DeleteResponse(success=True, episode_id=episode_id)




@router.post("/api/episode/{episode_id}/play", response_model=PlayResponse)
async def mark_played(episode_id: str, request: PlayRequest = None) -> PlayResponse:
    """
    标记播放

    更新最后播放时间，记录播放位置
    """
    # 更新活动时间
    await EpisodeRepository.update_last_activity(episode_id)

    # 记录使用日志
    payload = {"position_ms": request.position_ms} if request and request.position_ms else None
    await UsageLogRepository.log({
        "event_type": "play_start",
        "episode_id": episode_id,
        "payload_json": str(payload) if payload else None,
    })

    return PlayResponse()




@router.post("/api/episode/{episode_id}/cancel", response_model=CancelResponse)
async def cancel_episode(episode_id: str) -> CancelResponse:
    """
    取消正在处理的任务

    取消下载、转录或分析任务。对于 pending 状态的任务，直接标记为取消；
    对于正在运行的任务，尝试取消并标记为取消。
    """
    import logging
    logger = logging.getLogger(__name__)

    # 检查节目是否存在
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 只能取消处理中的任务
    status = ep_data.get("status")
    if status not in ["pending", "downloading", "asr_running", "llm_running"]:
        raise HTTPException(status_code=400, detail="只能取消处理中的任务")

    # 对于 pending 状态，直接标记为取消（任务还没开始）
    if status == "pending":
        await EpisodeRepository.update_status(
            episode_id,
            EpisodeStatus.FAILED,
            error_msg="任务已取消",
        )
        logger.info(f"Episode {episode_id} (pending) marked as cancelled")
        return CancelResponse(
            success=True,
            episode_id=episode_id,
            status=EpisodeStatus.FAILED.value,
        )

    # 对于正在运行的任务，尝试取消
    cancelled = await pipeline.cancel(episode_id)

    if cancelled:
        # 更新状态为已取消
        await EpisodeRepository.update_status(
            episode_id,
            EpisodeStatus.FAILED,
            error_msg="任务已取消",
        )

        logger.info(f"Episode {episode_id} cancelled successfully")

        return CancelResponse(
            success=True,
            episode_id=episode_id,
            status=EpisodeStatus.FAILED.value,
        )
    else:
        # 任务可能已经完成或失败，刷新状态
        await EpisodeRepository.update_status(
            episode_id,
            EpisodeStatus.FAILED,
            error_msg="任务已取消",
        )
        return CancelResponse(
            success=True,
            episode_id=episode_id,
            status=EpisodeStatus.FAILED.value,
        )




@router.post("/api/episode/{episode_id}/resume", response_model=ResumeResponse)
async def resume_episode(episode_id: str, request: ResumeRequest) -> ResumeResponse:
    """
    恢复中断或失败的任务

    从上次完成的阶段继续处理，而非从头开始。
    会检查已存在的文件（transcript.json, outline.json 等），
    只执行未完成的阶段。
    """
    import logging
    logger = logging.getLogger(__name__)

    # 检查节目是否存在
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 只能恢复失败或就绪状态的节目
    status = ep_data.get("status")
    if status not in ["failed", "ready"]:
        raise HTTPException(
            status_code=400,
            detail=f"只能恢复失败或完成的任务，当前状态：{status}"
        )

    # 获取原始输入：请求体 > source 表 > usage_log（paste 一定写过）
    raw_input = request.raw_input
    if not raw_input:
        from ..database import SourceRepository
        source_data = await SourceRepository.get_by_episode(episode_id)
        if source_data:
            raw_input = source_data.get("raw_input")
            logger.info(f"从 source 表恢复原始URL: {raw_input}")
        else:
            # 早期失败的任务可能 pipeline 还没来得及写 source 表，
            # 回退到 usage_log（paste 一定写过 raw_input）
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT payload_json FROM usage_log "
                    "WHERE episode_id = ? AND event_type = 'paste' "
                    "ORDER BY ts DESC LIMIT 1",
                    (episode_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        raw_input = row[0]
                        logger.info(f"从 usage_log 恢复原始URL: {raw_input}")
            if not raw_input:
                raise HTTPException(
                    status_code=400,
                    detail="找不到原始URL，请提供raw_input参数"
                )

    # 标记状态为处理中
    await EpisodeRepository.update_status(episode_id, EpisodeStatus.PENDING)

    # 在后台启动恢复任务
    async def run_resume():
        from ..pipeline import pipeline as audio_pipeline
        try:
            await audio_pipeline.resume_episode(
                episode_id,
                raw_input,  # 使用从 source 表/usage_log 获取的 URL
                on_progress=lambda sid, prog, overall: None,
            )
        except Exception as e:
            logger.exception(f"Resume failed for {episode_id}: {e}")
            await EpisodeRepository.update_status(
                episode_id,
                EpisodeStatus.FAILED,
                error_msg=str(e)
            )

    import asyncio
    create_background_task(run_resume(), name=f"resume:{episode_id}")

    logger.info(f"Episode {episode_id} resume started")

    return ResumeResponse(
        success=True,
        episode_id=episode_id,
        status=EpisodeStatus.PENDING.value,
    )




@router.post(
    "/api/episode/{episode_id}/insights",
    response_model=GenerateInsightsResponse,
    dependencies=[Depends(rate_limit(10, 60))],
)
async def generate_insights(episode_id: str) -> GenerateInsightsResponse:
    """
    为现有节目生成产品和技术洞察

    使用已有数据生成 product_insights.json
    """
    import logging
    logger = logging.getLogger(__name__)

    # 检查节目是否存在
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 检查必需文件是否存在
    media_dir = deps.data_dir / "media" / episode_id
    required_files = {
        "transcript.json": "转录文本",
        "outline.json": "章节大纲",
        "summaries.json": "章节摘要",
        "highlight.json": "亮点摘要",
    }

    missing = []
    for file_name, desc in required_files.items():
        if not (media_dir / file_name).exists():
            missing.append(desc)

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"缺少必要文件: {', '.join(missing)}。请先完成节目的完整处理。"
        )

    # 检查是否已经存在
    if (media_dir / "product_insights.json").exists():
        return GenerateInsightsResponse(
            episode_id=episode_id,
            message="产品洞察已存在"
        )

    # 在后台生成洞察
    async def run_insights_generation():
        try:
            from ..llm_pipeline.llm_product_insights import run_product_insights_stage

            await run_product_insights_stage(
                episode_id=episode_id,
                data_dir=deps.data_dir,
                on_progress=lambda prog: None,
            )
            logger.info(f"Product insights generated for {episode_id}")
        except Exception as e:
            logger.error(f"Product insights generation failed for {episode_id}: {e}")

    import asyncio
    create_background_task(run_insights_generation(), name=f"insights:{episode_id}")

    logger.info(f"Product insights generation started for {episode_id}")

    return GenerateInsightsResponse(
        episode_id=episode_id,
        message="产品洞察正在后台生成中"
    )




