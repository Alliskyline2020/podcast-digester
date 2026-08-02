"""
LLM 管道编排 - 模块化处理管道

按照 7 阶段架构设计：
1. 音频下载 + ASR 转录
2. 章节拆分 (llm_split.py)
3. 章节摘要 (llm_summary.py)
4. 文本翻译 (llm_translate.py)
5. 高亮提取 (llm_highlight.py)
6a. 发布会专项 (llm_launch_analyze.py)
6b. 播客专项 (llm_podcast_analyze.py)
7. 持久化与状态移交 (storage.py)

注：旧的 legacy.py（run_llm_pipeline）已随 task_recovery.py 一并移除——任务恢复
改由 worker 单 owner 在 poll 中经 pipeline.resume_episode 按 checkpoint 续点，
不再需要 LLM-only 的遗留恢复路径。
"""

from .llm_split import split_into_chapters
from .llm_summary import generate_chapter_summaries, generate_chapter_summary
from .llm_translate import translate_segments, apply_translations
from .llm_highlight import extract_highlights
from .llm_launch_analyze import (
    analyze_launch_specs,
    analyze_launch_product_insight,
    analyze_launch_marketing,
)
from .llm_podcast_analyze import (
    analyze_podcast_viewpoints,
    analyze_podcast_insights,
    analyze_podcast_insights_parallel,
)

__all__ = [
    "split_into_chapters",
    "generate_chapter_summaries",
    "generate_chapter_summary",
    "translate_segments",
    "apply_translations",
    "extract_highlights",
    "analyze_launch_specs",
    "analyze_launch_product_insight",
    "analyze_launch_marketing",
    "analyze_podcast_viewpoints",
    "analyze_podcast_insights",
    "analyze_podcast_insights_parallel",
]
