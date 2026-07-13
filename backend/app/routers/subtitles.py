"""Subtitle router: transcript + 同步 + LLM 处理 + segment 编辑 + 词库应用。

Routes:
- GET  /api/episodes/{id}/transcript           获取字幕（编辑器使用）
- POST /api/episodes/{id}/sync-subtitles       规则分段
- POST /api/episodes/{id}/sync-subtitles-llm   LLM 智能分段（rate-limited）
- POST /api/episodes/{id}/extract-insights     LLM 金句提取（rate-limited）
- POST /api/episodes/{id}/correct-transcript   LLM ASR 纠错（rate-limited）
- POST /api/episodes/{id}/segments/update      更新单条 segment
- POST /api/episodes/{id}/apply-glossary       全篇应用词库纠错
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import deps
from ..database import EpisodeRepository
from ..models import TranscriptResponse
from ..rate_limit import rate_limit
from ..services.episode_loader import load_episode_bundle
from ..services.background_tasks import (
    create_background_task,
    sync_episode_modules,
)
from ..utils import clean_segment_text
from ..utils.io import safe_read_json


router = APIRouter()
logger = logging.getLogger(__name__)


# ==================== Schemas ====================
# 这些响应/请求模型只在本 router 内使用，inline 在这里定义。

class SyncSubtitlesResponse(BaseModel):
    """字幕同步响应"""
    episode_id: str
    paragraph_count: int
    paragraph_mappings: list
    segment_count: int


class CorrectTranscriptResponse(BaseModel):
    """字幕纠错响应"""
    episode_id: str
    total_segments: int
    corrected_segments: int
    duration_ms: int
    # 下游产物(outline/summaries/highlight/product_insights)的纠错字段数
    # 词库驱动的纯字符串替换,不调 LLM。None = 没触发(老行为)。
    modules_corrected: Optional[dict] = None


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


class InsightExtractionResponse(BaseModel):
    """金句提取响应"""
    episode_id: str
    insights: List[Dict[str, Any]] = Field(default_factory=list, description="提取的金句列表")
    llm_processed: bool = True
    error: Optional[str] = None


@router.get("/api/episodes/{episode_id}/transcript", response_model=TranscriptResponse)
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
    bundle = await load_episode_bundle(episode_id)

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




@router.post("/api/episodes/{episode_id}/sync-subtitles", response_model=SyncSubtitlesResponse)
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
    transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
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
    from ..services.llm_semantic_segmenter import split_into_semantic_segments
    from ..models import Episode

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




@router.post(
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
    transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
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
        from ..services.llm_subtitle_processor import LLMSubtitleProcessor

        processor = LLMSubtitleProcessor()

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




@router.post(
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
    transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
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
        from ..services.llm_subtitle_processor import LLMSubtitleProcessor

        processor = LLMSubtitleProcessor()

        logger.info(f"[LLM Insights] Extracting insights for {episode_id}")
        result = await processor.extract_insights(full_transcript, episode_id, max_insights)

        logger.info(f"[LLM Insights] Extracted {len(result.get('insights', []))} insights")

        return result

    except Exception as e:
        logger.error(f"[LLM Insights] Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"金句提取失败: {str(e)}")




@router.post(
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
    transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
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
        from ..services.llm_subtitle_processor import LLMSubtitleProcessor
        from ..utils.io import atomic_write_json

        processor = LLMSubtitleProcessor()

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




@router.post("/api/episodes/{episode_id}/segments/update", response_model=UpdateSegmentResponse)
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
    bundle = await load_episode_bundle(episode_id)
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
        from ..services.glossary import get_glossary

        # 简单的启发式：提取差异
        if old_text and new_text and old_text != new_text:
            # 假设较短的词是错误词（简化逻辑）
            glossary = get_glossary(deps.data_dir)
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
    create_background_task(
        sync_episode_modules(episode_id, segments_dict),
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




@router.post("/api/episodes/{episode_id}/apply-glossary", response_model=CorrectTranscriptResponse)
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
    bundle = await load_episode_bundle(episode_id)

    # 3. 提取transcript数据
    transcript_dict = bundle.transcript.model_dump() if bundle.transcript else {"segments": []}
    total_segments = len(transcript_dict.get("segments", []))

    if total_segments == 0:
        raise HTTPException(status_code=400, detail="字幕数据为空，无法应用词库纠错")

    # 4. 使用词库纠正
    from ..services.glossary import get_glossary, apply_glossary_to_all_modules
    glossary = get_glossary(deps.data_dir)

    corrected_data, corrected_count = glossary.correct_transcript(transcript_dict)

    # 5. 更新数据库中的transcript
    await EpisodeRepository.update_transcript(episode_id, corrected_data)

    # 6. 同步词库到所有下游产物(outline/summaries/highlight/product_insights)
    # 专有名词纠错是词级替换,语义不变,纯字符串替换即可,不需要 LLM 重算。
    # 字幕编辑后下游产物会过期,这里一次性把同样的替换应用到所有模块。
    media_dir = deps.data_dir / "media" / episode_id
    modules_corrected = apply_glossary_to_all_modules(glossary, episode_id, media_dir)

    duration_ms = int((time.time() - start_time) * 1000)

    logger.info(
        f"[Glossary Apply] Episode {episode_id}: transcript {corrected_count}/{total_segments} segments, "
        f"downstream modules {modules_corrected}"
    )

    # 7. 如果字幕有纠正，同步 paragraph_mappings（不改段落结构）
    if corrected_count > 0:
        create_background_task(
            sync_episode_modules(episode_id, corrected_data["segments"], regenerate_paragraphs=False),
            name=f"sync_modules:{episode_id}",
        )

    return CorrectTranscriptResponse(
        episode_id=episode_id,
        total_segments=total_segments,
        corrected_segments=corrected_count,
        duration_ms=duration_ms,
        modules_corrected=modules_corrected,
    )


# _sync_episode_modules / _create_background_task / _log_task_exception
# 已迁移到 .services.background_tasks，通过顶部 import 引入到本模块命名空间。
# _load_highlight_fast / _load_episode_bundle 等 loader 助手也已迁移到
# .services.episode_loader。所有这些通过顶部 import 的别名引用，调用方无需改动。


# Export API（POST /api/episodes/{id}/export + GET /api/exports/{filename}）
# 已迁移到 routers/export.py。


