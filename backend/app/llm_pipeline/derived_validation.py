"""Write-side validation for LLM-generated derived data (chapters / summaries).

架构修复（systematic-debugging 根因层）：pipeline 旧设计把 LLM 产出的原始 dict 不经
校验就落盘(outline.json / summaries.json) + 入库(OutlineRepository / SummariesRepository)，
只在 LOAD 时用 all-or-nothing 列表推导 ``[OutlineEntry(**e) for e in entries]`` 对 Pydantic
模型做校验。后果：单条坏数据(末章 end_ms 缺失、summary content_zh <50 字、key_points <2 项)
会**静默进存储**，加载时再把**整组** outline / summaries 砸成 None —— 前端章节列表 +
章内 bullets 全空（用户可见的「DB 数据是空的」）。

修法：在**生成边界**(split_into_chapters / generate_chapter_summaries 返回前)就按模型校验、
丢掉坏条目(并落 warning)、回填 index、返回 model-conformant 的 ``.model_dump()`` dict。
这样 file(json.dump) 与 DB(json.dumps) 落盘的内容永远可被 loader 直接重构，从源头消除
fail-late / fail-big。loader 侧的 skip-and-warn(episode_loader._build_summaries / outline
兜底)保留，作为对历史数据 / 异常输入的读侧防御。

设计要点：
- 不就地改入参 dict（pipeline 可能复用原始结构）；用 {**ch} 浅拷贝后回填 index。
- index 由本函数负责回填与连续重排——解耦「index 注入」与「校验」的调用顺序，避免
  缺 index 时把整组全丢(那正是要消除的 fail-big)。
- 丢条目只 warn 不抛：单条坏数据不得让整集 LLM 工作白费。
"""
import logging
from typing import Any, List

from ..models import ChapterSummary, OutlineEntry

logger = logging.getLogger(__name__)


def validate_chapters(chapters: List[dict]) -> List[dict]:
    """按 OutlineEntry 校验章节 dict，丢弃非法条目，返回 model-conformant dict 列表。

    - 缺 index 则按位置回填；丢弃后 index 连续重排为 0..n-1。
    - 不就地修改入参。
    - 返回的 dict 即 OutlineEntry.model_dump()，可直接 json 序列化落盘/入库。
    """
    built: List[dict] = []
    for position, ch in enumerate(chapters):
        candidate = {**ch}
        candidate.setdefault("index", position)
        try:
            built.append(OutlineEntry(**candidate).model_dump())
        except Exception as err:  # noqa: BLE001 — 单坏条目不得砸掉整组
            logger.warning(
                f"[Validate] 跳过非法 chapter "
                f"(title={ch.get('title_zh')!r}, index={ch.get('index')!r}): {err}"
            )
    # 丢弃后重排为连续 index（前端按 index 排序；空洞无害但连续更可调试）
    for i, ch in enumerate(built):
        ch["index"] = i
    return built


def validate_summaries(summaries: List[dict]) -> List[dict]:
    """按 ChapterSummary 校验摘要 dict，丢弃非法条目，返回 model-conformant dict 列表。

    ChapterSummary 比 OutlineEntry 更严(content_zh min_length=50、key_points_zh
    min_items=2)，LLM 偶发产出短摘要/少要点时这里丢弃，避免入库后在 load 处炸整组。
    """
    built: List[dict] = []
    for s in summaries:
        try:
            built.append(ChapterSummary(**s).model_dump())
        except Exception as err:  # noqa: BLE001 — 单坏条目不得砸掉整组
            logger.warning(
                f"[Validate] 跳过非法 summary "
                f"(chapter_id={s.get('chapter_id')!r}): {err}"
            )
    return built


__all__ = ["validate_chapters", "validate_summaries"]
