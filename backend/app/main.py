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
from .routers import glossary as glossary_router
from .routers import media as media_router

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


class BatchSyncRequest(BaseModel):
    """批量字幕同步请求"""
    episode_ids: list[str] = Field(..., description="要同步的节目ID列表")


class BatchSyncResponse(BaseModel):
    """批量字幕同步响应"""
    total: int = Field(..., description="总数")
    successful: list[str] = Field(..., description="成功的节目ID列表")
    failed: list[dict[str, str]] = Field(..., description="失败的节目ID和错误信息")
    duration_ms: int = Field(..., description="处理耗时（毫秒）")


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


@app.post(
    "/api/admin/batch-sync-subtitles",
    response_model=BatchSyncResponse,
    dependencies=[Depends(verify_admin)],
)
async def batch_sync_subtitle_segments(request: BatchSyncRequest) -> BatchSyncResponse:
    """
    批量同步字幕分段

    对多个已有节目进行字幕段落合并处理，无需重新下载音频或重新转录。
    """
    import logging
    logger = logging.getLogger(__name__)

    start_time = time.time()
    successful = []
    failed = []

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
    import os
    api_key = os.getenv("DEEPSEEK_API_KEY")
    use_llm = api_key is not None

    if use_llm:
        try:
            from .services.llm_subtitle_processor import LLMSubtitleProcessor
            llm_processor = LLMSubtitleProcessor(api_key=api_key)
            logger.info(f"Batch sync: using LLM segmentation")
        except Exception as e:
            logger.warning(f"Batch sync: LLM initialization failed, using rule-based: {e}")
            use_llm = False

    if not use_llm:
        from .services.subtitle_segmenter import SubtitleSegmenter
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
            transcript_file = data_dir / "media" / episode_id / "transcript.json"
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
                    from .services.subtitle_segmenter import SubtitleSegmenter
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


# ==================== 辅助函数 ====================

def _load_highlight_fast(episode_id: str) -> Optional[dict]:
    """快速加载 highlight（仅基础字段）"""
    from .utils.io import safe_read_json

    highlight_file = data_dir / "media" / episode_id / "highlight.json"
    return safe_read_json(highlight_file)


async def _load_highlight_fast_async(episode_id: str) -> Optional[dict]:
    """异步包装：避免在 async 处理器里直接做阻塞 FS 读"""
    return await asyncio.to_thread(_load_highlight_fast, episode_id)


def _get_duration_fast(episode_id: str) -> Optional[int]:
    """快速获取节目时长（分钟）"""
    from .utils.io import safe_read_json

    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    data = safe_read_json(transcript_file)
    if data:
        segments = data.get("segments", [])
        if segments:
            total_ms = segments[-1].get("end_ms", 0)
            return int(total_ms / 1000 / 60)
    return None


async def _get_duration_fast_async(episode_id: str) -> Optional[int]:
    """异步包装：避免在 async 处理器里直接做阻塞 FS 读"""
    return await asyncio.to_thread(_get_duration_fast, episode_id)


async def _prefetch_card_meta(episode_id: str, need_duration: bool) -> tuple[Optional[dict], Optional[int]]:
    """并发预取单个 episode 的 highlight 与 duration，把阻塞 FS 读推到线程池"""
    tasks = [_load_highlight_fast_async(episode_id)]
    if need_duration:
        tasks.append(_get_duration_fast_async(episode_id))
    results = await asyncio.gather(*tasks)
    highlight = results[0]
    duration = results[1] if need_duration else None
    return highlight, duration


