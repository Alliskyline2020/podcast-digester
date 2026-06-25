"""
Episode 数据加载助手。

抽取自 main.py 的辅助函数区，供 router 在不反向 import main 的前提下复用。

包含：
- highlight / duration / progress 的快速加载（并发预取）
- _load_episode_bundle：组装完整 EpisodeBundle（episode + transcript +
  outline + summaries + highlight + ingest_job + product_insights）

文件系统读用 deps.data_dir 属性访问（不用 \`from ..deps import data_dir\`），
以便 conftest 的 temp_data_dir fixture 能在测试时打补丁。
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from .. import deps
from ..database import EpisodeRepository, IngestJobRepository, SourceRepository
from ..models import (
    ChapterSummary,
    ConfidenceType,
    Episode,
    EpisodeBundle,
    EpisodeStatus,
    HighlightCard,
    HighlightItem,
    HighlightKind,
    IngestJob,
    IngestStage,
    Outline,
    OutlineEntry,
    ProductInsights,
    Segment,
    Transcript,
    VerdictType,
)
from ..repositories import (
    HighlightRepository,
    OutlineRepository,
    ProductInsightsRepository,
    SummariesRepository,
)
from ..utils.io import load_json_with_callback, safe_read_json


logger = logging.getLogger(__name__)


# ==================== 快速加载助手 ====================

def load_highlight_fast(episode_id: str) -> Optional[dict]:
    """快速加载 highlight(优先 DB, fallback 文件)。

    必须与 load_episode_bundle(详情 API 用)保持相同的数据源优先级,
    否则列表卡片和播放器详情页会显示不一致的 tldr_zh。
    DB 优先,fallback 文件。
    """
    import sqlite3
    import json
    from app.config import DB_PATH
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT highlights_json FROM highlight WHERE episode_id = ?",
                (episode_id,)
            ).fetchone()
            if row and row["highlights_json"]:
                return json.loads(row["highlights_json"])
    except Exception:
        pass
    # fallback 文件
    highlight_file = deps.data_dir / "media" / episode_id / "highlight.json"
    return safe_read_json(highlight_file)


async def load_highlight_fast_async(episode_id: str) -> Optional[dict]:
    """异步包装：避免在 async 处理器里直接做阻塞 FS 读"""
    return await asyncio.to_thread(load_highlight_fast, episode_id)


def get_duration_fast(episode_id: str) -> Optional[int]:
    """快速获取节目时长（分钟）"""
    transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
    data = safe_read_json(transcript_file)
    if data:
        segments = data.get("segments", [])
        if segments:
            total_ms = segments[-1].get("end_ms", 0)
            return int(total_ms / 1000 / 60)
    return None


async def get_duration_fast_async(episode_id: str) -> Optional[int]:
    """异步包装：避免在 async 处理器里直接做阻塞 FS 读"""
    return await asyncio.to_thread(get_duration_fast, episode_id)


async def prefetch_card_meta(
    episode_id: str, need_duration: bool
) -> tuple[Optional[dict], Optional[int]]:
    """并发预取单个 episode 的 highlight 与 duration，把阻塞 FS 读推到线程池"""
    tasks = [load_highlight_fast_async(episode_id)]
    if need_duration:
        tasks.append(get_duration_fast_async(episode_id))
    results = await asyncio.gather(*tasks)
    highlight = results[0]
    duration = results[1] if need_duration else None
    return highlight, duration


async def load_progress_fast(episode_id: str) -> Optional[dict]:
    """快速加载处理进度

    返回格式：
        {
            "current_stage": "download",
            "stages": [{"id": "download", "name": "下载", "status": "...", "progress": 0.5}, ...],
            "overall_progress": 0.125,
        }
    """
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

    STAGE_NAMES = {
        "download": "下载",
        "transcribe": "转录",
        "chapterize": "分章",
        "summarize": "摘要",
        "highlight": "亮点",
        "translate": "翻译",
        "done": "完成",
    }

    stages_data = []
    total_progress = 0.0
    current_stage_id = job_data.get("current_stage", "")

    for stage in job_data.get("stages", []):
        stage_id = stage.get("name", stage.get("id", ""))
        progress = stage.get("progress", 0.0)
        stage_status = stage.get("status", "")

        if not stage_id:
            continue

        if stage_id in STAGE_WEIGHTS:
            weight = STAGE_WEIGHTS[stage_id]
            if progress >= 1.0:
                total_progress += weight
            elif stage_id == current_stage_id:
                total_progress += weight * progress

        stages_data.append({
            "id": stage_id,
            "name": STAGE_NAMES.get(stage_id, stage_id),
            "status": stage_status,
            "progress": progress,
        })

    return {
        "current_stage": current_stage_id,
        "stages": stages_data,
        "overall_progress": min(total_progress / TOTAL_WEIGHT, 1.0),
    }


# ==================== EpisodeBundle 组装 ====================

def _clean_segment_text(text: str) -> str:
    """清理 segment 文本：解码 HTML 实体、移除标签、合并空格。"""
    if not text:
        return text
    cleaned = text
    cleaned = cleaned.replace("&lt;", "<").replace("&gt;", ">")
    cleaned = cleaned.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
    cleaned = cleaned.replace("&nbsp;", " ")
    cleaned = re.sub(r"<[^>]*>", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def load_episode_bundle(episode_id: str) -> EpisodeBundle:
    """加载完整节目数据包"""
    ep_data = await EpisodeRepository.get_by_id(episode_id)
    if not ep_data:
        raise HTTPException(status_code=404, detail="节目不存在")

    # 从source表读取原始URL
    source_data = await SourceRepository.get_by_episode(episode_id)
    if source_data:
        ep_data["source_url"] = source_data.get("raw_input")

    # 解析paragraph_mappings JSON字符串
    pm_value = ep_data.get("paragraph_mappings")
    logger.debug(f"Original paragraph_mappings type: {type(pm_value)}, value: {bool(pm_value)}")

    if pm_value:
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

    # 加载 transcript - 优先数据库，回退到 transcript.json 文件
    transcript = None
    transcript_json = ep_data.get("transcript")
    if transcript_json:
        try:
            transcript_data = json.loads(transcript_json)
            cleaned_segments = []
            for seg_dict in transcript_data.get("segments", []):
                # 优先处理带标点的文本
                text_with_punct = seg_dict.get("text_with_punct")
                if text_with_punct:
                    seg_dict["text_with_punct"] = _clean_segment_text(text_with_punct)
                # 清理原始文本
                seg_dict["text_original"] = _clean_segment_text(seg_dict.get("text_original", ""))
                cleaned_segments.append(Segment(**seg_dict))

            transcript = Transcript(
                episode_id=episode_id,
                language=transcript_data.get("language", "unknown"),
                segments=cleaned_segments,
            )
        except Exception as e:
            logger.debug(f"[Load Bundle] transcript DB load failed: {e}")

    # DB 无 transcript 时回退到文件系统（pipeline 的 checkpoint 落盘）
    if transcript is None:
        transcript_file = deps.data_dir / "media" / episode_id / "transcript.json"
        if transcript_file.exists():
            try:
                transcript_data = safe_read_json(transcript_file)
                if transcript_data and transcript_data.get("segments"):
                    cleaned_segments = []
                    for seg_dict in transcript_data.get("segments", []):
                        text_with_punct = seg_dict.get("text_with_punct")
                        if text_with_punct:
                            seg_dict["text_with_punct"] = _clean_segment_text(text_with_punct)
                        seg_dict["text_original"] = _clean_segment_text(seg_dict.get("text_original", ""))
                        cleaned_segments.append(Segment(**seg_dict))
                    transcript = Transcript(
                        episode_id=episode_id,
                        language=transcript_data.get("language", "unknown"),
                        segments=cleaned_segments,
                    )
                    logger.debug(f"[Load Bundle] transcript loaded from file: {len(cleaned_segments)} segments")
            except Exception as e:
                logger.debug(f"[Load Bundle] transcript file load failed: {e}")

    # 加载 outline - 从数据库读取，失败时回退到文件系统
    outline = None
    try:
        outline_data = await OutlineRepository.get(episode_id)
        if outline_data and outline_data.get("entries"):
            outline_data["episode_id"] = episode_id
            entries_data = outline_data.get("entries")
            if isinstance(entries_data, dict) and "entries" in entries_data:
                entries_list = entries_data["entries"]
            else:
                entries_list = entries_data if isinstance(entries_data, list) else []
            outline_data["entries"] = [OutlineEntry(**e) for e in entries_list]
            outline = Outline(**outline_data)
    except Exception as e:
        logger.debug(f"[Load Bundle] outline DB load failed, trying filesystem: {e}")
        outline_file = deps.data_dir / "media" / episode_id / "outline.json"
        if outline_file.exists():
            def prepare_outline(data):
                data["episode_id"] = episode_id
                data["entries"] = [OutlineEntry(**e) for e in data.get("entries", [])]
                return Outline(**data)
            outline = load_json_with_callback(outline_file, prepare_outline)

    # 加载章节摘要 - 从数据库读取，失败时回退到文件系统
    summaries = []
    try:
        summaries_data = await SummariesRepository.get(episode_id)
        if summaries_data and summaries_data.get("summaries_json"):
            summaries_list = json.loads(summaries_data["summaries_json"])
            summaries = [ChapterSummary(**s) for s in summaries_list]
    except Exception as e:
        logger.debug(f"[Load Bundle] summaries DB load failed, trying filesystem: {e}")
        summaries_file = deps.data_dir / "media" / episode_id / "summaries.json"
        if summaries_file.exists():
            def prepare_summaries(data):
                return [ChapterSummary(**s) for s in data]
            summaries = load_json_with_callback(summaries_file, prepare_summaries) or []

    # 加载 highlight - 从数据库读取，失败时回退到文件系统
    highlight = None
    try:
        from pydantic import ValidationError as PydanticValidationError

        highlight_data = await HighlightRepository.get(episode_id)
        if highlight_data and "highlights" in highlight_data:
            card_data = highlight_data["highlights"]

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
                    logger.debug(f"[Load Bundle] highlight items parse failed: {e}")

            try:
                if "worth_listening_verdict" in card_data:
                    card_data["worth_listening_verdict"] = VerdictType(card_data["worth_listening_verdict"])
                if "verdict_confidence" in card_data:
                    card_data["verdict_confidence"] = ConfidenceType(card_data["verdict_confidence"])
            except Exception as e:
                logger.debug(f"[Load Bundle] enum conversion failed: {e}")

            try:
                highlight = HighlightCard(**card_data)
            except PydanticValidationError as ve:
                raise
    except Exception as e:
        logger.debug(f"[Load Bundle] highlight DB load failed, trying filesystem: {e}")
        highlight_file = deps.data_dir / "media" / episode_id / "highlight.json"
        if highlight_file.exists():
            def prepare_highlight(data):
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
                if "worth_listening_verdict" in data:
                    data["worth_listening_verdict"] = VerdictType(data["worth_listening_verdict"])
                if "verdict_confidence" in data:
                    data["verdict_confidence"] = ConfidenceType(data["verdict_confidence"])
                return data
            highlight_raw = load_json_with_callback(highlight_file, prepare_highlight)
            if highlight_raw:
                highlight = HighlightCard(**highlight_raw)

    # 加载 product_insights - 从数据库读取，失败时回退到文件系统
    product_insights = None
    try:
        insights_data = await ProductInsightsRepository.get(episode_id)
        if insights_data and insights_data.get("insights_json"):
            insights_dict = json.loads(insights_data["insights_json"])
            product_insights = ProductInsights(**insights_dict)
    except Exception as e:
        logger.debug(f"[Load Bundle] product_insights DB load failed, trying filesystem: {e}")
        insights_file = deps.data_dir / "media" / episode_id / "product_insights.json"
        if insights_file.exists():
            product_insights = load_json_with_callback(insights_file, lambda d: ProductInsights(**d))

    # 加载 ingest_job（如果还在处理中）
    ingest_job = None
    if episode.status in [
        EpisodeStatus.PENDING,
        EpisodeStatus.DOWNLOADING,
        EpisodeStatus.ASR_RUNNING,
        EpisodeStatus.LLM_RUNNING,
    ]:
        job_data = await IngestJobRepository.get_by_id(episode_id)
        if job_data:
            ingest_job = IngestJob(
                episode_id=job_data["episode_id"],
                current_stage=job_data["current_stage"],
                stages=[IngestStage(**s) for s in job_data.get("stages", [])],
                created_at=datetime.fromisoformat(job_data["created_at"]),
                updated_at=datetime.fromisoformat(job_data["updated_at"]),
            )

    # 加载非致命失败状态文件（标点恢复等），让前端能展示"为何字幕没有标点"。
    punctuation_status = None
    punctuation_status_file = deps.data_dir / "media" / episode_id / "punctuation_status.json"
    if punctuation_status_file.exists():
        try:
            punctuation_status = json.loads(punctuation_status_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug(f"[Load Bundle] punctuation_status.json unreadable: {e}")

    return EpisodeBundle(
        episode=episode,
        transcript=transcript,
        outline=outline,
        chapter_summaries=summaries,
        highlight=highlight,
        ingest_job=ingest_job,
        product_insights=product_insights,
        punctuation_status=punctuation_status,
    )
