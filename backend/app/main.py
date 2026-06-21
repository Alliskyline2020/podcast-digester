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


@app.get("/api/episodes/{episode_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(episode_id: str) -> TranscriptResponse:
    """
    获取节目字幕数据

    返回所有字幕段落，供字幕编辑器使用
    """
    import re
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 加载完整数据
    bundle = await _load_episode_bundle(episode_id)

    # 提取字幕段落并清理HTML
    cleaned_segments = []
    if bundle.transcript and bundle.transcript.segments:
        for seg in bundle.transcript.segments:
            # 优先使用带标点的文本，否则使用原始文本
            text_to_use = seg.text_with_punct or seg.text_original or ""
            # 创建清理后的segment（使用集中的文本清洗工具）
            cleaned_text = clean_segment_text(text_to_use)
            # 清理后的文本存入 text_original（前端期望的字段名）
            seg.text_original = cleaned_text
            # 保留原始带标点的版本
            if seg.text_with_punct:
                seg.text_with_punct = cleaned_text
            cleaned_segments.append(seg)

    return TranscriptResponse(segments=cleaned_segments)


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


@app.post("/api/episodes/{episode_id}/sync-subtitles", response_model=SyncSubtitlesResponse)
async def sync_subtitle_segments(episode_id: str) -> SyncSubtitlesResponse:
    """
    同步字幕分段

    从原始字幕 segments 生成段落映射，并持久化到数据库。
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. 获取节目数据
    episode = await EpisodeRepository.get_by_id(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 2. 读取字幕文件
    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    if not transcript_file.exists():
        raise HTTPException(status_code=400, detail="字幕文件不存在")

    transcript_data = safe_read_json(transcript_file)
    if not transcript_data or not transcript_data.get("segments"):
        raise HTTPException(status_code=400, detail="字幕数据为空或格式错误")

    # 3. 为 segments 添加索引（用于映射）
    segments = transcript_data["segments"]
    for i, seg in enumerate(segments):
        if "id" not in seg:
            seg["id"] = f"seg_{episode_id}_{i}"
        seg["_index"] = i

    # 4. 使用LLM语义分段（按语义完整性划分，而非机械规则）
    logger.info(f"Using LLM semantic segmentation for {episode_id}")
    from .services.llm_semantic_segmenter import split_into_semantic_segments
    from .models import Episode

    episode = await EpisodeRepository.get_by_id(episode_id)
    title = episode.get("title") if episode and episode.get("title") else "Unknown"
    language = episode.get("language") if episode and episode.get("language") else "zh"

    paragraph_mappings = await split_into_semantic_segments(
        segments=segments,
        title=title,
        language=language,
        batch_size=800,
        progress_cb=None
    )

    # 5. 持久化到数据库
    await EpisodeRepository.update(episode_id, paragraph_mappings=paragraph_mappings)

    logger.info(f"Synced subtitles for {episode_id}: {len(paragraph_mappings)} paragraphs from {len(segments)} segments")

    # 6. 返回结果
    return SyncSubtitlesResponse(
        episode_id=episode_id,
        paragraph_count=len(paragraph_mappings),
        paragraph_mappings=paragraph_mappings,
        segment_count=len(segments)
    )


# /api/admin/batch-sync-subtitles 已迁移到 routers/admin.py
# （含 verify_admin 依赖通过 router 级别应用）


# ==================== LLM 智能字幕处理 ====================

@app.post(
    "/api/episodes/{episode_id}/sync-subtitles-llm",
    response_model=SyncSubtitlesResponse,
    dependencies=[Depends(rate_limit(10, 60))],
)
async def sync_subtitle_segments_llm(episode_id: str) -> SyncSubtitlesResponse:
    """
    使用 LLM 智能同步字幕分段（Full LLM 方案）

    使用 LLM 进行智能分段、清洗和金句提取，追求最佳质量。
    处理时间：1-2 分钟
    成本：~$0.5/小时节目
    """
    import logging
    import time
    import os
    logger = logging.getLogger(__name__)

    start_time = time.time()

    # 1. 获取节目数据
    episode = await EpisodeRepository.get_by_id(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 2. 读取字幕文件
    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    if not transcript_file.exists():
        raise HTTPException(status_code=400, detail="字幕文件不存在")

    transcript_data = safe_read_json(transcript_file)
    if not transcript_data or not transcript_data.get("segments"):
        raise HTTPException(status_code=400, detail="字幕数据为空或格式错误")

    # 3. 为 segments 添加索引
    segments = transcript_data["segments"]
    for i, seg in enumerate(segments):
        if "id" not in seg:
            seg["id"] = f"seg_{episode_id}_{i}"
        seg["_index"] = i

    logger.info(f"[LLM Sync] Starting LLM processing for {episode_id} with {len(segments)} segments")

    # 4. 使用 LLM 智能分段
    try:
        from .services.llm_subtitle_processor import LLMSubtitleProcessor

        # 获取 API key
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY 未配置")

        processor = LLMSubtitleProcessor(api_key=api_key)

        # LLM 智能分段
        logger.info(f"[LLM Sync] Calling LLM for segmentation...")
        paragraph_mappings = await processor.segment_transcript(segments, episode_id)

        logger.info(f"[LLM Sync] LLM returned {len(paragraph_mappings)} paragraphs")

    except Exception as e:
        logger.error(f"[LLM Sync] LLM segmentation failed: {e}")
        raise HTTPException(status_code=500, detail=f"LLM 分段失败: {str(e)}")

    # 5. 持久化到数据库
    try:
        await EpisodeRepository.update(episode_id, paragraph_mappings=paragraph_mappings)
        logger.info(f"[LLM Sync] Saved {len(paragraph_mappings)} paragraphs to database")
    except Exception as e:
        logger.error(f"[LLM Sync] Database update failed: {e}")
        raise HTTPException(status_code=500, detail=f"数据库更新失败: {str(e)}")

    duration = int((time.time() - start_time) * 1000)

    logger.info(f"[LLM Sync] Completed for {episode_id}: {len(paragraph_mappings)} paragraphs in {duration}ms")

    # 6. 返回结果
    return SyncSubtitlesResponse(
        episode_id=episode_id,
        paragraph_count=len(paragraph_mappings),
        paragraph_mappings=paragraph_mappings,
        segment_count=len(segments)
    )


@app.post(
    "/api/episodes/{episode_id}/extract-insights",
    response_model=InsightExtractionResponse,
    dependencies=[Depends(rate_limit(10, 60))],
)
async def extract_insights_llm(
    episode_id: str,
    max_insights: int = 5
) -> InsightExtractionResponse:
    """
    使用 LLM 提取金句和洞察

    基于语义理解提取最有价值的句子和观点。
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. 获取节目数据
    episode = await EpisodeRepository.get_by_id(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 2. 读取转录文件
    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    if not transcript_file.exists():
        raise HTTPException(status_code=400, detail="转录文件不存在")

    transcript_data = safe_read_json(transcript_file)
    if not transcript_data or not transcript_data.get("segments"):
        raise HTTPException(status_code=400, detail="转录数据为空")

    # 3. 准备完整转录文本
    segments = transcript_data["segments"]
    full_transcript = "\n".join([
        f"[{seg['start_ms']/1000:.2f}] {seg.get('speaker', '')}: {seg.get('text_original', '')}"
        for seg in segments
    ])

    # 4. 使用 LLM 提取金句
    try:
        from .services.llm_subtitle_processor import LLMSubtitleProcessor

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY 未配置")

        processor = LLMSubtitleProcessor(api_key=api_key)

        logger.info(f"[LLM Insights] Extracting insights for {episode_id}")
        result = await processor.extract_insights(full_transcript, episode_id, max_insights)

        logger.info(f"[LLM Insights] Extracted {len(result.get('insights', []))} insights")

        return result

    except Exception as e:
        logger.error(f"[LLM Insights] Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"金句提取失败: {str(e)}")


@app.post(
    "/api/episodes/{episode_id}/correct-transcript",
    response_model=CorrectTranscriptResponse,
    dependencies=[Depends(rate_limit(10, 60))],
)
async def correct_transcript_llm(episode_id: str) -> CorrectTranscriptResponse:
    """
    使用 LLM 纠正字幕中的 ASR 识别错误

    纠正常见的ASR错误，如人名错误、同音字错误等。
    """
    import logging
    logger = logging.getLogger(__name__)

    start_time = time.time()

    # 1. 获取节目数据
    episode = await EpisodeRepository.get_by_id(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 2. 读取转录文件
    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    if not transcript_file.exists():
        raise HTTPException(status_code=400, detail="转录文件不存在，请先完成转录")

    transcript_data = safe_read_json(transcript_file)
    if not transcript_data or not transcript_data.get("segments"):
        raise HTTPException(status_code=400, detail="转录数据为空")

    # 3. 准备segments
    segments = transcript_data["segments"]
    total_segments = len(segments)

    # 4. 使用 LLM 纠错
    try:
        from .services.llm_subtitle_processor import LLMSubtitleProcessor
        from .utils.io import atomic_write_json

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY 未配置")

        processor = LLMSubtitleProcessor(api_key=api_key)

        logger.info(f"[LLM Correction] Starting correction for {episode_id} ({total_segments} segments)")

        # 调用纠错
        corrected_segments = await processor.correct_transcription(
            segments=segments,
            episode_title=episode.get("title", ""),
            episode_description=episode.get("description", ""),
            batch_size=50
        )

        # 统计纠错数量
        corrected_count = sum(1 for seg in corrected_segments if seg.get("text_corrected", False))

        # 保存纠正后的transcript
        transcript_data["segments"] = corrected_segments
        atomic_write_json(transcript_file, transcript_data)

        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(f"[LLM Correction] Completed for {episode_id}: {corrected_count}/{total_segments} segments corrected in {duration_ms}ms")

        return CorrectTranscriptResponse(
            episode_id=episode_id,
            total_segments=total_segments,
            corrected_segments=corrected_count,
            duration_ms=duration_ms
        )

    except Exception as e:
        logger.error(f"[LLM Correction] Failed: {e}")
        raise HTTPException(status_code=500, detail=f"字幕纠错失败: {str(e)}")


@app.post("/api/episodes/{episode_id}/segments/update", response_model=UpdateSegmentResponse)
async def update_transcript_segment(
    episode_id: str,
    request: UpdateSegmentRequest
) -> UpdateSegmentResponse:
    """
    手动编辑字幕segment并同步到所有模块

    Args:
        episode_id: 节目ID
        request: 更新请求

    Returns:
        更新结果
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. 验证输入
    if not episode_id or not isinstance(episode_id, str):
        raise HTTPException(status_code=400, detail="无效的episode_id")

    if episode_id.startswith("ep_") is False:
        raise HTTPException(status_code=400, detail="episode_id格式错误")

    if request.segment_index < 0:
        raise HTTPException(status_code=400, detail="segment_index不能为负数")

    # 验证文本长度
    if not request.text_original:
        raise HTTPException(status_code=400, detail="text_original不能为空")

    if len(request.text_original) > 10000:  # 10KB限制
        raise HTTPException(status_code=400, detail="text_original过长")

    # 2. 获取节目数据
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 3. 加载完整数据
    bundle = await _load_episode_bundle(episode_id)
    if not bundle.transcript:
        raise HTTPException(status_code=404, detail="字幕数据不存在")

    segments = bundle.transcript.segments

    if request.segment_index >= len(segments):
        raise HTTPException(
            status_code=400,
            detail=f"segment_index超出范围: {request.segment_index} >= {len(segments)}"
        )

    # 4. 更新segment
    segment = segments[request.segment_index]
    old_text = segment.text_original
    new_text = request.text_original

    segment.text_original = new_text

    # 5. 如果需要，添加到词库
    added_to_glossary = False
    if request.note_to_glossary:
        from .services.glossary import get_glossary

        # 简单的启发式：提取差异
        if old_text and new_text and old_text != new_text:
            # 假设较短的词是错误词（简化逻辑）
            glossary = get_glossary(data_dir)
            if len(old_text) < len(new_text):
                # old是错误词，new是正确词
                glossary.add_entry(new_text, [old_text])
                added_to_glossary = True
                logger.info(f"[Glossary] Added entry: {new_text} <- {old_text}")

    # 6. 保存transcript到数据库
    transcript_dict = bundle.transcript.model_dump()
    await EpisodeRepository.update_transcript(episode_id, transcript_dict)

    # 7. 同步到其他模块（后台任务）
    segments_dict = [seg.model_dump() for seg in segments]
    _create_background_task(
        _sync_episode_modules(episode_id, segments_dict),
        name=f"sync_modules:{episode_id}",
    )

    logger.info(f"[Segment Update] Episode {episode_id}, segment {request.segment_index}: {old_text} -> {new_text}")

    return UpdateSegmentResponse(
        success=True,
        segment_index=request.segment_index,
        old_text=old_text,
        new_text=new_text,
        added_to_glossary=added_to_glossary
    )


# 3 个纯词库 CRUD 端点已迁移到 routers/glossary.py


@app.post("/api/episodes/{episode_id}/apply-glossary", response_model=CorrectTranscriptResponse)
async def apply_glossary_to_episode(episode_id: str) -> CorrectTranscriptResponse:
    """
    使用词库纠正整个节目的字幕

    Args:
        episode_id: 节目ID

    Returns:
        纠正结果
    """
    import logging
    logger = logging.getLogger(__name__)

    start_time = time.time()

    # 1. 获取节目数据
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 2. 加载完整数据
    bundle = await _load_episode_bundle(episode_id)

    # 3. 提取transcript数据
    transcript_dict = bundle.transcript.model_dump() if bundle.transcript else {"segments": []}
    total_segments = len(transcript_dict.get("segments", []))

    if total_segments == 0:
        raise HTTPException(status_code=400, detail="字幕数据为空，无法应用词库纠错")

    # 4. 使用词库纠正
    from .services.glossary import get_glossary
    glossary = get_glossary(data_dir)

    corrected_data, corrected_count = glossary.correct_transcript(transcript_dict)

    # 5. 更新数据库中的transcript
    await EpisodeRepository.update_transcript(episode_id, corrected_data)

    duration_ms = int((time.time() - start_time) * 1000)

    logger.info(f"[Glossary Apply] Episode {episode_id}: {corrected_count}/{total_segments} segments corrected")

    # 6. 如果有纠正，同步到其他模块（不包括paragraph_mappings，因为词库纠错不改段落结构）
    if corrected_count > 0:
        _create_background_task(
            _sync_episode_modules(episode_id, corrected_data["segments"], regenerate_paragraphs=False),
            name=f"sync_modules:{episode_id}",
        )

    return CorrectTranscriptResponse(
        episode_id=episode_id,
        total_segments=total_segments,
        corrected_segments=corrected_count,
        duration_ms=duration_ms
    )


# _sync_episode_modules / _create_background_task / _log_task_exception
# 已迁移到 .services.background_tasks，通过顶部 import 引入到本模块命名空间。
# _load_highlight_fast / _load_episode_bundle 等 loader 助手也已迁移到
# .services.episode_loader。所有这些通过顶部 import 的别名引用，调用方无需改动。


# Export API（POST /api/episodes/{id}/export + GET /api/exports/{filename}）
# 已迁移到 routers/export.py。