async def _load_progress_fast(episode_id: str) -> Optional[dict]:
    """快速加载处理进度

    返回格式：
    {
        "current_stage": "download",  # 当前阶段ID（英文）
        "stages": [
            {"id": "download", "name": "下载", "status": "downloading", "progress": 0.5},
            {"id": "transcribe", "name": "转录", "status": "pending", "progress": 0.0},
            ...
        ],
        "overall_progress": 0.125,
    }
    """
    from .database import IngestJobRepository

    job_data = await IngestJobRepository.get_by_id(episode_id)
    if not job_data:
        return None

    # 阶段权重配置（与 pipeline.py 保持一致）
    STAGE_WEIGHTS = {
        "download": 25,
        "transcribe": 25,
        "chapterize": 12,
        "summarize": 20,
        "highlight": 18,
        "translate": 0,  # 可选阶段，不计入总进度
    }
    TOTAL_WEIGHT = 100

    # 阶段ID到中文名称的映射
    STAGE_NAMES = {
        "download": "下载",
        "transcribe": "转录",
        "chapterize": "分章",
        "summarize": "摘要",
        "highlight": "亮点",
        "translate": "翻译",
        "done": "完成",
    }

    # 转换 stages 为前端需要的格式
    stages_data = []
    total_progress = 0.0
    current_stage_id = job_data.get("current_stage", "")

    for stage in job_data.get("stages", []):
        stage_id = stage.get("name", stage.get("id", ""))
        progress = stage.get("progress", 0.0)
        stage_status = stage.get("status", "")

        # 跳过没有ID的无效阶段
        if not stage_id:
            continue

        # 计算总体进度
        if stage_id in STAGE_WEIGHTS:
            weight = STAGE_WEIGHTS[stage_id]
            if progress >= 1.0:
                total_progress += weight
            elif stage_id == current_stage_id:
                total_progress += weight * progress

        stages_data.append({
            "id": stage_id,  # 保留原始ID用于比较
            "name": STAGE_NAMES.get(stage_id, stage_id),  # 中文名称用于显示
            "status": stage_status,
            "progress": progress,
        })

    return {
        "current_stage": current_stage_id,
        "stages": stages_data,
        "overall_progress": min(total_progress / TOTAL_WEIGHT, 1.0),
    }


