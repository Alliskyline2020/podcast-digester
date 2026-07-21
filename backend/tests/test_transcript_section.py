"""transcript_section 纯函数单测: 导出字幕的段落分组 + 重点加粗。"""
from app.export.transcript_section import build_transcript_paragraphs


def _seg(i, text_with_punct=None, text_original=None, start_ms=0):
    return {
        "id": i,
        "start_ms": start_ms,
        "end_ms": start_ms + 5000,
        "text_with_punct": text_with_punct,
        "text_original": text_original,
    }


def test_groups_segments_by_paragraph_indices():
    segments = [
        _seg(0, text_with_punct="第一句。", text_original="第一句", start_ms=0),
        _seg(1, text_with_punct="第二句。", text_original="第二句", start_ms=5000),
        _seg(2, text_with_punct="第三句。", text_original="第三句", start_ms=10000),
    ]
    pm = [
        {"segment_indices": [0, 1], "start_ms": 0},
        {"segment_indices": [2], "start_ms": 10000},
    ]
    paras = build_transcript_paragraphs(segments, pm, highlighted_ids=set())
    assert len(paras) == 2
    assert paras[0]["start_time"] == "00:00"
    assert [s["text"] for s in paras[0]["segments"]] == ["第一句。", "第二句。"]
    assert paras[1]["start_time"] == "00:10"


def test_uses_text_with_punct_falls_back_to_original():
    segments = [
        _seg(0, text_with_punct=None, text_original="原始无标点", start_ms=0),
    ]
    paras = build_transcript_paragraphs(segments, [{"segment_indices": [0], "start_ms": 0}], set())
    assert paras[0]["segments"][0]["text"] == "原始无标点"


def test_marks_highlighted_segments():
    segments = [
        _seg(0, text_with_punct="普通句。", start_ms=0),
        _seg(1, text_with_punct="亮点原话。", start_ms=1000),
        _seg(2, text_with_punct="另一亮点。", start_ms=2000),
    ]
    pm = [{"segment_indices": [0, 1, 2], "start_ms": 0}]
    paras = build_transcript_paragraphs(segments, pm, highlighted_ids={1, 2})
    flags = [s["highlight"] for s in paras[0]["segments"]]
    assert flags == [False, True, True]
    assert paras[0]["has_highlight"] is True


def test_paragraph_without_highlights_has_has_highlight_false():
    segments = [_seg(0, text_with_punct="普通。", start_ms=0)]
    paras = build_transcript_paragraphs(segments, [{"segment_indices": [0], "start_ms": 0}], {99})
    assert paras[0]["has_highlight"] is False


def test_skips_empty_text_segments():
    segments = [
        _seg(0, text_with_punct="有内容。", start_ms=0),
        _seg(1, text_with_punct="   ", text_original="", start_ms=1000),  # 空
        _seg(2, text_with_punct="也行。", start_ms=2000),
    ]
    pm = [{"segment_indices": [0, 1, 2], "start_ms": 0}]
    paras = build_transcript_paragraphs(segments, pm, set())
    assert len(paras[0]["segments"]) == 2  # 空段被剔除


def test_fallback_flat_chunking_when_no_paragraph_mappings():
    # paragraph_mappings=None → 按字符预算把扁平段切成段落
    # 每段 ~90 字, 8 段共 ~720 字 > TRANSCRIPT_FALLBACK_CHARS → 应切成多段
    long = "今天我们来聊一个非常有意思的话题，关于人工智能在内容创作领域的最新进展以及它对未来创作者工作流的深远影响，这一点值得深入探讨。"
    segments = [_seg(i, text_with_punct=long, start_ms=i * 1000) for i in range(8)]
    paras = build_transcript_paragraphs(segments, None, set())
    assert len(paras) >= 2  # 被切成多段
    # 全部段都被覆盖
    all_texts = [s["text"] for p in paras for s in p["segments"]]
    assert len(all_texts) == 8


def test_empty_segments_returns_empty():
    assert build_transcript_paragraphs([], None, set()) == []
    assert build_transcript_paragraphs([], [{"segment_indices": [0]}], set()) == []


def test_highlighted_ids_accepts_list_or_set():
    segments = [_seg(0, text_with_punct="亮点。", start_ms=0)]
    # 传 list 也应工作
    paras = build_transcript_paragraphs(segments, [{"segment_indices": [0], "start_ms": 0}], [0])
    assert paras[0]["segments"][0]["highlight"] is True
