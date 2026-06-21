"""
VTT 字幕解析器
解析 YouTube VTT 格式字幕并转换为 Transcript 模型
"""
import re
from typing import Optional
from ..models import Transcript, Segment


def parse_vtt_to_transcript(vtt_content: str, lang: str = "zh") -> Optional[Transcript]:
    """
    解析 VTT 字幕内容为 Transcript

    Args:
        vtt_content: VTT 文件内容
        lang: 字幕语言标识 (zh/en)

    Returns:
        Transcript 对象或 None
    """
    lines = vtt_content.strip().split("\n")

    segments = []
    current_cue = []
    segment_id = 0
    current_start_ms = 0
    current_end_ms = 0

    # 时间戳解析函数
    def parse_timestamp(ts: str) -> int:
        """将 VTT 时间戳 (00:00:01.500) 转换为毫秒"""
        h, m, s_ms = ts.split(":")
        s, ms = s_ms.split(".")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)

    for line in lines:
        line = line.strip()

        # 跳过空行和 VTT 头部
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:"):
            continue

        # 时间戳行
        timestamp_match = re.match(r"(\d{2}:\d{2}:\d{2}\.\d+) --> (\d{2}:\d{2}:\d{2}\.\d+)", line)
        if timestamp_match:
            if current_cue:
                # 处理上一个 cue
                text = " ".join(current_cue)
                if text and current_start_ms > 0:  # 确保有时间戳
                    segments.append(Segment(
                        id=segment_id,
                        start_ms=current_start_ms,
                        end_ms=current_end_ms,
                        text_original=text,
                    ))
                    segment_id += 1
                current_cue = []

            # 解析当前 cue 的时间戳
            current_start_ms = parse_timestamp(timestamp_match.group(1))
            current_end_ms = parse_timestamp(timestamp_match.group(2))
            continue

        # 清理内联时间戳标签
        line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d+>", "", line)
        line = re.sub(r"<c\.[^>]+>", "", line)
        line = re.sub(r"</c>", "", line)

        # 跳过重复内容标记
        if line.startswith("[重复]") or line.startswith("[音乐]") or line.startswith("[掌声]"):
            continue

        # 添加到当前 cue
        if line:
            current_cue.append(line)

    # 处理最后一个 cue
    if current_cue:
        text = " ".join(current_cue)
        if text and current_start_ms > 0:
            segments.append(Segment(
                id=segment_id,
                start_ms=current_start_ms,
                end_ms=current_end_ms,
                text_original=text,
            ))

    if not segments:
        return None

    return Transcript(
        episode_id="",  # 需要在调用时设置
        language=lang,  # 使用传入的语言参数
        segments=segments,
    )