async def _load_episode_bundle(episode_id: str) -> EpisodeBundle:
    """加载完整节目数据包"""
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 从source表读取原始URL
    from .database import SourceRepository
    source_data = await SourceRepository.get_by_episode(episode_id)
    if source_data:
        ep_data["source_url"] = source_data.get("raw_input")

    # 解析paragraph_mappings JSON字符串
    pm_value = ep_data.get("paragraph_mappings")
    logger.debug(f"Original paragraph_mappings type: {type(pm_value)}, value: {bool(pm_value)}")

    if pm_value:
        import json
        # 检查是否已经解析过（是list）还是需要解析（是str）
        if isinstance(pm_value, str):
            try:
                parsed = json.loads(pm_value)
                ep_data["paragraph_mappings"] = parsed
                logger.debug(f"Parsed {len(parsed)} paragraph_mappings from JSON string")
            except Exception as e:
                logger.error(f"[Load Bundle] Failed to parse paragraph_mappings JSON: {e}")
                ep_data["paragraph_mappings"] = None
        elif isinstance(pm_value, list):
            logger.debug(f"paragraph_mappings is already a list with {len(pm_value)} items")
        else:
            logger.debug(f"Unexpected paragraph_mappings type: {type(pm_value)}")

    pm_type_before = type(ep_data.get("paragraph_mappings"))
    logger.debug(f"Before Episode(), ep_data['paragraph_mappings'] type = {pm_type_before}")
    episode = Episode(**ep_data)
    pm_type_after = type(episode.paragraph_mappings)
    logger.debug(f"After Episode(), episode.paragraph_mappings type = {pm_type_after}")
    if episode.paragraph_mappings:
        logger.debug(f"episode.paragraph_mappings length = {len(episode.paragraph_mappings)}")

    # 加载 transcript - 从数据库读取
    transcript = None
    transcript_json = ep_data.get("transcript")
    if transcript_json:
        import json
        import re
        try:
            transcript_data = json.loads(transcript_json)
            # 清理HTML标签和实体
            cleaned_segments = []
            for seg_dict in transcript_data.get("segments", []):
                # 优先处理带标点的文本
                text_with_punct = seg_dict.get("text_with_punct")
                if text_with_punct:
                    # 清理带标点的文本
                    cleaned_punct = text_with_punct
                    # 解码HTML实体
                    cleaned_punct = cleaned_punct.replace("&lt;", "<").replace("&gt;", ">")
                    cleaned_punct = cleaned_punct.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                    cleaned_punct = cleaned_punct.replace("&nbsp;", " ")
                    # 移除HTML标签
                    cleaned_punct = re.sub(r'<[^>]*>', '', cleaned_punct)
                    # 清理多余空格
                    cleaned_punct = re.sub(r'\s+', ' ', cleaned_punct).strip()
                    seg_dict["text_with_punct"] = cleaned_punct

                # 清理原始文本
                cleaned_text = seg_dict.get("text_original", "")
                # 解码HTML实体
                cleaned_text = cleaned_text.replace("&lt;", "<").replace("&gt;", ">")
                cleaned_text = cleaned_text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                cleaned_text = cleaned_text.replace("&nbsp;", " ")
                # 移除HTML标签
                cleaned_text = re.sub(r'<[^>]*>', '', cleaned_text)
                # 清理多余空格
                cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
                seg_dict["text_original"] = cleaned_text

                cleaned_segments.append(Segment(**seg_dict))

            from .models import Transcript
            transcript = Transcript(
                episode_id=episode_id,
                language=transcript_data.get("language", "unknown"),
                segments=cleaned_segments
            )
        except Exception as e:
            # import logging
            # logger = logging.getLogger(__name__)
            # logger.error(f"[Load Bundle] Failed to load transcript from database: {e}")
            pass

    # 加载 outline - 从数据库读取
    outline = None
    try:
        from .repositories import OutlineRepository
        from .models import OutlineEntry, Outline

        outline_data = await OutlineRepository.get(episode_id)
        if outline_data and outline_data.get("entries"):
            outline_data["episode_id"] = episode_id
            # 处理entries可能是字典（包含"entries"键）或列表的情况
            entries_data = outline_data.get("entries")
            if isinstance(entries_data, dict) and "entries" in entries_data:
                entries_list = entries_data["entries"]
            else:
                entries_list = entries_data if isinstance(entries_data, list) else []
            outline_data["entries"] = [OutlineEntry(**e) for e in entries_list]
            outline = Outline(**outline_data)
            # logger.info(f"[Load Bundle] Loaded outline from database for {episode_id}")
    except Exception as e:
        # logger.error(f"[Load Bundle] Failed to load outline from database: {e}")
        # Fallback: 尝试从文件系统读取
        outline_file = data_dir / "media" / episode_id / "outline.json"
        if outline_file.exists():
            from .utils.io import load_json_with_callback
            def prepare_outline(data):
                data["episode_id"] = episode_id
                data["entries"] = [OutlineEntry(**e) for e in data.get("entries", [])]
                return Outline(**data)
            outline = load_json_with_callback(outline_file, prepare_outline)
            # logger.info(f"[Load Bundle] Fallback to file system for outline")

    # 加载章节摘要 - 从数据库读取
    summaries = []
    try:
        from .repositories import SummariesRepository
        from .models import ChapterSummary

        summaries_data = await SummariesRepository.get(episode_id)
        if summaries_data and summaries_data.get("summaries_json"):
            # 解析JSON字符串
            import json
            summaries_list = json.loads(summaries_data["summaries_json"])
            summaries = [ChapterSummary(**s) for s in summaries_list]
            # logger.info(f"[Load Bundle] Loaded summaries from database for {episode_id}")
    except Exception as e:
        # logger.error(f"[Load Bundle] Failed to load summaries from database: {e}")
        # Fallback: 尝试从文件系统读取
        summaries_file = data_dir / "media" / episode_id / "summaries.json"
        if summaries_file.exists():
            from .utils.io import load_json_with_callback
            def prepare_summaries(data):
                return [ChapterSummary(**s) for s in data]
            summaries = load_json_with_callback(summaries_file, prepare_summaries) or []
            # logger.info(f"[Load Bundle] Fallback to file system for summaries")

    # 加载 highlight - 从数据库读取
    highlight = None
    try:
        from .repositories import HighlightRepository
        from .models import HighlightItem, HighlightKind, HighlightCard
        from pydantic import ValidationError as PydanticValidationError

        highlight_data = await HighlightRepository.get(episode_id)
        if highlight_data and "highlights" in highlight_data:
            # highlight_data["highlights"] 包含完整的 HighlightCard 数据
            card_data = highlight_data["highlights"]

            # 转换 highlights 列表
            if "highlights" in card_data and isinstance(card_data["highlights"], list):
                try:
                    card_data["highlights"] = [
                        HighlightItem(
                            kind=HighlightKind(h["kind"]),
                            text_zh=h["text_zh"],
                            why_zh=h["why_zh"],
                            cited_segment_ids=h["cited_segment_ids"],
                            start_ms=h.get("start_ms"),
                        )
                        for h in card_data["highlights"]
                    ]
                except Exception as e:
                    # logger.warning(f"[Load Bundle] Failed to parse highlights: {e}")
                    pass

            # 转换枚举
            try:
                if "worth_listening_verdict" in card_data:
                    card_data["worth_listening_verdict"] = VerdictType(card_data["worth_listening_verdict"])
                if "verdict_confidence" in card_data:
                    card_data["verdict_confidence"] = ConfidenceType(card_data["verdict_confidence"])
            except Exception as e:
                # logger.warning(f"[Load Bundle] Failed to convert enums: {e}")
                pass

            # logger.info(f"[Load Bundle] Attempting to create HighlightCard with keys: {list(card_data.keys())}")

            try:
                highlight = HighlightCard(**card_data)
                # logger.info(f"[Load Bundle] Loaded highlight from database for {episode_id}")
            except PydanticValidationError as ve:
                # logger.error(f"[Load Bundle] HighlightCard validation error: {ve}")
                # logger.error(f"[Load Bundle] card_data: {card_data}")
                raise
        else:
            # logger.info(f"[Load Bundle] No highlight data found in database for {episode_id}")
            pass
    except Exception as e:
        # logger.error(f"[Load Bundle] Failed to load highlight from database: {e}")
        # Fallback: 尝试从文件系统读取
        highlight_file = data_dir / "media" / episode_id / "highlight.json"
        if highlight_file.exists():
            from .utils.io import load_json_with_callback
            def prepare_highlight(data):
                # 转换 highlights
                if "highlights" in data:
                    data["highlights"] = [
                        HighlightItem(
                            kind=HighlightKind(h["kind"]),
                            text_zh=h["text_zh"],
                            why_zh=h["why_zh"],
                            cited_segment_ids=h["cited_segment_ids"],
                            start_ms=h.get("start_ms"),
                        )
                        for h in data["highlights"]
                    ]
                # 转换枚举
                if "worth_listening_verdict" in data:
                    data["worth_listening_verdict"] = VerdictType(data["worth_listening_verdict"])
                if "verdict_confidence" in data:
                    data["verdict_confidence"] = ConfidenceType(data["verdict_confidence"])
                return data
            highlight = load_json_with_callback(highlight_file, prepare_highlight)
            if highlight:
                from .models import HighlightCard
                highlight = HighlightCard(**highlight)
            # logger.info(f"[Load Bundle] Fallback to file system for highlight")

    # 加载 product_insights - 从数据库读取
    product_insights = None
    try:
        from .repositories import ProductInsightsRepository

        insights_data = await ProductInsightsRepository.get(episode_id)
        if insights_data and insights_data.get("insights_json"):
            import json
            # 解析JSON字符串
            insights_dict = json.loads(insights_data["insights_json"])
            product_insights = ProductInsights(**insights_dict)
            # logger.info(f"[Load Bundle] Loaded product_insights from database for {episode_id}")
    except Exception as e:
        # logger.error(f"[Load Bundle] Failed to load product_insights from database: {e}")
        # Fallback: 尝试从文件系统读取
        insights_file = data_dir / "media" / episode_id / "product_insights.json"
        if insights_file.exists():
            from .utils.io import load_json_with_callback
            product_insights = load_json_with_callback(insights_file, lambda d: ProductInsights(**d))
            # logger.info(f"[Load Bundle] Fallback to file system for product_insights")

    # 加载 ingest_job（如果还在处理中）
    ingest_job = None
    if episode.status in [EpisodeStatus.PENDING, EpisodeStatus.DOWNLOADING, EpisodeStatus.ASR_RUNNING, EpisodeStatus.LLM_RUNNING]:
        from .database import IngestJobRepository
        job_data = await IngestJobRepository.get_by_id(episode_id)
        if job_data:
            from .models import IngestJob, IngestStage
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
        chapter_summaries=summaries,
        highlight=highlight,
        ingest_job=ingest_job,
        product_insights=product_insights,
    )


