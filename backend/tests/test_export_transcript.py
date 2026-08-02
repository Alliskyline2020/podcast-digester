"""
导出「包含完整字幕」行为测试。

覆盖 bug：导出报告勾选「包含完整字幕」时，产物里只有章节摘要、没有字幕文本。
根因是 routers/export.py 把 export_data['transcript'] 写死成 []，且
template.html 没有 transcript 渲染区块。

本测试聚焦模板渲染层（render_html_template）：给定 transcript segments，
include_transcript=True 时应渲染「完整字幕」区块和文本。
"""
import pytest

from app.export.template import render_html_template


def _bundle(segments):
    """构造最小可渲染的 episode_data。"""
    return {
        "episode": {"title": "测试节目", "title_zh": "测试节目"},
        "chapters": [],
        "summaries": [],
        "highlights": [],
        "transcript": segments,
    }


@pytest.mark.unit
class TestExportTranscript:
    def test_transcript_rendered_when_included(self):
        """include_transcript=True + 有 segments → HTML 出现完整字幕区块、文本、时间戳。"""
        data = _bundle([
            {"start_ms": 0, "text_with_punct": "你好世界"},
            {"start_ms": 65000, "text_with_punct": "第二段内容"},
        ])
        html = render_html_template(data, include_transcript=True)

        assert "<h2>完整字幕</h2>" in html
        assert "你好世界" in html
        assert "第二段内容" in html
        assert "01:05" in html  # 65000ms → 01:05

    def test_transcript_skipped_when_not_included(self):
        """include_transcript=False → 不出现完整字幕区块（即使有数据）。"""
        data = _bundle([{"start_ms": 0, "text_with_punct": "你好"}])
        html = render_html_template(data, include_transcript=False)

        # <h2>完整字幕</h2> 只在 section 渲染时出现（CSS 里不会有这个字符串）
        assert "<h2>完整字幕</h2>" not in html
        assert "你好" not in html

    def test_transcript_skipped_when_empty(self):
        """include_transcript=True 但无 segments → 不渲染空区块。"""
        data = _bundle([])
        html = render_html_template(data, include_transcript=True)

        assert "<h2>完整字幕</h2>" not in html

    def test_picks_best_text_field(self):
        """文本优先级：text_zh > text_en > text_with_punct > text_original。"""
        data = _bundle([
            # 有中文翻译 → 用翻译，不用原文
            {"start_ms": 0, "text_zh": "中文翻译", "text_original": "raw original"},
            # 无翻译、有标点版 → 用标点版
            {"start_ms": 1000, "text_with_punct": "带标点版本", "text_original": "raw"},
        ])
        html = render_html_template(data, include_transcript=True)

        assert "中文翻译" in html
        assert "raw original" not in html
        assert "带标点版本" in html

    def test_skips_segments_with_no_text(self):
        """所有文本字段都空的段 → 跳过，不渲染空行。"""
        data = _bundle([
            {"start_ms": 0, "text_with_punct": "有效段"},
            {"start_ms": 2000, "text_zh": None, "text_original": "", "text_with_punct": None},
        ])
        html = render_html_template(data, include_transcript=True)

        assert "有效段" in html
