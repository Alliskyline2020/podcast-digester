"""
音频处理管道主入口
整合 8 阶段处理流程：下载 → ASR → 分章 → 摘要 → 翻译 → 高亮 → 产品洞察 → 持久化
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Any, List, Dict
from datetime import datetime

from .models import EpisodeStatus, Transcript
from .database import EpisodeRepository, IngestJobRepository
from .sources.registry import resolve_source
from .asr_afm3 import run_asr
from .storage import save_episode_bundle, EpisodeManager
from .errors import ConcurrencyError
from .config import (
    STAGE_CONFIG, STAGE_ORDER, calculate_overall_progress,
)

# LLM 处理模块
from .llm_pipeline import (
    split_into_chapters,
    generate_chapter_summaries,
    extract_highlights,
)
from .llm_pipeline.llm_product_insights import run_product_insights_stage
from .llm_pipeline.llm_launch_analyze import analyze_launch_specs
from .llm_pipeline.llm_podcast_analyze import analyze_podcast_insights_parallel
from .services.subtitle_segmenter import SubtitleSegmenter
from .services.subtitle_processor import SubtitleProcessor


logger = logging.getLogger(__name__)


class AudioProcessPipeline:
    """音频处理管道（8阶段处理流程）

    处理流程：
    1. 下载 (download): 从 URL/文件下载音频，权重 20%
    2. 转录 (transcribe): ASR 语音识别，权重 20%
    3. 分章 (chapterize): 拆分章节，权重 10%
    4. 摘要 (summarize): 生成章节摘要，权重 17%
    5. 翻译 (translate): 翻译为中文（仅非中文内容），权重 18%
    6. 高亮 (highlight): 提取亮点，权重 18%
    7. 产品洞察 (product_insights): 提取产品和技术洞察，权重 15%
    8. 持久化 (done): 保存结果，完成

    任务管理：
    - 使用 asyncio.Lock 防止竞态条件
    - current_tasks 追踪正在运行的任务
    - 支持 replace_existing 取消旧任务
    - 自动清理完成的任务

    进度追踪：
    - 每个阶段 0-1 进度
    - 总进度根据阶段权重计算
    - 实时同步到数据库（ingest_job 表）

    字幕优先级策略：
    1. YouTube 字幕（如果检测到 YouTube URL）
    2. Parser 提供的字幕
    3. 预存的 transcript.json
    4. 本地 ASR（最后手段）

    与其他组件的关系：
    - Worker: 调用 pipeline.run_ingest()
    - IngestPipeline: 委托给 AudioProcessPipeline
    - EpisodeRepository: 更新节目状态
    - IngestJobRepository: 同步处理阶段

    Attributes:
        data_dir: 数据目录
        current_tasks: 正在运行的任务映射 {episode_id: Task}
        _lock: 异步锁，防止竞态条件
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.current_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def process_episode(
        self,
        episode_id: str,
        raw_input: str,
        on_progress: Optional[Callable[[str, float, float], Any]] = None,
        replace_existing: bool = False,
    ) -> None:
        """
        运行完整的音频处理流程

        Args:
            episode_id: 节目 ID
            raw_input: 用户输入的 URL 或路径
            on_progress: 进度回调 (stage_id, stage_progress, overall_progress)
            replace_existing: 如果任务已存在，是否取消旧任务并创建新任务

        Raises:
            ConcurrencyError: 当任务已存在且replace_existing=False时
        """
        # 使用锁防止竞态条件
        async with self._lock:
            # 检查是否有正在运行的任务
            if episode_id in self.current_tasks:
                if replace_existing:
                    # 取消旧任务并等待其完成
                    old_task = self.current_tasks[episode_id]
                    old_task.cancel()
                    logger.info(f"Cancelled existing task for {episode_id}, waiting for cleanup...")
                    # 等待旧任务真正停止（避免资源竞争）
                    try:
                        await asyncio.wait_for(old_task, timeout=5.0)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        # 任务超时或已被取消，继续
                        logger.warning(f"Old task for {episode_id} did not stop cleanly")
                    del self.current_tasks[episode_id]
                else:
                    # 抛出并发冲突错误
                    raise ConcurrencyError(
                        f"Episode {episode_id} already has a running task",
                        episode_id=episode_id,
                    )

        def update_progress(stage_id: str, progress: float):
            """更新进度"""
            if on_progress:
                overall = calculate_overall_progress(stage_id, progress)
                on_progress(stage_id, progress, overall)

        try:
            await self._process_internal(
                episode_id, raw_input, update_progress
            )
        except asyncio.CancelledError:
            logger.info(f"Task for {episode_id} was cancelled")
            raise
        finally:
            async with self._lock:
                self.current_tasks.pop(episode_id, None)

    def _checkpoint_json(self, episode_id: str, filename: str, data) -> None:
        """阶段级 checkpoint：立即把单个中间产物落盘，不碰 episode 状态。

        save_episode_bundle 只在最后阶段 8 一次性写入并把 status 翻成 ready，
        中途崩溃会丢失所有产物；而 product_insights 等阶段需要读前面的 JSON。
        所以每个阶段完成后单独写一份，保证后续阶段可读 + 崩溃可恢复。
        """
        import json
        media_dir = self.data_dir / "media" / episode_id
        media_dir.mkdir(parents=True, exist_ok=True)
        with open(media_dir / filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[checkpoint] {filename} saved for {episode_id}")

    async def _process_internal(
        self,
        episode_id: str,
        raw_input: str,
        on_progress: Callable[[str, float], Any],
    ) -> None:
        """内部处理实现"""
        from .utils.validation import validate_raw_input

        # 验证输入（防止注入攻击）
        try:
            validated_input = validate_raw_input(raw_input)
        except ValueError as e:
            logger.error(f"Invalid input for {episode_id}: {e}")
            await EpisodeRepository.update_status(
                episode_id,
                "failed",
                error_msg=f"Invalid input: {str(e)}"
            )
            raise ValueError(f"Invalid input: {e}")

        stages = []
        completed_stages = []

        async def sync_stages():
            """同步阶段到数据库（确保等待完成）"""
            if stages:
                await IngestJobRepository.update_stages(
                    episode_id,
                    [self._format_stage(s) for s in stages],
                    stages[-1]["id"] if stages else "pending",
                )

        # === 阶段 0: 初始化任务 ===
        await IngestJobRepository.create(episode_id)
        await sync_stages()

        # 使用验证后的输入
        raw_input = validated_input

        # === 阶段 1: 下载音频 ===
        await self._add_stage(stages, "download", EpisodeStatus.DOWNLOADING, sync_stages)

        parser = await resolve_source(raw_input)
        media_dir = self.data_dir / "media" / episode_id
        media_dir.mkdir(parents=True, exist_ok=True)

        # 下载带进度回调
        def download_progress(s, p):
            stages[-1]["progress"] = p
            if on_progress:
                on_progress("download", p)
            # yt-dlp 进度回调是同步的；DB 写库 fire-and-forget，
            # 否则 async 函数被同步调用会变成 never-awaited 协程
            asyncio.create_task(IngestJobRepository.update_stages(
                episode_id,
                [self._format_stage(s) for s in stages],
                stages[-1]["id"],
            ))

        parse_result = await parser.parse(raw_input, episode_id, media_dir, download_progress)

        # 翻译标题（英文→中文，方便检索和展示；纯中文标题直接复用）
        title_zh = await self._translate_title(parse_result.title)

        # 更新 episode 信息
        await EpisodeRepository.update(
            episode_id,
            title=parse_result.title,
            title_zh=title_zh,
            media_path=str(parse_result.audio_path),
            language=parse_result.language,
        )

        await self._complete_stage(stages, "download", completed_stages, sync_stages)

        # === 阶段 2: 转录 ===
        await self._add_stage(stages, "transcribe", EpisodeStatus.ASR_RUNNING, sync_stages)

        # 转录来源优先级：
        # 1. YouTube 字幕（双语合并：英文=原文，中文=翻译，质量最佳）
        # 2. 本地 checkpoint（resume 场景）
        # 3. parser 提供的字幕（下载阶段已抓取）
        # 4. ASR 兜底（无任何字幕时；长音频可能质量差）
        transcript = await self._try_fetch_subtitles(raw_input, episode_id)
        if not transcript:
            transcript = await self._load_transcript(episode_id)
        if not transcript:
            transcript = parse_result.extra.get("transcript")

        if not transcript:
            logger.info(f"No subtitle available for {episode_id}, falling back to Apple AFM 3 ASR")
            transcript = await run_asr(parse_result.audio_path, None)
            transcript.episode_id = episode_id
        else:
            logger.info(f"Using transcript ({len(transcript.segments)} segments, lang={transcript.language}) for {episode_id}")
            transcript.episode_id = episode_id

        # 统一把语种写回 DB（ASR 分支原本缺这步，导致 episode.language 字段为空，
        # 前端语种标签无法展示）。两个分支都执行，幂等。
        if transcript.language:
            await EpisodeRepository.update(episode_id, language=transcript.language)

        # 生成字幕段落映射
        await self._generate_paragraph_mappings(episode_id, transcript)

        # === 阶段 2.5: 字幕润色（双语，加标点+去口水话，时间戳/语义/段数不变）===
        await SubtitleProcessor().polish(
            transcript,
            progress_cb=(lambda p: on_progress("polish", p)) if on_progress else None,
        )

        # P1：润色后重新生成段落映射，让段落字幕消费 text_with_punct（带标点+去口水话）
        # 而非上面 line-261 用 raw ASR 生成的版本。早期那次调用保留——保证 transcribe
        # 一完成字幕就可见；这里是"最终态"刷新。
        await self._generate_paragraph_mappings(episode_id, transcript)

        self._checkpoint_json(episode_id, "transcript.json", transcript.model_dump())
        await self._complete_stage(stages, "transcribe", completed_stages, sync_stages)

        # === 阶段 3: 分章 ===
        await self._add_stage(stages, "chapterize", EpisodeStatus.LLM_RUNNING, sync_stages)

        chapters = await split_into_chapters(
            transcript,
            progress_cb=lambda p: self._update_stage_progress_sync(stages, "chapterize", p, episode_id, sync_stages),
        )
        self._checkpoint_json(episode_id, "outline.json", {"entries": chapters})
        await self._complete_stage(stages, "chapterize", completed_stages, sync_stages)

        # === 阶段 4: 章节摘要 ===
        await self._add_stage(stages, "summarize", EpisodeStatus.LLM_RUNNING, sync_stages)

        summaries = await generate_chapter_summaries(
            chapters, transcript,
            progress_cb=lambda p: self._update_stage_progress_sync(stages, "summarize", p, episode_id, sync_stages),
        )
        self._checkpoint_json(episode_id, "summaries.json", summaries)
        await self._complete_stage(stages, "summarize", completed_stages, sync_stages)

        # === 阶段 5: 翻译（可选，EN→ZH，结构校验+不丢段）===
        # 双语字幕合并后 text_translated 已有中文 → 跳过；英文单语才翻译。
        # 下游 split/summary/highlight/insights 统一用 text_translated 优先。
        _translated_ratio = (
            sum(1 for s in transcript.segments if s.text_translated) /
            max(len(transcript.segments), 1)
        )
        if transcript.language != "zh" and _translated_ratio < 0.5:
            logger.info(f"Translate needed (translated ratio {_translated_ratio:.0%})")
            await self._add_stage(stages, "translate", EpisodeStatus.LLM_RUNNING, sync_stages)
            await SubtitleProcessor().translate(
                transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "translate", p, episode_id, sync_stages),
            )
            # P1：翻译后再次刷新段落映射——en-source 现在拿到 text_translated，
            # 段落级 text_translated 才会填充。zh-source 跳过 translate 块，
            # 上面的 post-polish 调用就是最终态。
            await self._generate_paragraph_mappings(episode_id, transcript)
            self._checkpoint_json(episode_id, "transcript.json", transcript.model_dump())
            await self._complete_stage(stages, "translate", completed_stages, sync_stages)

        # === 阶段 6: 高亮提取 ===
        await self._add_stage(stages, "highlight", EpisodeStatus.LLM_RUNNING, sync_stages)

        highlight = await extract_highlights(
            parse_result.title,
            sum((s.end_ms - s.start_ms) for s in transcript.segments) / 1000 / 60,
            chapters,
            summaries,
            transcript,
            progress_cb=lambda p: self._update_stage_progress_sync(stages, "highlight", p, episode_id, sync_stages),
        )
        self._checkpoint_json(episode_id, "highlight.json", highlight.model_dump())
        await self._complete_stage(stages, "highlight", completed_stages, sync_stages)

        # === 阶段 7: 产品和技术洞察 ===
        await self._add_stage(stages, "product_insights", EpisodeStatus.LLM_RUNNING, sync_stages)

        product_insights = await run_product_insights_stage(
            episode_id,
            self.data_dir,
            progress_cb=lambda p: self._update_stage_progress_sync(stages, "product_insights", p, episode_id, sync_stages),
        )
        await self._complete_stage(stages, "product_insights", completed_stages, sync_stages)

        # === 阶段 8: 持久化 ===
        await self._add_stage(stages, "done", EpisodeStatus.READY, sync_stages)

        # 保存数据到文件系统和数据库
        save_episode_bundle(
            episode_id,
            self.data_dir,
            transcript=transcript,
            outline={"entries": chapters},
            summaries=summaries,
            highlight=highlight,
        )

        # 保存派生数据到数据库
        if chapters:
            from app.repositories import OutlineRepository
            await OutlineRepository.set(episode_id, chapters)

        if summaries:
            from app.repositories import SummariesRepository
            await SummariesRepository.set(episode_id, summaries)

        if highlight:
            from app.repositories import HighlightRepository
            await HighlightRepository.set(episode_id, highlight.model_dump())

        if product_insights:
            from app.repositories import ProductInsightsRepository
            await ProductInsightsRepository.set(episode_id, product_insights.model_dump())

        await self._complete_stage(stages, "done", completed_stages, sync_stages)

    async def _add_stage(self, stages: list, stage_id: str, status: EpisodeStatus, sync_fn):
        """添加新阶段"""
        config = STAGE_CONFIG[stage_id]
        stages.append({
            "id": stage_id,
            "name": config["name"],
            "status": status.value,
            "progress": 0.0,
            "started_at": datetime.now().isoformat(),
        })
        await sync_fn()

    async def _complete_stage(self, stages: list, stage_id: str, completed: list, sync_fn):
        """完成阶段"""
        stages[-1]["progress"] = 1.0
        stages[-1]["completed_at"] = datetime.now().isoformat()
        completed.append(stage_id)
        await sync_fn()

    def _update_stage_progress(self, stages: list, stage_id: str, progress: float):
        """更新阶段进度（内存）"""
        for s in stages:
            if s["id"] == stage_id:
                s["progress"] = progress
                break

    async def _update_stage_progress_sync(
        self, stages: list, stage_id: str, progress: float,
        episode_id: str, sync_fn
    ):
        """更新阶段进度并同步到数据库"""
        self._update_stage_progress(stages, stage_id, progress)
        await sync_fn()

    async def _try_fetch_subtitles(self, raw_input: str, episode_id: str) -> Optional[Transcript]:
        """
        尝试从云端获取字幕（跳过 ASR）
        优先级: YouTube 字幕 > 通用 yt-dlp 字幕
        """
        from .sources.ytdlp_runner import fetch_youtube_subtitles
        import re

        logger = logging.getLogger(__name__)

        # 检测是否为 YouTube URL
        youtube_pattern = re.compile(
            r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+'
        )

        if youtube_pattern.search(raw_input):
            try:
                logger.info(f"Attempting to fetch YouTube subtitles for {episode_id}")
                transcript = await fetch_youtube_subtitles(raw_input)
                if transcript and len(transcript.segments) > 5:
                    # 质量门控：拦截 YouTube 自动字幕的垃圾数据
                    # (", , ," 纯逗号 / 大量空洞 / 极低覆盖率)。
                    # 残缺字幕会让下游 LLM 在 49 个碎片上幻觉合成，
                    # 产出"看似成功实则全错"的摘要/亮点。
                    is_valid, reason = self._validate_subtitle_quality(transcript)
                    if not is_valid:
                        logger.warning(
                            f"Subtitle quality check FAILED for {episode_id} "
                            f"({reason}), falling back to ASR"
                        )
                        return None
                    logger.info(
                        f"Successfully fetched {len(transcript.segments)} subtitle segments "
                        f"(quality OK)"
                    )
                    return transcript
            except Exception as e:
                logger.warning(f"YouTube subtitle fetch failed: {e}")

        return None

    @staticmethod
    def _validate_subtitle_quality(transcript) -> tuple[bool, str]:
        """检测 YouTube 自动字幕的垃圾数据，避免下游 LLM 基于残缺输入产生幻觉。

        三道门控任一命中即判定不可用：
        1. 垃圾段比例 > 30%（text_original 去掉逗号/句号/空白后 < 3 字符）
        2. 平均 segment 间隔 > 30 秒（章节之间存在大量空洞）
        3. 字幕覆盖率 < 30%（基于首末 segment 的跨度，不依赖 ffprobe）

        Returns:
            (is_valid, reason) - is_valid=False 时 reason 描述命中哪个门控
        """
        segments = transcript.segments
        if not segments:
            return False, "no segments"

        n = len(segments)

        # 1. 垃圾段比例
        junk_count = 0
        for seg in segments:
            text = (seg.text_original or "").replace(",", "").replace(".", "").strip()
            if len(text) < 3:
                junk_count += 1
        junk_ratio = junk_count / n
        if junk_ratio > 0.3:
            return False, f"junk_ratio={junk_ratio:.0%} ({junk_count}/{n})"

        # 2. 平均间隔（相邻 segment 之间的空洞）
        if n >= 2:
            gaps = []
            for i in range(1, n):
                gap = segments[i].start_ms - segments[i - 1].end_ms
                if gap > 0:
                    gaps.append(gap)
            if gaps:
                avg_gap_ms = sum(gaps) / len(gaps)
                if avg_gap_ms > 30_000:
                    return False, f"avg_gap={avg_gap_ms / 1000:.0f}s"

        # 3. 覆盖率（总 speech 时长 / 首末跨度）
        total_speech = sum(s.end_ms - s.start_ms for s in segments)
        span_ms = segments[-1].end_ms - segments[0].start_ms
        if span_ms > 0:
            coverage = total_speech / span_ms
            if coverage < 0.3:
                return False, f"coverage={coverage:.0%}"

        return True, ""

    async def _translate_title(self, title: str) -> Optional[str]:
        """翻译节目标题为中文。

        - 纯中文标题（CJK 字符占比 > 30%）直接返回原文，省一次 LLM 调用
        - 英文/混合标题用 DeepSeek 翻译，保留人名/品牌名原文
        - 翻译失败返回 None，不阻塞 pipeline（下游显示原文）

        Args:
            title: 原始标题（可能是任何语言）

        Returns:
            中文标题字符串，或 None（翻译失败/空标题）
        """
        if not title or not title.strip():
            return None

        # 已经是中文为主的标题，直接复用
        cjk_count = sum(1 for c in title if "\u4e00" <= c <= "\u9fff")
        if cjk_count / max(len(title), 1) > 0.3:
            logger.info(f"标题已是中文为主，跳过翻译: {title[:40]}")
            return title

        try:
            from .llm import chat_json
            result = await chat_json(
                system=(
                    "你是一位专业的播客标题翻译。把英文播客标题翻译成自然流畅的中文，"
                    "保持原标题的语气、悬念和吸引点。人名/品牌名保留原文（可在括号内补中文译名）。"
                    "只返回 JSON。"
                ),
                user=(
                    f"翻译以下播客标题为中文。返回格式：{{\"title_zh\": \"翻译后的标题\"}}。\n\n"
                    f"标题：{title}"
                ),
                max_tokens=200,
                temperature=0.3,
            )
            translated = (result.get("title_zh") or "").strip()
            if translated:
                logger.info(f"标题翻译: {title[:40]} → {translated[:40]}")
                return translated
            return None
        except Exception as e:
            logger.warning(f"标题翻译失败 ({title[:40]}...): {e}")
            return None

    async def _load_transcript(self, episode_id: str) -> Optional[Transcript]:
        """从文件加载 transcript"""
        from .utils.io import load_json_with_callback

        transcript_file = self.data_dir / "media" / episode_id / "transcript.json"

        def prepare_transcript(data):
            data["episode_id"] = episode_id
            return Transcript(**data)

        return load_json_with_callback(transcript_file, prepare_transcript)

    async def _generate_paragraph_mappings(self, episode_id: str, transcript):
        """生成字幕段落映射（idempotent，可多次调用）

        P1 修复（语言命名重构 Phase 4a）：通过收敛点
        `segments_for_segmenter` 构造 segmenter 输入，使段落字幕优先消费
        `text_with_punct`（润色后带标点文本），而不是 raw ASR。
        pipeline 会在 transcribe 后（早期可见性）、polish 后、translate 后
        多次调用本方法 —— 最终态反映最完整的文本。

        Args:
            episode_id: 节目 ID
            transcript: Transcript 对象（episode_id 需已设置）
        """
        if not transcript or not transcript.segments:
            logger.info(f"No transcript segments for {episode_id}, skipping paragraph generation")
            return

        # 收敛点：单一构造 segmenter 输入（P1：优先 text_with_punct）
        from .services.segmenter_input import segments_for_segmenter
        segments_input = segments_for_segmenter(transcript)

        # 执行分段
        segmenter = SubtitleSegmenter()
        paragraph_mappings = segmenter.segment(segments_input)

        # 持久化
        await EpisodeRepository.update(episode_id, **{
            "paragraph_mappings": paragraph_mappings
        })

        logger.info(f"Generated {len(paragraph_mappings)} paragraph mappings for episode {episode_id}")

    def _format_stage(self, stage: dict) -> dict:
        """格式化阶段数据给数据库"""
        return {
            "name": stage.get("id", "pending"),
            "status": stage.get("status"),
            "progress": stage.get("progress", 0.0),
            "started_at": stage.get("started_at"),
            "completed_at": stage.get("completed_at"),
            "error": stage.get("error"),
        }

    async def cancel(self, episode_id: str) -> bool:
        """取消正在进行的任务"""
        async with self._lock:
            task = self.current_tasks.get(episode_id)
            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled task for episode_id: {episode_id}")
                return True
        return False

    def _check_existing_files(self, episode_id: str) -> dict:
        """检查已存在的文件，确定哪些阶段已完成

        Returns:
            dict: {'transcript': bool, 'outline': bool, 'summaries': bool, 'highlight': bool}
        """
        media_dir = self.data_dir / "media" / episode_id
        return {
            'transcript': (media_dir / "transcript.json").exists(),
            'outline': (media_dir / "outline.json").exists(),
            'summaries': (media_dir / "summaries.json").exists(),
            'highlight': (media_dir / "highlight.json").exists(),
        }

    async def _load_intermediate_results(self, episode_id: str) -> dict:
        """加载中间结果用于恢复处理

        Returns:
            dict: {'transcript': Transcript|None, 'chapters': list|None, 'summaries': list|None}
        """
        from .models import Transcript, OutlineEntry, ChapterSummary
        from .utils.io import load_json_with_callback
        import json

        media_dir = self.data_dir / "media" / episode_id
        results = {'transcript': None, 'chapters': None, 'summaries': None}

        # 加载 transcript
        transcript_file = media_dir / "transcript.json"
        if transcript_file.exists():
            def prepare_transcript(data):
                data["episode_id"] = episode_id
                return Transcript(**data)
            results['transcript'] = load_json_with_callback(transcript_file, prepare_transcript)

        # 加载 outline/chapters
        outline_file = media_dir / "outline.json"
        if outline_file.exists():
            with open(outline_file, 'r', encoding='utf-8') as f:
                outline_data = json.load(f)
                # 容错：历史上 outline.json 可能在 chapterize 检查点之后、
                # summarize 注入 index 之前崩溃时缺少 index 字段——补上位置序号，
                # 避免 OutlineEntry 校验失败阻塞 resume。
                entries = outline_data.get('entries', [])
                results['chapters'] = [
                    OutlineEntry(**{'index': i}, **e) for i, e in enumerate(entries)
                ]

        # 加载 summaries
        summaries_file = media_dir / "summaries.json"
        if summaries_file.exists():
            def prepare_summaries(data):
                return [ChapterSummary(**s) for s in data]
            results['summaries'] = load_json_with_callback(summaries_file, prepare_summaries)

        return results

    async def resume_episode(self, episode_id: str, raw_input: str, on_progress: Optional[Callable[[str, float, float], Any]] = None) -> None:
        """
        恢复中断的节目处理

        Args:
            episode_id: 节目 ID
            raw_input: 原始输入（用于重新下载）
            on_progress: 进度回调
        """
        # 检查现有文件
        existing = self._check_existing_files(episode_id)

        # 如果没有任何文件，从头开始
        if not any(existing.values()):
            logger.info(f"No existing files for {episode_id}, starting from scratch")
            await self.process_episode(episode_id, raw_input, on_progress)
            return

        # 加载中间结果
        intermediate = await self._load_intermediate_results(episode_id)

        logger.info(f"Resuming {episode_id}, existing: {existing}")

        def update_progress(stage_id: str, progress: float):
            if on_progress:
                overall = calculate_overall_progress(stage_id, progress)
                on_progress(stage_id, progress, overall)

        try:
            await self._resume_internal(
                episode_id, raw_input, update_progress, existing, intermediate
            )
        except asyncio.CancelledError:
            logger.info(f"Resume task for {episode_id} was cancelled")
            raise
        finally:
            async with self._lock:
                self.current_tasks.pop(episode_id, None)

    async def _resume_internal(
        self,
        episode_id: str,
        raw_input: str,
        on_progress: Callable[[str, float], Any],
        existing: dict,
        intermediate: dict,
    ) -> None:
        """内部恢复实现"""
        from .utils.validation import validate_raw_input

        # 验证输入
        try:
            validated_input = validate_raw_input(raw_input)
        except ValueError as e:
            logger.error(f"Invalid input for {episode_id}: {e}")
            await EpisodeRepository.update_status(
                episode_id, "failed", error_msg=f"Invalid input: {str(e)}"
            )
            raise ValueError(f"Invalid input: {e}")

        stages = []
        completed_stages = []

        async def sync_stages():
            if stages:
                await IngestJobRepository.update_stages(
                    episode_id,
                    [self._format_stage(s) for s in stages],
                    stages[-1]["id"] if stages else "pending",
                )

        # 初始化或加载任务
        job = await IngestJobRepository.get_by_id(episode_id)
        if not job:
            await IngestJobRepository.create(episode_id)

        # 标记已完成的阶段
        if existing['transcript']:
            completed_stages.extend(['download', 'transcribe'])
        if existing['outline']:
            completed_stages.append('chapterize')
        if existing['summaries']:
            completed_stages.append('summarize')
        if existing['highlight']:
            completed_stages.extend(['translate', 'highlight'])

        raw_input = validated_input
        transcript = intermediate.get('transcript')
        chapters = intermediate.get('chapters')
        summaries = intermediate.get('summaries')

        # === 阶段 1: 下载（如需要）===
        if not existing['transcript']:
            await self._add_stage(stages, "download", EpisodeStatus.DOWNLOADING, sync_stages)

            parser = await resolve_source(raw_input)
            media_dir = self.data_dir / "media" / episode_id
            media_dir.mkdir(parents=True, exist_ok=True)

            def download_progress(s, p):
                stages[-1]["progress"] = p
                if on_progress:
                    on_progress("download", p)
                asyncio.create_task(IngestJobRepository.update_stages(
                    episode_id,
                    [self._format_stage(s) for s in stages],
                    stages[-1]["id"],
                ))

            parse_result = await parser.parse(raw_input, episode_id, media_dir, download_progress)

            await EpisodeRepository.update(
                episode_id,
                title=parse_result.title,
                media_path=str(parse_result.audio_path),
                language=parse_result.language,
            )

            await self._complete_stage(stages, "download", completed_stages, sync_stages)
        else:
            logger.info(f"Download stage already complete for {episode_id}")

        # === 阶段 2: 转录（如需要）===
        if not existing['transcript']:
            await self._add_stage(stages, "transcribe", EpisodeStatus.ASR_RUNNING, sync_stages)

            # 尝试获取字幕
            transcript = await self._try_fetch_subtitles(raw_input, episode_id)

            if not transcript:
                parser = await resolve_source(raw_input)
                media_dir = self.data_dir / "media" / episode_id
                parse_result = await parser.parse(raw_input, episode_id, media_dir, lambda s, p: None)
                transcript = parse_result.extra.get("transcript")

            if not transcript:
                transcript = await self._load_transcript(episode_id)

            if not transcript:
                logger.info(f"Using ASR for {episode_id}")
                if 'parse_result' not in locals():
                    parser = await resolve_source(raw_input)
                    media_dir = self.data_dir / "media" / episode_id
                    parse_result = await parser.parse(raw_input, episode_id, media_dir, lambda s, p: None)
                transcript = await run_asr(parse_result.audio_path, None)
                transcript.episode_id = episode_id
                # Apple AFM 3默认中文，无需更新language字段
            else:
                logger.info(f"Using existing transcript for {episode_id}")
                transcript.episode_id = episode_id
                if transcript.language:
                    await EpisodeRepository.update(episode_id, language=transcript.language)

            # 生成字幕段落映射
            await self._generate_paragraph_mappings(episode_id, transcript)

            await self._complete_stage(stages, "transcribe", completed_stages, sync_stages)
        else:
            logger.info(f"Transcript already exists for {episode_id}")

        # === 阶段 3: 分章（如需要）===
        if not existing['outline']:
            await self._add_stage(stages, "chapterize", EpisodeStatus.LLM_RUNNING, sync_stages)

            chapters = await split_into_chapters(
                transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "chapterize", p, episode_id, sync_stages),
            )
            await self._complete_stage(stages, "chapterize", completed_stages, sync_stages)
        else:
            logger.info(f"Outline already exists for {episode_id}, {len(chapters) if chapters else 0} chapters")

        # === 阶段 4: 章节摘要（如需要）===
        if not existing['summaries']:
            await self._add_stage(stages, "summarize", EpisodeStatus.LLM_RUNNING, sync_stages)

            summaries = await generate_chapter_summaries(
                chapters, transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "summarize", p, episode_id, sync_stages),
            )
            await self._complete_stage(stages, "summarize", completed_stages, sync_stages)
        else:
            logger.info(f"Summaries already exist for {episode_id}")

        # === 阶段 5: 翻译（如需要）===
        _translated_ratio = sum(1 for s in transcript.segments if s.text_translated) / max(len(transcript.segments), 1)
        if transcript.language != "zh" and _translated_ratio < 0.5 and not existing.get('translated'):
            await self._add_stage(stages, "translate", EpisodeStatus.LLM_RUNNING, sync_stages)
            await SubtitleProcessor().translate(
                transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "translate", p, episode_id, sync_stages),
            )
            # P1：翻译后刷新段落映射（与 _process_internal 对齐），
            # 让 en-source 段落的 text_translated 反映翻译结果。
            # resume 路径不重跑 polish——transcript.json checkpoint 已带润色文本，
            # helper 优先用 text_with_punct 即可。
            await self._generate_paragraph_mappings(episode_id, transcript)
            self._checkpoint_json(episode_id, "transcript.json", transcript.model_dump())
            await self._complete_stage(stages, "translate", completed_stages, sync_stages)

        # === 阶段 6: 高亮提取（如需要）===
        if not existing['highlight']:
            await self._add_stage(stages, "highlight", EpisodeStatus.LLM_RUNNING, sync_stages)

            # 获取标题（如果还没有）
            ep_data = await EpisodeRepository.get_by_id(episode_id)
            title = ep_data.get('title', '') if ep_data else ''

            duration_min = sum((s.end_ms - s.start_ms) for s in transcript.segments) / 1000 / 60

            highlight = await extract_highlights(
                title,
                duration_min,
                chapters,
                summaries,
                transcript,
                progress_cb=lambda p: self._update_stage_progress_sync(stages, "highlight", p, episode_id, sync_stages),
            )
            await self._complete_stage(stages, "highlight", completed_stages, sync_stages)
        else:
            logger.info(f"Highlight already exists for {episode_id}")

        # === 阶段 7: 持久化（始终执行，确保所有文件都保存）===
        await self._add_stage(stages, "done", EpisodeStatus.READY, sync_stages)

        save_episode_bundle(
            episode_id,
            self.data_dir,
            transcript=transcript,
            outline={"entries": chapters},
            summaries=summaries,
            highlight=intermediate.get('highlight') if existing.get('highlight') else None,
        )

        await self._complete_stage(stages, "done", completed_stages, sync_stages)


# 全局管道实例
from .config import DATA_DIR
pipeline = AudioProcessPipeline(DATA_DIR)
