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

Legacy 兼容层 (legacy.py):
- run_llm_pipeline: 供 task_recovery.py 使用的遗留接口
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
# Legacy compatibility for task_recovery.py
from .legacy import run_llm_pipeline

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
    # Legacy
    "run_llm_pipeline",
]
