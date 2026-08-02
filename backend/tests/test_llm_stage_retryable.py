"""LLM 阶段 retryable 分类回归测试。

背景：阶段 2/2.3/2.4（章节拆分 / 语义分段 / 产品洞察）的 try/except 早期写法是
`raise RuntimeError(f"... failed: {e}")`，会把内层 chat_json 抛出的 LLMError(retryable=True)
洗成 RuntimeError——后者没有 retryable 属性，worker._handle_episode_failure 的
getattr(exc, "retryable", False) 判 False → 直接标记 failed，本可重试的瞬态错
（限流 / JSON 截断 / 网络）丢失了自动恢复能力，违背「第 N 步出问题能恢复」的核心诉求。

这些测试锁定：阶段级 except 必须原样上抛，保留异常类型与 retryable 语义。
"""
import pytest

from app.errors import LLMError
from app.models import Transcript, Segment
from app.llm_pipeline.llm_split import split_into_chapters
from app.llm_pipeline.llm_product_insights import extract_product_insights
from app.services.llm_semantic_segmenter import split_into_semantic_segments


def _transcript(n: int) -> Transcript:
    return Transcript(
        episode_id="t",
        language="zh",
        segments=[
            Segment(id=i, start_ms=i * 1000, end_ms=(i + 1) * 1000, text_original=f"第{i}句")
            for i in range(n)
        ],
    )


# ---------- 章节拆分（阶段 2）----------

@pytest.mark.asyncio
async def test_chapterize_propagates_llm_error_as_retryable(monkeypatch):
    """LLMError 必须原样上抛，retryable=True 保留给 worker 重试。"""
    async def boom(**kwargs):
        raise LLMError("rate limited", task="chapterize")

    monkeypatch.setattr("app.llm_pipeline.llm_split.chat_json", boom)

    with pytest.raises(LLMError) as exc:
        await split_into_chapters(_transcript(3))
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_chapterize_does_not_make_unclassified_retryable(monkeypatch):
    """未分类异常（如裸 401 / 逻辑 bug）不能被包成 retryable——应保持永久。"""
    async def boom_401(**kwargs):
        raise Exception("401 Unauthorized")  # 非 PodcastError，无 retryable 属性

    monkeypatch.setattr("app.llm_pipeline.llm_split.chat_json", boom_401)

    with pytest.raises(Exception) as exc:
        await split_into_chapters(_transcript(3))
    assert not getattr(exc.value, "retryable", False)


# ---------- 语义分段（阶段 2.3）----------

@pytest.mark.asyncio
async def test_semantic_segment_propagates_llm_error_as_retryable(monkeypatch):
    async def boom(**kwargs):
        raise LLMError("json truncated", task="semantic_segment")

    monkeypatch.setattr("app.services.llm_semantic_segmenter.chat_json", boom)

    segments = [
        {"id": i, "start_ms": i * 1000, "end_ms": (i + 1) * 1000, "text_original": f"句{i}"}
        for i in range(3)
    ]
    with pytest.raises(LLMError) as exc:
        await split_into_semantic_segments(segments, title="t", language="zh")
    assert exc.value.retryable is True


# ---------- 产品洞察（阶段 2.4）----------

@pytest.mark.asyncio
async def test_product_insights_propagates_llm_error_as_retryable(monkeypatch):
    async def boom(**kwargs):
        raise LLMError("context length exceeded", task="product_insights")

    monkeypatch.setattr("app.llm_pipeline.llm_product_insights.chat_json", boom)

    t = _transcript(3)
    chapters = [{"start_segment_id": 0, "end_segment_id": 2}]
    with pytest.raises(LLMError) as exc:
        await extract_product_insights(
            title="t", duration_min=1.0, chapters=chapters, summaries=[], transcript=t
        )
    assert exc.value.retryable is True
