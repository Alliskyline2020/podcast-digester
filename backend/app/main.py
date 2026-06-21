"""
FastAPI 主应用
REST API 入口
"""
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Response, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.responses import FileResponse as StarletteFileResponse
from starlette.datastructures import Headers
import asyncio
from functools import lru_cache
from typing import Optional, List, Dict, Any, Tuple
import os

from .models import (
    Episode, EpisodeBundle, EpisodeCard, EpisodeStatus,
    PasteRequest, PasteResponse, PlayRequest, PlayResponse,
    VerdictType, ConfidenceType, ProductInsights,
    ExportRequest, ExportResponse,
    HighlightCard, Outline, TranscriptResponse, Segment,
)
from .utils import clean_segment_text
from .database import init_db, EpisodeRepository, UsageLogRepository
from .config import DB_PATH, settings
import aiosqlite
from .ingest import run_ingest, pipeline
from .utils.validation import validate_raw_input
from .utils.io import safe_read_json
from .errors import PodcastError
from .rate_limit import rate_limit, limiter as _global_limiter
from .deps import data_dir, verify_admin, is_loopback as _is_loopback
from .services.background_tasks import (
    log_task_exception as _log_task_exception,
    create_background_task as _create_background_task,
    sync_episode_modules as _sync_episode_modules,
)
from .services.episode_loader import (
    load_highlight_fast as _load_highlight_fast,
    load_highlight_fast_async as _load_highlight_fast_async,
    get_duration_fast as _get_duration_fast,
    get_duration_fast_async as _get_duration_fast_async,
    prefetch_card_meta as _prefetch_card_meta,
    load_progress_fast as _load_progress_fast,
    load_episode_bundle as _load_episode_bundle,
)
from .routers import glossary as glossary_router
from .routers import media as media_router
from .routers import admin as admin_router
from .routers import export as export_router
from .routers import subtitles as subtitles_router

# 初始化logger
logger = logging.getLogger(__name__)

# 注：verify_admin / _is_loopback / data_dir 来自 .deps，
# _log_task_exception / _create_background_task / _sync_episode_modules 来自
# .services.background_tasks，均已通过顶部 import 引入。

# ==================== 数据传输对象 ====================

class ListEpisodesResponse(BaseModel):
    """节目列表响应"""
    episodes: list[EpisodeCard]


class EpisodeResponse(BaseModel):
    """节目详情响应"""
    episode: EpisodeBundle


class DeleteResponse(BaseModel):
    """删除响应"""
    ok: bool = True
    deleted: str


class HealthResponse(BaseModel):
    """健康检查响应"""
    name: str
    version: str
    status: str


class SyncSubtitlesResponse(BaseModel):
    """字幕同步响应"""
    episode_id: str
    paragraph_count: int
    paragraph_mappings: list
    segment_count: int


# BatchSyncRequest / BatchSyncResponse 已迁移到 routers/admin.py


class CorrectTranscriptResponse(BaseModel):
    """字幕纠错响应"""
    episode_id: str
    total_segments: int
    corrected_segments: int
    duration_ms: int


class UpdateSegmentRequest(BaseModel):
    """更新字幕segment请求"""
    segment_index: int
    text_original: str
    note_to_glossary: bool = False


class UpdateSegmentResponse(BaseModel):
    """更新字幕segment响应"""
    success: bool
    segment_index: int
    old_text: str
    new_text: str
    added_to_glossary: bool


# GlossaryEntry / GlossaryResponse 已迁移到 routers/glossary.py


# ==================== 应用初始化 ====================

app = FastAPI(
    title="Podcast Digester",
    description="播客/发布会内容摘要引擎",
    version="0.2.1-m2p",
)

# CORS 配置
# 注意：allow_origins=["*"] + allow_credentials=True 是 CORS 规范禁止的组合，
# 浏览器会拒发 credentialed 请求。这里改为读 settings.cors_origins（默认 loopback），
# 并关闭 allow_credentials，匹配无 cookie/session 的纯 token 认证模型。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务
# data_dir 需要指向项目根目录的 data 文件夹
# data_dir 来自 .deps（顶部 import），历史上这里也有同名赋值，
# 路径相同但重复；这里改用注释提示来源，避免本地变量遮蔽 import。
# data_dir = Path(__file__).parent.parent.parent / "data"  # 来自 .deps


# ==================== 支持 Range 请求的音频服务 ====================
# 已迁移到 routers/media.py


