"""
基于LLM的语义分段服务

复用分章节逻辑，将长文本按照语义完整性切分成适合阅读的段落。
"""
import logging
from typing import List, Dict, Any, Optional
from ..llm import chat_json
from app.utils import clean_llm_text

logger = logging.getLogger(__name__)


SEMANTIC_SEGMENT_SYSTEM = """你是一个资深的播客内容编辑。给定一段播客的逐句字幕（每句带 id 和时间戳），你需要把它划分为适合阅读的语义段落。

要求：
1. 每个段落表达一个完整的意思或观点，100-300字为宜
2. 段落按照语义完整性划分，而非机械的字数或时间切割
3. 识别话题转变、对话结构、自然停顿作为分段边界
4. 段落边界对齐到segment id（不要跨段切分）
5. 保留说话人信息和重要引用
6. 严格输出 JSON 对象，格式如下：
{
  "segments": [
    {"start_segment_id": 0, "end_segment_id": 12, "reasoning": "这是开场白，属于完整的话题引入"},
    {"start_segment_id": 13, "end_segment_id": 35, "reasoning": "嘉宾开始分享背景故事"},
    ...
  ]
}

end_segment_id 是该段落最后一段的 id（包含）。段落必须连续覆盖整个 transcript，
第一个段落 start_segment_id=0，最后一个段落 end_segment_id 等于最后一段的 id。

reasoning 简要说明为什么这样分段（用于调试和验证）。"""


def build_semantic_segment_user(
    title: str,
    language: str,
    n_segments: int,
    duration_min: float,
    transcript_block: str
) -> str:
    """构建语义分段用户输入"""
    return f"""节目标题：{title}
语言：{language}
段落数：{n_segments}
总时长：{duration_min} 分钟

字幕（id | 时间戳 | 原文）：
{transcript_block}

请按照语义完整性划分为适合阅读的段落（100-300字/段），输出 JSON。"""


