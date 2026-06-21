"""
字幕同步 API 测试

测试字幕分段同步的 API 端点
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from app.database import EpisodeRepository
from app.models import EpisodeStatus


@pytest.mark.asyncio
async def test_sync_subtitle_segments(temp_db, temp_data_dir) -> None:
    """测试字幕同步 API - 基本功能"""
    # Arrange - 创建测试节目
    episode_data = {
        "id": "test_sync_ep",
        "title": "Test Sync Episode",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    # 创建测试字幕文件
    from pathlib import Path
    import json

    # 使用 temp_data_dir 作为媒体目录
    media_dir = temp_data_dir / "media" / "test_sync_ep"
    media_dir.mkdir(parents=True, exist_ok=True)

    transcript_data = {
        "episode_id": "test_sync_ep",
        "language": "en",
        "segments": [
            {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "This is the first sentence."},
            {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "This is the second sentence."},
            {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "This is the third sentence."},
        ]
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f)

    # Act - 调用同步 API
    from app.main import app
    client = TestClient(app)
    response = client.post(f"/api/episodes/test_sync_ep/sync-subtitles")

    # Assert - 验证响应
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "episode_id" in data
    assert data["episode_id"] == "test_sync_ep"
    assert "paragraph_count" in data
    assert "paragraph_mappings" in data
    assert "segment_count" in data
    assert isinstance(data["paragraph_mappings"], list)
    assert len(data["paragraph_mappings"]) > 0
    assert data["segment_count"] == 3

    # 验证数据库已更新
    updated_episode = await EpisodeRepository.get_by_id("test_sync_ep")
    assert updated_episode is not None
    assert "paragraph_mappings" in updated_episode
    assert updated_episode["paragraph_mappings"] is not None
    assert len(updated_episode["paragraph_mappings"]) > 0


@pytest.mark.asyncio
async def test_sync_subtitle_segments_episode_not_found(temp_db, temp_data_dir) -> None:
    """测试字幕同步 API - 节目不存在"""
    from app.main import app
    client = TestClient(app)

    response = client.post("/api/episodes/nonexistent/sync-subtitles")

    assert response.status_code == 404
    data = response.json()
    assert "message" in data  # Custom error handler uses 'message' not 'detail'


@pytest.mark.asyncio
async def test_sync_subtitle_segments_no_transcript(temp_db, temp_data_dir) -> None:
    """测试字幕同步 API - 没有字幕文件"""
    # Arrange - 创建没有字幕的节目
    episode_data = {
        "id": "test_no_transcript",
        "title": "Test No Transcript",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    # Act & Assert
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/episodes/test_no_transcript/sync-subtitles")

    assert response.status_code == 400
    data = response.json()
    assert "message" in data  # Custom error handler uses 'message' not 'detail'
    assert "transcript" in data["message"].lower() or "字幕" in data["message"]


@pytest.mark.asyncio
async def test_get_episode_includes_paragraph_mappings(temp_db, temp_data_dir) -> None:
    """测试获取节目详情时包含分段映射"""
    # Arrange - 创建节目并添加分段映射
    episode_data = {
        "id": "test_with_mappings",
        "title": "Test Episode with Mappings",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "paragraph_mappings": [
            {
                "id": 0,
                "start_ms": 0,
                "end_ms": 15000,
                "text_original": "Test paragraph",
                "text_translated": "测试段落",
                "segment_indices": [0, 1],
                "segment_ids": ["seg1", "seg2"]
            }
        ]
    }
    await EpisodeRepository.create(episode_data)

    # Act
    from app.main import app
    client = TestClient(app)
    response = client.get(f"/api/episode/test_with_mappings")

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "episode" in data
    # EpisodeBundle contains an "episode" key which is the Episode object
    bundle = data["episode"]
    assert "episode" in bundle  # The Episode object inside the bundle
    episode_obj = bundle["episode"]
    assert "paragraph_mappings" in episode_obj
    assert episode_obj["paragraph_mappings"] is not None
    assert len(episode_obj["paragraph_mappings"]) == 1
    assert episode_obj["paragraph_mappings"][0]["id"] == 0


@pytest.mark.asyncio
async def test_sync_then_get_episode_flow(temp_db, temp_data_dir) -> None:
    """测试完整的同步后获取流程"""
    # Arrange - 创建节目和字幕文件
    episode_data = {
        "id": "test_flow_ep",
        "title": "Test Flow Episode",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    # 创建字幕文件
    from pathlib import Path
    import json

    media_dir = temp_data_dir / "media" / "test_flow_ep"
    media_dir.mkdir(parents=True, exist_ok=True)

    transcript_data = {
        "episode_id": "test_flow_ep",
        "language": "en",
        "segments": [
            {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "First sentence."},
            {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "Second sentence."},
            {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "Third sentence."},
            {"id": "seg4", "start_ms": 15000, "end_ms": 20000, "text_original": "Fourth sentence."},
        ]
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f)

    # Act 1 - 同步字幕
    from app.main import app
    client = TestClient(app)
    sync_response = client.post("/api/episodes/test_flow_ep/sync-subtitles")

    # Assert 1 - 同步成功
    assert sync_response.status_code == 200
    sync_data = sync_response.json()
    assert sync_data["paragraph_count"] > 0

    # Act 2 - 获取节目详情
    episode_response = client.get("/api/episode/test_flow_ep")

    # Assert 2 - 节目详情包含映射
    assert episode_response.status_code == 200
    response_data = episode_response.json()
    assert "episode" in response_data
    # EpisodeBundle contains an "episode" key which is the Episode object
    bundle = response_data["episode"]
    assert "episode" in bundle
    episode_obj = bundle["episode"]
    assert "paragraph_mappings" in episode_obj
    assert episode_obj["paragraph_mappings"] is not None
    assert len(episode_obj["paragraph_mappings"]) == sync_data["paragraph_count"]
