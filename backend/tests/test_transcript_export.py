"""导出字幕装配 + 模板渲染集成测试。

覆盖:
- build_transcript_export: 从 transcript_data / paragraph_mappings / highlights
  装配出模板可用的字幕段落列表(包含重点加粗标记)。
- render_html_template: include_transcript=True 时渲染完整字幕版块,
  亮点段落文本被加粗(<strong>)。
"""
from types import SimpleNamespace

from app.export.transcript_section import build_transcript_export
from app.export.template import render_html_template


def _hl(cited):
    """构造类 HighlightItem 的轻量对象(带 cited_segment_ids 属性)。"""
    return SimpleNamespace(kind="insight", text_zh="亮点摘要", why_zh="原因",
                           cited_segment_ids=cited, start_ms=None)


def test_build_transcript_export_disabled_returns_empty():
    segs = [{"id": 0, "start_ms": 0, "text_with_punct": "内容。"}]
    out = build_transcript_export(
        {"segments": segs}, [{"segment_indices": [0], "start_ms": 0}], [],
        include_transcript=False,
    )
    assert out == []


def test_build_transcript_export_no_segments_returns_empty():
    out = build_transcript_export({"segments": []}, None, [], include_transcript=True)
    assert out == []


def test_build_transcript_export_collects_highlighted_ids_from_objects():
    transcript_data = {
        "segments": [
            {"id": 0, "start_ms": 0, "text_with_punct": "普通句。"},
            {"id": 1, "start_ms": 1000, "text_with_punct": "亮点原话。"},
        ]
    }
    pm = [{"segment_indices": [0, 1], "start_ms": 0}]
    highlights = [_hl([1])]
    out = build_transcript_export(transcript_data, pm, highlights, include_transcript=True)
    assert len(out) == 1
    flags = [s["highlight"] for s in out[0]["segments"]]
    assert flags == [False, True]
    assert out[0]["has_highlight"] is True


def test_build_transcript_export_accepts_dict_highlights():
    transcript_data = {"segments": [
        {"id": 0, "start_ms": 0, "text_with_punct": "亮点。"},
    ]}
    pm = [{"segment_indices": [0], "start_ms": 0}]
    highlights = [{"cited_segment_ids": [0]}]  # dict 形式
    out = build_transcript_export(transcript_data, pm, highlights, include_transcript=True)
    assert out[0]["segments"][0]["highlight"] is True


def test_build_transcript_export_handles_none_inputs():
    out = build_transcript_export(None, None, None, include_transcript=True)
    assert out == []


def test_template_renders_transcript_section_with_bold_highlights():
    """include_transcript=True 时, 模板应渲染完整字幕版块, 亮点段加粗。"""
    transcript = [
        {
            "start_time": "00:00",
            "has_highlight": True,
            "segments": [
                {"text": "普通的一句字幕。", "highlight": False},
                {"text": "这是值得加粗的亮点原话。", "highlight": True},
            ],
        }
    ]
    html = render_html_template(
        {"episode": {"title": "测试", "title_zh": "测试"}, "transcript": transcript},
        theme="light",
        include_transcript=True,
    )
    # 版块标题存在
    assert "完整字幕" in html or "原文字幕" in html
    # 亮点文本被渲染且加粗(<strong> 或 <b>)
    assert "这是值得加粗的亮点原话。" in html
    assert "<strong>" in html or 'class="hl-sentence"' in html
    # 普通文本也渲染
    assert "普通的一句字幕。" in html


def test_template_omits_transcript_section_when_disabled():
    html = render_html_template(
        {"episode": {"title": "测试", "title_zh": "测试"}, "transcript": []},
        theme="light",
        include_transcript=False,
    )
    assert "完整字幕" not in html and "原文字幕" not in html
