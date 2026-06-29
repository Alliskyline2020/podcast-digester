"""SubtitleProcessor 单元测试(LLM 全部 mock)。"""
import pytest
from app.models import Segment, Transcript
from app.services.subtitle_processor import SubtitleProcessor


def _seg(i, text, translated=None):
    return Segment(id=i, start_ms=i * 1000, end_ms=i * 1000 + 999,
                   text_original=text, text_translated=translated)


def _transcript(lang, segs):
    return Transcript(episode_id="ep_test", language=lang, segments=segs)


@pytest.mark.asyncio
async def test_polish_accepts_clean_punctuation(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "我觉得，这个浏览器很好用。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "我觉得这个浏览器很好用")])
    n = await SubtitleProcessor().polish(t)
    assert n == 1
    assert t.segments[0].text_with_punct == "我觉得，这个浏览器很好用。"


@pytest.mark.asyncio
async def test_polish_falls_back_on_drift(monkeypatch):
    # LLM 返回邻段内容(drift) → semantic_ok False → 回退原文
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "Craigslist 和 BAT 是新媒介的代表。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "维护成本和移动端的商业模式")])
    n = await SubtitleProcessor().polish(t)
    assert n == 0  # 没有任何句被接受
    assert t.segments[0].text_with_punct == "维护成本和移动端的商业模式"  # 回退原文


@pytest.mark.asyncio
async def test_polish_falls_back_when_llm_missing_id(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": []}  # LLM 漏返
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "这是一个测试")])
    await SubtitleProcessor().polish(t)
    assert t.segments[0].text_with_punct == "这是一个测试"  # 回退, 非空


@pytest.mark.asyncio
async def test_polish_falls_back_on_llm_exception(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        raise RuntimeError("api down")
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    t = _transcript("zh", [_seg(0, "这是一个测试"), _seg(1, "第二句话")])
    await SubtitleProcessor().polish(t)  # 不抛异常
    assert t.segments[0].text_with_punct == "这是一个测试"
    assert t.segments[1].text_with_punct == "第二句话"


@pytest.mark.asyncio
async def test_polish_preserves_timestamps_and_original(monkeypatch):
    async def fake_chat_json(system, user, **kw):
        return {"polished": [{"id": 0, "text": "这是测试。"}]}
    monkeypatch.setattr("app.services.subtitle_processor.chat_json", fake_chat_json)

    seg = _seg(0, "这是测试")
    t = _transcript("zh", [seg])
    snap = SubtitleProcessor()._snapshot(t)
    await SubtitleProcessor().polish(t)
    SubtitleProcessor()._assert_immutability(snap, t)  # 不抛 = 通过
    # text_with_punct 非空, 但 id/start_ms/end_ms/text_original 未变
    assert (seg.id, seg.start_ms, seg.end_ms, seg.text_original) == snap[0]


@pytest.mark.asyncio
async def test_translate_skips_zh(monkeypatch):
    called = []
    async def fake_translate(transcript, progress_cb=None):
        called.append(1)
        return []
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("zh", [_seg(0, "中文")])
    n = await SubtitleProcessor().translate(t)
    assert n == 0
    assert called == []  # ZH 不调 translate_segments


@pytest.mark.asyncio
async def test_translate_writes_all_segments(monkeypatch):
    async def fake_translate(transcript, progress_cb=None):
        return [{"id": 0, "text_zh": "这是中文0"}, {"id": 1, "text_zh": "这是中文1"}]
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("en", [_seg(0, "english zero"), _seg(1, "english one")])
    n = await SubtitleProcessor().translate(t)
    assert n == 2
    assert t.segments[0].text_translated == "这是中文0"
    assert t.segments[1].text_translated == "这是中文1"


@pytest.mark.asyncio
async def test_translate_fills_gaps_with_original(monkeypatch):
    # translate_segments 漏掉 id=1 → 不丢段, 用原文兜底
    async def fake_translate(transcript, progress_cb=None):
        return [{"id": 0, "text_zh": "这是中文0"}]
    monkeypatch.setattr("app.services.subtitle_processor.translate_segments", fake_translate)

    t = _transcript("en", [_seg(0, "english zero"), _seg(1, "english one")])
    n = await SubtitleProcessor().translate(t)
    assert n == 1
    assert t.segments[0].text_translated == "这是中文0"
    assert t.segments[1].text_translated == "english one"  # 原文兜底, 非空