# ==================== Export API ====================

@app.post(
    "/api/episodes/{episode_id}/export",
    response_model=ExportResponse,
    dependencies=[Depends(rate_limit(3, 60))],
)
async def export_episode_summary(
    episode_id: str,
    request: ExportRequest
) -> ExportResponse:
    """
    导出节目摘要

    生成精美的HTML或PNG格式的摘要卡片，包含：
    - 中英文标题
    - 节目摘要（TL;DR）
    - 章节目录
    - 章节摘要
    - 趋势洞察

    支持两种格式：
    - HTML: 可分享的网页链接
    - PNG: 适合社交媒体分享的长图
    """
    # 速率限制由路由依赖 rate_limit(3, 60) 强制执行
    from .export import render_html_template, render_png_from_html
    from .utils.io import load_json_with_callback
    from datetime import datetime, timedelta
    from pathlib import Path
    from .config import DATA_DIR

    # 1. 加载节目数据（从文件系统）
    data_dir = DATA_DIR
    media_dir = data_dir / "media" / episode_id

    if not media_dir.exists():
        raise HTTPException(status_code=404, detail="Episode media directory not found")

    # 尝试从transcript.json获取metadata
    transcript_file = media_dir / "transcript.json"
    episode_meta = {}

    if transcript_file.exists():
        from .utils.io import safe_read_json
        transcript_data = safe_read_json(transcript_file)
        if transcript_data:
            episode_meta = transcript_data.get('meta', {})

    # 构造episode对象（至少要有id）
    episode = {
        'id': episode_id,
        'title': episode_meta.get('title', episode_id),
        'title_zh': episode_meta.get('title_zh', episode_meta.get('title', episode_id)),
        'tldr_zh': '',  # 后续从highlight加载
        'worth_listening_verdict': '',
        'target_audience_zh': '',
        'publish_date': ''
    }

    # 2. 加载章节数据 (outline.json)
    chapters = None
    outline_file = media_dir / "outline.json"
    if outline_file.exists():
        # 直接加载JSON，不需要Outline模型验证（outline.json缺少episode_id字段）
        outline_data = safe_read_json(outline_file)
        chapters = outline_data.get('entries', []) if outline_data else []
        logger.info(f"Loaded {len(chapters) if chapters else 0} chapters from outline.json")

    # 3. 加载章节摘要 (summaries.json)
    summaries = None
    summaries_file = media_dir / "summaries.json"
    if summaries_file.exists():
        summaries = load_json_with_callback(summaries_file, lambda d: d)  # summaries是直接数组
        logger.info(f"Loaded {len(summaries) if summaries else 0} summaries from summaries.json")

    # 4. 加载洞察 (highlight.json)
    highlights = []
    highlights_file = media_dir / "highlight.json"
    if highlights_file.exists():
        highlight_data = load_json_with_callback(highlights_file, lambda d: HighlightCard(**d))
        if highlight_data:
            # 从highlight中获取tldr等episode级别信息
            episode['tldr_zh'] = highlight_data.tldr_zh or ''
            episode['worth_listening_verdict'] = highlight_data.worth_listening_verdict or ''
            episode['target_audience_zh'] = highlight_data.target_audience_zh or ''
            highlights = highlight_data.highlights if highlight_data.highlights else []
            logger.info(f"Loaded {len(highlights)} highlights from highlight.json")

    # 5. 准备导出数据
    export_data = {
        'episode': episode,
        'chapters': chapters or [],
        'summaries': summaries or [],
        'highlights': highlights,
        'transcript': []  # 暂时不包含完整字幕
    }

    logger.info(f"Export data prepared: {len(export_data['chapters'])} chapters, {len(export_data['summaries'])} summaries, {len(export_data['highlights'])} highlights")

    # 6. 生成文件名和路径
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_id = f"{episode_id}_{timestamp}"
    
    # 导出目录
    export_dir = data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # 7. 渲染HTML模板
    logger.info(f"Exporting episode {episode_id} as {request.format}")
    
    html_content = render_html_template(
        export_data,
        theme=request.theme,
        include_transcript=request.include_transcript
    )

    # 8. 根据格式生成文件
    expires_at = datetime.now() + timedelta(hours=24)  # 24小时后过期
    download_url = ""
    file_size = 0

    if request.format == "html":
        # 保存HTML文件
        html_file = export_dir / f"{export_id}.html"
        html_file.write_text(html_content, encoding='utf-8')
        
        # 生成下载URL
        download_url = f"/api/exports/{export_id}.html"
        file_size = html_file.stat().st_size

    elif request.format == "png":
        # 渲染PNG
        png_file = export_dir / f"{export_id}.png"
        await render_png_from_html(
            html_content,
            png_file,
            width=request.width,
            scale=2.0
        )
        
        # 生成下载URL
        download_url = f"/api/exports/{export_id}.png"
        file_size = png_file.stat().st_size

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")

    logger.info(f"Export completed: {download_url} ({file_size} bytes)")

    # 9. 返回响应
    return ExportResponse(
        download_url=download_url,
        format=request.format,
        expires_at=expires_at.isoformat(),
        file_size=file_size
    )


@app.get("/api/exports/{filename}")
async def download_export(filename: str):
    """
    下载导出文件

    静态文件服务端点，用于下载生成的HTML或PNG文件
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    from .config import DATA_DIR

    data_dir = DATA_DIR
    export_file = data_dir / "exports" / filename

    if not export_file.exists():
        raise HTTPException(status_code=404, detail="Export file not found")

    # 根据文件类型设置Content-Type
    if filename.endswith('.html'):
        media_type = 'text/html'
    elif filename.endswith('.png'):
        media_type = 'image/png'
    else:
        media_type = 'application/octet-stream'

    return FileResponse(
        export_file,
        media_type=media_type,
        filename=filename
    )