# 其他静态文件仍然使用 StaticFiles
app.mount("/media", StaticFiles(directory=str(data_dir / "media")), name="media")
# fixtures 目录可能不存在，仅在存在时挂载
fixtures_dir = data_dir / "fixtures"
if fixtures_dir.exists():
    app.mount("/fixtures", StaticFiles(directory=str(fixtures_dir)), name="fixtures")


# ==================== Routers ====================
# 各业务 router 在 routers/<name>.py 中定义，main.py 仅负责装载。
app.include_router(glossary_router.router)
app.include_router(media_router.router)
app.include_router(admin_router.router)
app.include_router(export_router.router)
app.include_router(subtitles_router.router)


# ==================== 全局异常处理器 ====================

from fastapi.responses import JSONResponse


@app.exception_handler(PodcastError)
def podcast_error_handler(request, exc: PodcastError) -> JSONResponse:
    """统一处理所有PodcastError"""
    status_code = getattr(exc, "http_status", 500)
    return JSONResponse(
        status_code=status_code,
        content=exc.to_dict()
    )


@app.exception_handler(HTTPException)
def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    """FastAPI HTTPException处理"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error_type": "HTTPException",
            "message": exc.detail,
            "retryable": False
        }
    )


@app.exception_handler(Exception)
def general_exception_handler(request, exc: Exception) -> JSONResponse:
    """未预期的异常处理"""
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)

    return JSONResponse(
        status_code=500,
        content={
            "error_type": "InternalServerError",
            "message": "Internal server error",
            "retryable": True
        }
    )


# ==================== 启动事件 ====================

@app.on_event("startup")
async def startup():
    """应用启动时初始化"""
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Starting Podcast Digester backend")

    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    # 恢复未完成的任务
    from .task_recovery import recover_pending_tasks
    _create_background_task(recover_pending_tasks(), name="recover_pending_tasks")
    logger.info("Task recovery started")


# ==================== 健康检查 ====================

@app.get("/", response_model=HealthResponse)
async def health():
    """健康检查"""
    return {
        "name": "podcast-digester",
        "version": "0.2.1-m2p",
        "status": "healthy",
    }


# ==================== 核心 API ====================

@app.post("/api/paste", response_model=PasteResponse, dependencies=[Depends(rate_limit(5, 60))])
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


@app.get("/api/episodes", response_model=ListEpisodesResponse)
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
        from .database import IngestJobRepository
        for ep_id in progress_episode_ids:
            progress_info = await _load_progress_fast(ep_id)
            if progress_info:
                progress_cache[ep_id] = progress_info

    # 预构造 card 列表，确定每条是否需要 duration（避免在循环里判断时卡事件循环）
    cards = [EpisodeCard(**ep_data) for ep_data in episodes_data]

    # 并发预取所有 highlight/duration（FS 读推到线程池，不阻塞事件循环）
    meta_results = await asyncio.gather(
        *[_prefetch_card_meta(c.id, need_duration=not c.duration_min) for c in cards]
    )
    meta_cache = {c.id: meta_results[i] for i, c in enumerate(cards)}

    # 用预取结果填充 card
    episodes = []
    for card in cards:
        highlight, duration = meta_cache.get(card.id, (None, None))

        if highlight:
            card.tldr_zh = highlight.get("tldr_zh")
            card.worth_listening_verdict = highlight.get("worth_listening_verdict")
            card.verdict_confidence = highlight.get("verdict_confidence")
            card.target_audience_zh = highlight.get("target_audience_zh")
            card.highlights_count = len(highlight.get("highlights", []))

        if not card.duration_min and duration is not None:
            card.duration_min = duration

        # 从缓存加载处理进度（进行中时）
        if card.id in progress_cache:
            progress_info = progress_cache[card.id]
            card.current_stage = progress_info.get("current_stage")
            card.stages = progress_info.get("stages", [])
            card.overall_progress = progress_info.get("overall_progress", 0.0)

        episodes.append(card)

    return ListEpisodesResponse(episodes=episodes)


@app.get("/api/episode/{episode_id}", response_model=EpisodeResponse)
async def get_episode(episode_id: str) -> EpisodeResponse:
    """
    获取节目完整数据

    返回 EpisodeBundle 包含所有关联数据
    """
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 加载完整数据
    bundle = await _load_episode_bundle(episode_id)

    return EpisodeResponse(episode=bundle)


@app.delete("/api/episode/{episode_id}", response_model=DeleteResponse)
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
    media_dir = data_dir / "media" / episode_id
    if media_dir.exists():
        import shutil
        try:
            shutil.rmtree(media_dir, ignore_errors=True)
            logger.info(f"Media files deleted for {episode_id}")
        except Exception as e:
            logger.warning(f"Failed to delete media files for {episode_id}: {e}")

    return DeleteResponse(deleted=episode_id)


@app.post("/api/episode/{episode_id}/play", response_model=PlayResponse)
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


class CancelResponse(BaseModel):
    """取消响应"""
    ok: bool = True
    cancelled: str
    message: str = ""


@app.post("/api/episode/{episode_id}/cancel", response_model=CancelResponse)
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
            cancelled=episode_id,
            message="任务已取消"
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
            cancelled=episode_id,
            message="任务已取消"
        )
    else:
        # 任务可能已经完成或失败，刷新状态
        await EpisodeRepository.update_status(
            episode_id,
            EpisodeStatus.FAILED,
            error_msg="任务已取消",
        )
        return CancelResponse(
            cancelled=episode_id,
            message="任务已取消"
        )


class ResumeRequest(BaseModel):
    """恢复请求"""
    raw_input: Optional[str] = Field(None, description="原始 URL 或文件路径（可选，不提供则从数据库读取）")


class ResumeResponse(BaseModel):
    """恢复响应"""
    ok: bool = True
    episode_id: str
    message: str = "任务已恢复"


@app.post("/api/episode/{episode_id}/resume", response_model=ResumeResponse)
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

    # 获取原始输入（从请求或数据库）
    raw_input = request.raw_input
    if not raw_input:
        # 从source表读取原始URL
        from .database import SourceRepository
        source_data = await SourceRepository.get_by_episode(episode_id)
        if not source_data:
            raise HTTPException(
                status_code=400,
                detail="找不到原始URL，请提供raw_input参数"
            )
        raw_input = source_data.get("raw_input")
        logger.info(f"从数据库恢复原始URL: {raw_input}")

    # 检查是否有任何已完成的文件
    media_dir = data_dir / "media" / episode_id
    has_any_file = any([
        (media_dir / "transcript.json").exists(),
        (media_dir / "outline.json").exists(),
        (media_dir / "summaries.json").exists(),
        (media_dir / "highlight.json").exists(),
    ])

    if not has_any_file and status != "ready":
        raise HTTPException(
            status_code=400,
            detail="没有可恢复的中间文件，请重新提交"
        )

    # 标记状态为处理中
    await EpisodeRepository.update_status(episode_id, EpisodeStatus.PENDING)

    # 在后台启动恢复任务
    async def run_resume():
        try:
            await pipeline.resume_episode(
                episode_id,
                raw_input,  # 使用从数据库获取的URL
                on_progress=lambda sid, prog, overall: None,
            )
        except Exception as e:
            logger.error(f"Resume failed for {episode_id}: {e}")
            await EpisodeRepository.update_status(
                episode_id,
                EpisodeStatus.FAILED,
                error_msg=str(e)
            )

    import asyncio
    _create_background_task(run_resume(), name=f"resume:{episode_id}")

    logger.info(f"Episode {episode_id} resume started")

    return ResumeResponse(
        episode_id=episode_id,
        message="任务已恢复，正在后台处理"
    )


class GenerateInsightsResponse(BaseModel):
    """生成洞察响应"""
    ok: bool = True
    episode_id: str
    message: str = "产品洞察生成完成"


class InsightExtractionResponse(BaseModel):
    """金句提取响应"""
    episode_id: str
    insights: List[Dict[str, Any]] = Field(default_factory=list, description="提取的金句列表")
    llm_processed: bool = True
    error: Optional[str] = None


@app.post(
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
    media_dir = data_dir / "media" / episode_id
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
            from .llm_pipeline.llm_product_insights import run_product_insights_stage

            await run_product_insights_stage(
                episode_id=episode_id,
                data_dir=data_dir,
                on_progress=lambda prog: None,
            )
            logger.info(f"Product insights generated for {episode_id}")
        except Exception as e:
            logger.error(f"Product insights generation failed for {episode_id}: {e}")

    import asyncio
    _create_background_task(run_insights_generation(), name=f"insights:{episode_id}")

    logger.info(f"Product insights generation started for {episode_id}")

    return GenerateInsightsResponse(
        episode_id=episode_id,
        message="产品洞察正在后台生成中"
    )


# ==================== LLM 智能字幕处理 ====================

