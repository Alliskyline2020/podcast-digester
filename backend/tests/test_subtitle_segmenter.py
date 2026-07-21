"""
字幕分段映射测试

测试 Episode 模型支持存储段落映射关系
"""
import pytest
from datetime import datetime
from app.database import EpisodeRepository
from app.models import Episode, EpisodeStatus


@pytest.mark.asyncio
async def test_episode_has_paragraph_mappings(temp_db) -> None:
    """测试 Episode 模型支持存储段落映射"""
    # Arrange
    episode_data = {
        "id": "test_ep_001",
        "title": "Test Episode",
        "status": EpisodeStatus.READY.value,
        "language": "en",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    # Act
    await EpisodeRepository.create(episode_data)
    retrieved = await EpisodeRepository.get_by_id("test_ep_001")

    # Assert - paragraph_mappings field should exist and default to None
    assert retrieved is not None
    assert "paragraph_mappings" in retrieved, "paragraph_mappings field should exist in database"
    assert retrieved["paragraph_mappings"] is None, "paragraph_mappings should default to None"


@pytest.mark.asyncio
async def test_episode_can_store_paragraph_mappings(temp_db) -> None:
    """测试 Episode 可以存储和检索段落映射数据"""
    # Arrange
    paragraph_mappings = [
        {
            "id": 0,
            "start_ms": 0,
            "end_ms": 15000,
            "text_original": "This is paragraph one",
            "text_translated": "这是第一段",
            "segment_indices": [0, 1, 2],
            "segment_ids": ["seg_001", "seg_002", "seg_003"]
        },
        {
            "id": 1,
            "start_ms": 15000,
            "end_ms": 30000,
            "text_original": "This is paragraph two",
            "text_translated": "这是第二段",
            "segment_indices": [3, 4, 5],
            "segment_ids": ["seg_004", "seg_005", "seg_006"]
        }
    ]

    episode_data = {
        "id": "test_ep_002",
        "title": "Test Episode with Mappings",
        "status": EpisodeStatus.READY.value,
        "language": "en",
        "paragraph_mappings": paragraph_mappings,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    # Act
    await EpisodeRepository.create(episode_data)
    retrieved = await EpisodeRepository.get_by_id("test_ep_002")

    # Assert
    assert retrieved is not None
    assert "paragraph_mappings" in retrieved, "paragraph_mappings field should exist"
    assert retrieved["paragraph_mappings"] == paragraph_mappings, "stored mappings should match input"


# ==================== SubtitleSegmenter Service Tests ====================

def test_segment_paragraphs_basic():
    """测试基本分段功能"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句", "text_translated": "First"},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "第二句", "text_translated": "Second"},
        {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "第三句", "text_translated": "Third"},
    ]

    segmenter = SubtitleSegmenter(max_chars=120, min_chars=40)
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    assert paragraphs[0]["segment_indices"] == [0, 1, 2]
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2", "seg3"]


def test_segment_empty_input():
    """测试空输入"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segmenter = SubtitleSegmenter()
    result = segmenter.segment([])
    assert result == []


def test_segment_long_gap():
    """测试时间间隔超过阈值强制分段"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "第二句", "_index": 1},
        # 间隔超过 2 秒
        {"id": "seg3", "start_ms": 25000, "end_ms": 30000, "text_original": "第三句", "_index": 2},
    ]

    segmenter = SubtitleSegmenter(max_chars=120, min_chars=5, merge_threshold=2.0)
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 2
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2"]
    assert paragraphs[1]["segment_ids"] == ["seg3"]


def test_segment_max_chars_limit():
    """测试字符数超限强制分段"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "这是第一句话", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "这是第二句话", "_index": 1},
        {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "这是第三句话", "_index": 2},
    ]

    segmenter = SubtitleSegmenter(max_chars=15, min_chars=8)
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 2
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2"]
    assert paragraphs[1]["segment_ids"] == ["seg3"]


def test_segment_projects_text_with_punct_not_rule_clean():
    """分段器已解耦: text_clean 投影 text_with_punct, 不再做规则清洗。

    清洗责任上移到 LLM polish(写 Segment.text_with_punct); 分段器只投影。
    若 text_with_punct 含 HTML(说明上游没清干净), 分段器原样投影, 不再二次清洗。
    """
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "_index": 0,
         "text_original": "raw &lt;html&gt;", "text_with_punct": "Clean text one."},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "_index": 1,
         "text_original": "raw <b>bold</b>", "text_with_punct": "Clean text two."},
    ]

    segmenter = SubtitleSegmenter()
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    # text_clean 投影 text_with_punct, 不含 raw html
    assert paragraphs[0]["text_clean"] == "Clean text one. Clean text two."


def test_segmenter_does_not_invoke_rule_clean(monkeypatch):
    """分段器不应再调用规则 clean_text(否则计数 > 0)。"""
    from app.services import subtitle_segmenter as mod
    from app.services.subtitle_segmenter import SubtitleSegmenter

    calls = {"n": 0}
    orig = mod.clean_text

    def spy(text, aggressive=True):
        calls["n"] += 1
        return orig(text, aggressive=aggressive)

    monkeypatch.setattr(mod, "clean_text", spy)

    segs = [
        {"id": "seg_e_0", "start_ms": 0, "end_ms": 1000, "_index": 0,
         "text_original": "raw asr zero", "text_with_punct": "Raw ASR zero."},
        {"id": "seg_e_1", "start_ms": 1000, "end_ms": 2000, "_index": 1,
         "text_original": "raw asr one", "text_with_punct": "Raw ASR one."},
    ]
    SubtitleSegmenter().segment(segs)
    assert calls["n"] == 0


def test_segmenter_falls_back_to_text_original_when_no_punct():
    """text_with_punct 缺失时回退 text_original(零清洗, 但不丢段)。"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segs = [{"id": "s0", "start_ms": 0, "end_ms": 500, "_index": 0,
             "text_original": "只有原文", "text_with_punct": None}]
    paras = SubtitleSegmenter().segment(segs)
    assert paras[0]["text_clean"] == "只有原文"


def test_segmenter_timestamps_and_segment_ids_preserved():
    """解耦后时间戳与 segment_ids 仍正确投影。"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segs = [
        {"id": "seg_e_0", "start_ms": 0, "end_ms": 1000, "_index": 0,
         "text_original": "raw asr zero", "text_with_punct": "Raw ASR zero."},
        {"id": "seg_e_1", "start_ms": 1000, "end_ms": 2000, "_index": 1,
         "text_original": "raw asr one", "text_with_punct": "Raw ASR one."},
    ]
    paras = SubtitleSegmenter().segment(segs)
    p = paras[0]
    assert p["start_ms"] == 0
    assert p["end_ms"] == 2000
    assert p["segment_ids"] == ["seg_e_0", "seg_e_1"]


def test_segment_with_translated_text():
    """测试包含译文的分段"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "Hello", "text_translated": "你好", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "World", "text_translated": "世界", "_index": 1},
    ]

    segmenter = SubtitleSegmenter()
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    # text_original 有空格分隔
    assert paragraphs[0]["text_original"] == "Hello World"
    # text_translated 有空格分隔
    assert paragraphs[0]["text_translated"] == "你好 世界"


def test_segment_skip_empty_text():
    """测试跳过空文本"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "First", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "", "_index": 1},
        {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "Third", "_index": 2},
    ]

    segmenter = SubtitleSegmenter()
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg3"]