async def split_into_semantic_segments(
    segments: List[Dict[str, Any]],
    title: str = "Unknown",
    language: str = "zh",
    batch_size: int = 800,
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    将字幕segments按语义完整性切分成段落

    Args:
        segments: 原始字幕segments列表，每个包含 id, start_ms, end_ms, text_original
        title: 节目标题
        language: 语言
        batch_size: 每批处理的segment数量（超过token限制时分批）
        progress_cb: 进度回调函数

    Returns:
        语义段落列表，每个包含：
        - start_segment_id: int (起始segment ID)
        - end_segment_id: int (结束segment ID)
        - start_ms: int (开始时间)
        - end_ms: int (结束时间)
        - text_original: str (原文拼接)
        - text_clean: str (清洗后的文本)
        - reasoning: str (分段原因)
        - segment_ids: List[str] (包含的segment ID列表)
    """
    if not segments:
        return []

    n_segments = len(segments)
    total_duration_min = sum(
        (s.get("end_ms", 0) - s.get("start_ms", 0)) for s in segments
    ) / 1000 / 60

    logger.info(f"Starting semantic segmentation: {n_segments} segments, {total_duration_min:.1f} min")

    # 判断是否需要分批处理
    # 使用更小的批次确保完整覆盖
    effective_batch_size = 400  # 每批400个segments，确保完整覆盖
    if n_segments > effective_batch_size:
        return await _split_with_batches(
            segments, title, language, effective_batch_size, progress_cb
        )

    # 单批处理
    if progress_cb:
        progress_cb(0.0)

    transcript_block = _build_transcript_block(segments)
    user_input = build_semantic_segment_user(
        title, language, n_segments, total_duration_min, transcript_block
    )

    try:
        result = await chat_json(
            system=SEMANTIC_SEGMENT_SYSTEM,
            user=user_input,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        semantic_segments = result.get("segments", [])

        # 转换为最终格式
        final_segments = []
        for seg in semantic_segments:
            start_id = seg["start_segment_id"]
            end_id = seg["end_segment_id"]

            if start_id >= len(segments) or end_id >= len(segments):
                logger.warning(f"Invalid segment range: {start_id}-{end_id}, total: {len(segments)}")
                continue

            # 提取对应的原始segments
            raw_segments = segments[start_id:end_id + 1]

            # 拼接文本
            text_original = " ".join([s.get("text_original", "") for s in raw_segments])
            text_clean = _clean_text(text_original)

            final_segments.append({
                "start_segment_id": start_id,
                "end_segment_id": end_id,
                "start_ms": raw_segments[0].get("start_ms", 0),
                "end_ms": raw_segments[-1].get("end_ms", 0),
                "text_original": text_original,
                "text_clean": text_clean,
                "reasoning": seg.get("reasoning", ""),
                "segment_ids": [s.get("id", "") for s in raw_segments],
                "segment_indices": list(range(start_id, end_id + 1))
            })

        logger.info(f"Semantic segmentation completed: {len(final_segments)} paragraphs")

        if progress_cb:
            progress_cb(1.0)

        return final_segments

    except Exception as e:
        logger.error(f"Semantic segmentation failed: {e}")
        raise RuntimeError(f"Semantic segmentation failed: {e}")


async def _split_with_batches(
    segments: List[Dict[str, Any]],
    title: str,
    language: str,
    batch_size: int,
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    分批处理长文本（无重叠连续批次）

    - 按 batch_size 切分连续窗口（无重叠）
    - 串行处理各批次（避免并发问题）
    - 验证每个批次完全覆盖
    - 简单拼接结果
    """
    # 计算批次数
    n_batches = (len(segments) + batch_size - 1) // batch_size
    logger.info(f"Using batch mode: {n_batches} batches, {batch_size} segments each")

    all_final_segments = []

    # 串行处理每个批次
    for batch_idx in range(n_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(segments))
        batch_segments = segments[start_idx:end_idx]

        logger.info(f"Processing batch {batch_idx + 1}/{n_batches} (segments {start_idx}-{end_idx - 1})")

        # 处理单个批次
        block = _build_transcript_block(batch_segments)
        duration_min = sum(
            (s.get("end_ms", 0) - s.get("start_ms", 0)) for s in batch_segments
        ) / 1000 / 60

        user_input = build_semantic_segment_user(
            f"{title} (part {batch_idx + 1}/{n_batches})",
            language,
            len(batch_segments),
            duration_min,
            block,
        )

        try:
            result = await chat_json(
                system=SEMANTIC_SEGMENT_SYSTEM,
                user=user_input,
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            batch_segments_result = result.get("segments", [])

            # 转换并验证每个批次的结果
            batch_covered = set()
            for seg in batch_segments_result:
                local_start = seg["start_segment_id"]
                local_end = seg["end_segment_id"]

                # 调整为全局ID
                global_start = start_idx + local_start
                global_end = start_idx + local_end

                if global_start >= len(segments) or global_end >= len(segments):
                    logger.warning(f"Invalid segment range: {global_start}-{global_end}, skipping")
                    continue

                # 记录已覆盖的segments
                batch_covered.update(range(local_start, local_end + 1))

                # 提取对应的原始segments
                raw_segments = segments[global_start:global_end + 1]
                text_original = " ".join([s.get("text_original", "") for s in raw_segments])
                text_clean = _clean_text(text_original)

                all_final_segments.append({
                    "start_segment_id": global_start,
                    "end_segment_id": global_end,
                    "start_ms": raw_segments[0].get("start_ms", 0),
                    "end_ms": raw_segments[-1].get("end_ms", 0),
                    "text_original": text_original,
                    "text_clean": text_clean,
                    "reasoning": seg.get("reasoning", ""),
                    "segment_ids": [s.get("id", "") for s in raw_segments],
                    "segment_indices": list(range(global_start, global_end + 1))
                })

            # 检查是否完全覆盖，如有遗漏则补充
            expected_covered = set(range(0, len(batch_segments)))
            missing = expected_covered - batch_covered

            if missing:
                logger.warning(f"Batch {batch_idx + 1}: LLM missed {len(missing)} segments, adding fallback segments")

                # 按顺序补充缺失的segments
                missing_list = sorted(missing)
                i = 0
                while i < len(missing_list):
                    # 将连续的缺失segments合并成一段
                    j = i
                    while j + 1 < len(missing_list) and missing_list[j + 1] == missing_list[j] + 1:
                        j += 1

                    # 创建fallback段落
                    fallback_local_start = missing_list[i]
                    fallback_local_end = missing_list[j]

                    raw_segments = batch_segments[fallback_local_start:fallback_local_end + 1]
                    text_original = " ".join([s.get("text_original", "") for s in raw_segments])
                    text_clean = _clean_text(text_original)

                    all_final_segments.append({
                        "start_segment_id": start_idx + fallback_local_start,
                        "end_segment_id": start_idx + fallback_local_end,
                        "start_ms": raw_segments[0].get("start_ms", 0),
                        "end_ms": raw_segments[-1].get("end_ms", 0),
                        "text_original": text_original,
                        "text_clean": text_clean,
                        "reasoning": "Auto-filled: LLM missed these segments",
                        "segment_ids": [s.get("id", "") for s in raw_segments],
                        "segment_indices": list(range(start_idx + fallback_local_start, start_idx + fallback_local_end + 1))
                    })

                    i = j + 1

            logger.info(f"Batch {batch_idx + 1} completed: {len(batch_segments_result)} LLM paragraphs + {len(missing) if missing else 0} fallback segments")

        except Exception as e:
            logger.error(f"Batch {batch_idx + 1} failed: {e}")
            # 如果批次失败，使用简单分段作为fallback
            for i in range(start_idx, end_idx, 50):  # 每50个segments一段
                fallback_end = min(i + 50, end_idx) - 1
                raw_segments = segments[i:fallback_end + 1]
                text_original = " ".join([s.get("text_original", "") for s in raw_segments])
                text_clean = _clean_text(text_original)

                all_final_segments.append({
                    "start_segment_id": i,
                    "end_segment_id": fallback_end,
                    "start_ms": raw_segments[0].get("start_ms", 0),
                    "end_ms": raw_segments[-1].get("end_ms", 0),
                    "text_original": text_original,
                    "text_clean": text_clean,
                    "reasoning": "Fallback due to LLM error",
                    "segment_ids": [s.get("id", "") for s in raw_segments],
                    "segment_indices": list(range(i, fallback_end + 1))
                })

        if progress_cb:
            progress = (batch_idx + 1) / n_batches * 0.9
            progress_cb(progress)

    logger.info(f"Batch processing completed: {len(all_final_segments)} paragraphs")

    if progress_cb:
        progress_cb(1.0)

    return all_final_segments


def _merge_adjacent_segments(segments: List[Dict]) -> List[Dict]:
    """
    合并相邻的重复段落（由窗口重叠导致）

    判断标准：如果两个段落的内容高度重叠，则只保留一个
    """
    if not segments:
        return []

    merged = [segments[0]]
    for seg in segments[1:]:
        last = merged[-1]
        # 如果新段落的起始在最后一个段落的中间，说明是重叠
        if seg["start_segment_id"] <= last["end_segment_id"]:
            # 跳过这个重复段落
            continue
        merged.append(seg)

    return merged


def _build_transcript_block(segments: List[Dict]) -> str:
    """构建紧凑格式的字幕块"""
    lines = []
    for seg in segments:
        seg_id = seg.get("id", "")
        start_ms = seg.get("start_ms", 0)
        text = seg.get("text_original", "")

        # 格式: id | MM:SS | 原文
        time_str = f"{start_ms//1000//60:02d}:{start_ms//1000%60:02d}"
        lines.append(f"{seg_id} | {time_str} | {text}")

    return "\n".join(lines)


def _clean_text(text: str) -> str:
    """
    清洗文本

    - 解码HTML实体
    - 移除HTML标签
    - 移除特殊符号
    - 清理多余空格
    """
    if not text:
        return ""

    # 使用集中的文本清洗工具（激进模式 + 移除特殊符号）
    return clean_llm_text(text)
