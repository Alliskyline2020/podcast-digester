"""
阶段 6b: 专项分析 · Podcast 双路
播客内容发散且富有深度，采用 asyncio.gather 并行挖掘两种维度的信息。

特性：
- Viewpoint（观点与分歧）：提取多位嘉宾的核心主张和碰撞点
- Intel（行业情报）：提取轶事、内幕数据、对从业者的建议

适用场景：
- 多人对话播客
- 深度访谈节目
- 行业讨论节目
"""
import logging
from typing import List, Dict, Any, Optional
from ..llm import chat_json


logger = logging.getLogger(__name__)


PODCAST_VIEWPOINT_SYSTEM = """你是一个资深的播客内容分析师，擅长提取嘉宾的核心观点和分歧。

请从播客内容中提取：

1. 核心观点：每位嘉宾的主要主张或论点
2. 分歧点：嘉宾之间的意见分歧或争议
3. 共识点：嘉宾达成的共识

请标注观点归属的嘉宾（如果有明确的说话人），并用原文引用支撑。

严格输出 JSON：
{
  "viewpoints": [
    {
      "speaker": "嘉宾姓名",
      "main_argument": "核心主张",
      "supporting_quotes": ["原文引用1", "原文引用2"]
    }
  ],
  "disagreements": [
    {
      "topic": "分歧主题",
      "parties": ["甲方观点", "乙方观点"],
      "resolution": "是否达成共识"
    }
  ],
  "consensus": ["共识点1", "共识点2"]
}
"""


PODCAST_INTEL_SYSTEM = """你是一个资深的行业情报分析师，擅长从播客中提取有价值的行业信息。

请从播客内容中提取：

1. 轶事（Story）：具体的人物、事件、场景故事
2. 内幕数据（Data）：未公开的数字、比例、案例
3. 从业建议（Advice）：对行业从业者的具体建议

请确保每个条目都有具体的原文引用支撑。

严格输出 JSON：
{
  "stories": [
    {
      "title": "故事标题",
      "description": "故事描述",
      "key_people": ["人物1", "人物2"],
      "cited_segment_ids": [123, 456]
    }
  ],
  "insider_data": [
    {
      "metric": "指标名称",
      "value": "具体数值",
      "context": "背景说明",
      "cited_segment_ids": [789]
    }
  ],
  "advice": [
    {
      "target": "建议对象",
      "tip": "具体建议",
      "cited_segment_ids": [234, 567]
    }
  ]
}
"""


async def analyze_podcast_viewpoints(
    transcript_text: str,
    speaker_info: Optional[Dict[str, str]] = None,
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    提取观点与分歧

    Args:
        transcript_text: 转录文本
        speaker_info: 说话人信息 {"speaker_1": "姓名", ...}
        progress_cb: 进度回调
    """
    if progress_cb:
        progress_cb(0.5)

    context = f"\n说话人信息：\n{speaker_info}\n\n" if speaker_info else ""
    user_input = f"{context}播客内容：\n\n{transcript_text}"

    result = await chat_json(
        system=PODCAST_VIEWPOINT_SYSTEM,
        user=user_input,
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    if progress_cb:
        progress_cb(1.0)

    return result


async def analyze_podcast_insights(
    transcript_text: str,
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    提取行业情报

    Args:
        transcript_text: 转录文本
        progress_cb: 进度回调
    """
    if progress_cb:
        progress_cb(0.5)

    user_input = f"播客内容：\n\n{transcript_text}"

    result = await chat_json(
        system=PODCAST_INTEL_SYSTEM,
        user=user_input,
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    if progress_cb:
        progress_cb(1.0)

    return result


async def analyze_podcast_insights_parallel(
    transcript_text: str,
    speaker_info: Optional[Dict[str, str]] = None,
    progress_cb: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    并行提取播客的两种维度分析

    使用 asyncio.gather 并行执行 Viewpoint 和 Intel 分析
    """
    import asyncio

    async def run_viewpoint():
        return await analyze_podcast_viewpoints(transcript_text, speaker_info)

    async def run_intel():
        return await analyze_podcast_insights(transcript_text)

    results = await asyncio.gather(
        run_viewpoint(),
        run_intel(),
    )

    return {
        "viewpoints": results[0],
        "insights": results[1],
    }
