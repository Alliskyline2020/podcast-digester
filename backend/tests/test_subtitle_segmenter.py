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


def test_segment_html_cleaning():
    """测试 HTML 标签和实体清理"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "Hello &lt;world&gt;", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "This is <b>bold</b> text", "_index": 1},
    ]

    segmenter = SubtitleSegmenter()
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    # text_original 保留原始文本，segments之间有空格
    assert paragraphs[0]["text_original"] == "Hello &lt;world&gt; This is <b>bold</b> text"
    # text_clean 包含清洗后的文本
    assert paragraphs[0]["text_clean"] == "Hello <world> This is bold text"
    assert "<b>" not in paragraphs[0]["text_clean"]
    assert "&lt;" not in paragraphs[0]["text_clean"]


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
