"""
阶段 2: 章节拆分
将长文本的 ASR 转录结果按照语义逻辑（而非固定时长）切割成 3-8 个连贯的章节。

特性：
- 滑动窗口合并（Sliding Window Merge）：相邻 Chunk 保留 15 个 Segment 重叠区
- 分块策略：超过 8000 tokens 时按时间线切块，Map-Reduce 合并
- JSON 约束：使用 response_format 强制 LLM 输出结构化数组
"""
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from pydantic import BaseModel

from ..llm import chat_json
from ..prompts import CHAPTERIZE_SYSTEM, build_chapterize_user


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..models import Transcript


class Chapter(BaseModel):
    """章节模型"""
    title_zh: str
    start_segment_id: int
    end_segment_id: int
    start_ms: int = 0
    end_ms: int = 0
    estimated_duration_min: Optional[float] = None


async def split_into_chapters(
    transcript: "Transcript",
    max_tokens: int = 8000,
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    将转录文本按语义逻辑切割成章节

    Args:
        transcript: Transcript 对象，包含所有 segments
        max_tokens: 单次处理的最大 token 数（用于决定是否分块）
        progress_cb: 进度回调函数

    Returns:
        章节列表 [{"title_zh": "...", "start_segment_id": 0, "end_segment_id": 120}, ...]
    """
    segments = transcript.segments
    n_segments = len(segments)
    total_duration_min = sum(
        (s.end_ms - s.start_ms) for s in segments
    ) / 1000 / 60

    logger.info(f"Starting chapter split: {n_segments} segments, {total_duration_min:.1f} min")

    # 判断是否需要分块处理
    if n_segments > 800:
        return await _split_with_windowing(
            transcript.title if hasattr(transcript, 'title') else "Unknown",
            transcript.language,
            segments,
            progress_cb,
        )

    # 单次处理模式
    if progress_cb:
        progress_cb(0.0)

    transcript_block = _build_transcript_block(segments)
    user_input = build_chapterize_user(
        transcript.title if hasattr(transcript, 'title') else "Unknown",
        transcript.language,
        n_segments,
        total_duration_min,
        transcript_block,
    )

    try:
        result = await chat_json(
            system=CHAPTERIZE_SYSTEM,
            user=user_input,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        chapters = result.get("chapters", [])

        # 添加时间戳信息
        for ch in chapters:
            start_id = ch["start_segment_id"]
            end_id = ch["end_segment_id"]
            if start_id < len(segments):
                ch["start_ms"] = segments[start_id].start_ms
            if end_id < len(segments):
                ch["end_ms"] = segments[end_id].end_ms

        logger.info(f"Chapter split completed: {len(chapters)} chapters")

        if progress_cb:
            progress_cb(1.0)

        return chapters

    except Exception as e:
        logger.error(f"Chapter split failed: {e}")
        raise RuntimeError(f"Chapter split failed: {e}")


async def _split_with_windowing(
    title: str,
    language: str,
    segments: List,
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    窗口模式分块处理（Map-Reduce）

    - 按 800 段切分窗口
    - 相邻窗口保留 15 段重叠区
    - 并行处理各窗口
    - 合并相似章节
    """
    from ..config import LLM_SPLIT_WINDOW_SIZE
    window_size = LLM_SPLIT_WINDOW_SIZE
    overlap = 15  # 滑动窗口重叠区

    windows = []
    for i in range(0, len(segments), window_size - overlap):
        window_segments = segments[i:i + window_size]
        windows.append((i, window_segments))

    logger.info(f"Using window mode: {len(windows)} windows")

    async def process_window(offset: int, segs: List) -> List[Dict]:
        """处理单个窗口"""
        block = _build_transcript_block(segs, max_segments=len(segs))
        duration_min = sum((s.end_ms - s.start_ms) for s in segs) / 1000 / 60

        user_input = build_chapterize_user(
            f"{title} (part {offset // (window_size - overlap) + 1})",
            language,
            len(segs),
            duration_min,
            block,
        )

        result = await chat_json(
            system=CHAPTERIZE_SYSTEM,
            user=user_input,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        return result.get("chapters", [])

    # 并行处理所有窗口
    import asyncio
    results = await asyncio.gather(*[
        process_window(offset, segs) for offset, segs in windows
    ])

    if progress_cb:
        progress_cb(0.8)

    # 合并窗口结果
    all_chapters = []
    for window_chapters in results:
        all_chapters.extend(window_chapters)

    # 为所有章节添加时间戳信息
    for ch in all_chapters:
        start_id = ch["start_segment_id"]
        end_id = ch["end_segment_id"]
        if start_id < len(segments):
            ch["start_ms"] = segments[start_id].start_ms
        if end_id < len(segments):
            ch["end_ms"] = segments[end_id].end_ms

    # 去重合并相邻的相似章节
    merged_chapters = _merge_adjacent_chapters(all_chapters)

    logger.info(f"Window merge completed: {len(merged_chapters)} chapters")

    if progress_cb:
        progress_cb(1.0)

    return merged_chapters


def _merge_adjacent_chapters(chapters: List[Dict]) -> List[Dict]:
    """
    合并相邻的同主题章节

    判断标准：章节标题共享超过 3 个字符则视为相似主题
    """
    if not chapters:
        return []

    merged = [chapters[0]]
    for ch in chapters[1:]:
        last = merged[-1]
        if _topics_similar(last.get("title_zh", ""), ch.get("title_zh", "")):
            # 合并：扩展最后一个章节的结束边界
            last["end_segment_id"] = ch["end_segment_id"]
            last["end_ms"] = ch.get("end_ms", last.get("end_ms", 0))
        else:
            merged.append(ch)

    return merged


def _topics_similar(title1: str, title2: str) -> bool:
    """
    判断两个标题主题是否相似

    相似标准：共享超过 3 个字符
    """
    words1 = set(title1)
    words2 = set(title2)
    return len(words1 & words2) > 3


def _build_transcript_block(segments: List, max_segments: Optional[int] = None) -> str:
    """构建紧凑格式的字幕块"""
    lines = []
    for seg in segments[:max_segments]:
        lines.append(f"{seg.id} | {seg.start_ms//1000//60:02d}:{seg.start_ms//1000%60:02d} | {seg.text_translated or seg.text_original}")
    return "\n".join(lines)
