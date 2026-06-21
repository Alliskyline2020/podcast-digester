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
from .routers import episodes as episodes_router

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
app.include_router(episodes_router.router)


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

class CancelResponse(BaseModel):
    """取消响应"""
    ok: bool = True
    cancelled: str
    message: str = ""


class ResumeRequest(BaseModel):
    """恢复请求"""
    raw_input: Optional[str] = Field(None, description="原始 URL 或文件路径（可选，不提供则从数据库读取）")


class ResumeResponse(BaseModel):
    """恢复响应"""
    ok: bool = True
    episode_id: str
    message: str = "任务已恢复"


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


# ==================== LLM 智能字幕处理 ====================

