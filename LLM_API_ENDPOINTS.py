# LLM 字幕同步和金句提取端点

@app.post("/api/episodes/{episode_id}/sync-subtitles-llm", response_model=SyncSubtitlesResponse)
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


@app.post("/api/episodes/{episode_id}/extract-insights", response_model=InsightExtractionResponse)
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


# 更新响应模型
class InsightExtractionResponse(BaseModel):
    """金句提取响应"""
    episode_id: str
    insights: List[Dict[str, Any]] = Field(default_factory=list, description="提取的金句列表")
    llm_processed: bool = True
    error: Optional[str] = None

