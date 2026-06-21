"""
Admin API 测试

测试管理员批量操作API端点
"""
import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from datetime import datetime

from app.database import EpisodeRepository
from app.models import EpisodeStatus


@pytest.mark.asyncio
async def test_batch_sync_subtitles_success(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 全部成功"""
    # Arrange - 创建3个测试节目（使用ep_前缀）
    episode_ids = ["ep_test_batch_1", "ep_test_batch_2", "ep_test_batch_3"]
    
    for episode_id in episode_ids:
        episode_data = {
            "id": episode_id,
            "title": f"Test Batch {episode_id}",
            "status": EpisodeStatus.READY.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        await EpisodeRepository.create(episode_data)
        
        # 创建字幕文件
        media_dir = temp_data_dir / "media" / episode_id
        media_dir.mkdir(parents=True, exist_ok=True)
        
        transcript_data = {
            "episode_id": episode_id,
            "language": "en",
            "segments": [
                {"id": f"seg1_{episode_id}", "start_ms": 0, "end_ms": 5000, 
                 "text_original": f"First sentence of {episode_id}."},
                {"id": f"seg2_{episode_id}", "start_ms": 5000, "end_ms": 10000, 
                 "text_original": f"Second sentence of {episode_id}."},
            ]
        }
        
        with open(media_dir / "transcript.json", "w") as f:
            json.dump(transcript_data, f)
    
    # Act - 调用批量同步 API
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": episode_ids
    })
    
    # Assert - 验证响应
    assert response.status_code == 200
    data = response.json()
    
    assert data["total"] == 3
    assert len(data["successful"]) == 3
    assert len(data["failed"]) == 0
    assert set(data["successful"]) == set(episode_ids)
    assert "duration_ms" in data
    assert data["duration_ms"] >= 0
    
    # 验证数据库已更新
    for episode_id in episode_ids:
        episode = await EpisodeRepository.get_by_id(episode_id)
        assert episode is not None
        assert "paragraph_mappings" in episode
        assert episode["paragraph_mappings"] is not None
        assert len(episode["paragraph_mappings"]) > 0


@pytest.mark.asyncio
async def test_batch_sync_subtitles_partial_failure(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 部分失败"""
    # Arrange - 创建3个节目，其中1个没有字幕文件（使用ep_前缀）
    episode_ids = ["ep_test_partial_1", "ep_test_partial_2", "ep_test_partial_3"]
    
    for i, episode_id in enumerate(episode_ids):
        episode_data = {
            "id": episode_id,
            "title": f"Test Partial {episode_id}",
            "status": EpisodeStatus.READY.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        await EpisodeRepository.create(episode_data)
        
        # 只为前两个创建字幕文件
        if i < 2:
            media_dir = temp_data_dir / "media" / episode_id
            media_dir.mkdir(parents=True, exist_ok=True)
            
            transcript_data = {
                "episode_id": episode_id,
                "language": "en",
                "segments": [
                    {"id": f"seg1_{episode_id}", "start_ms": 0, "end_ms": 5000, 
                     "text_original": f"Sentence of {episode_id}."},
                ]
            }
            
            with open(media_dir / "transcript.json", "w") as f:
                json.dump(transcript_data, f)
    
    # Act - 调用批量同步 API
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": episode_ids
    })
    
    # Assert - 验证响应
    assert response.status_code == 200
    data = response.json()
    
    assert data["total"] == 3
    assert len(data["successful"]) == 2
    assert len(data["failed"]) == 1
    assert set(data["successful"]) == {"ep_test_partial_1", "ep_test_partial_2"}
    
    # 验证失败信息
    failed_item = data["failed"][0]
    assert failed_item["episode_id"] == "ep_test_partial_3"
    assert "字幕文件不存在" in failed_item["error"]


@pytest.mark.asyncio
async def test_batch_sync_subtitles_empty_request(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 空请求"""
    from app.main import app
    client = TestClient(app)
    
    # Act & Assert - 空列表
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": []
    })
    
    assert response.status_code == 400
    data = response.json()
    assert "message" in data or "detail" in data


@pytest.mark.asyncio
async def test_batch_sync_subtitles_nonexistent_episodes(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 包含不存在的节目"""
    # Arrange - 只创建1个节目，但请求3个（使用一致的ep_前缀）
    episode_data = {
        "id": "ep_test_exists_1",
        "title": "Test Exists",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    media_dir = temp_data_dir / "media" / "ep_test_exists_1"
    media_dir.mkdir(parents=True, exist_ok=True)

    transcript_data = {
        "episode_id": "ep_test_exists_1",
        "language": "en",
        "segments": [
            {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "Test."},
        ]
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f)

    # Act - 请求包含不存在的节目
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": ["ep_test_exists_1", "ep_test_nonexistent_1", "ep_test_nonexistent_2"]
    })

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 3
    assert len(data["successful"]) == 1
    assert data["successful"][0] == "ep_test_exists_1"
    assert len(data["failed"]) == 2
    
    # 验证失败信息
    failed_ids = {item["episode_id"] for item in data["failed"]}
    assert failed_ids == {"ep_test_nonexistent_1", "ep_test_nonexistent_2"}
    
    for failed_item in data["failed"]:
        assert "不存在" in failed_item["error"]


@pytest.mark.asyncio
async def test_batch_sync_subtitles_invalid_transcript(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 无效的字幕数据"""
    # Arrange - 创建节目和无效的字幕文件（使用ep_前缀）
    episode_id = "ep_test_invalid_transcript"
    episode_data = {
        "id": episode_id,
        "title": "Test Invalid Transcript",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    media_dir = temp_data_dir / "media" / episode_id
    media_dir.mkdir(parents=True, exist_ok=True)

    # 创建空的字幕数据
    invalid_data = {
        "episode_id": episode_id,
        "language": "en",
        "segments": []  # 空segments
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(invalid_data, f)

    # Act
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": [episode_id]
    })

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert len(data["successful"]) == 0
    assert len(data["failed"]) == 1
    assert data["failed"][0]["episode_id"] == episode_id
    assert "字幕数据为空" in data["failed"][0]["error"] or "格式错误" in data["failed"][0]["error"]


@pytest.mark.asyncio
async def test_batch_sync_subtitles_large_segments(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 大量segments"""
    # Arrange - 创建包含大量segments的字幕（使用ep_前缀）
    episode_id = "ep_test_large_segments"
    episode_data = {
        "id": episode_id,
        "title": "Test Large Segments",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    media_dir = temp_data_dir / "media" / episode_id
    media_dir.mkdir(parents=True, exist_ok=True)

    # 生成100个segments
    segments = []
    for i in range(100):
        segments.append({
            "id": f"seg_{i}",
            "start_ms": i * 5000,
            "end_ms": (i + 1) * 5000,
            "text_original": f"This is sentence number {i + 1}."
        })

    transcript_data = {
        "episode_id": episode_id,
        "language": "en",
        "segments": segments
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f)

    # Act
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": [episode_id]
    })

    # Assert
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert len(data["successful"]) == 1
    assert len(data["failed"]) == 0
    
    # 验证数据库
    episode = await EpisodeRepository.get_by_id(episode_id)
    assert episode is not None
    assert episode["paragraph_mappings"] is not None
    # 100个segments应该被合并成多个段落（每个段落约120字符）
    assert len(episode["paragraph_mappings"]) > 1


@pytest.mark.asyncio
async def test_batch_sync_subtitles_performance(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 性能验证"""
    # Arrange - 创建10个节目
    episode_ids = [f"ep_test_perf_{i}" for i in range(10)]
    
    for episode_id in episode_ids:
        episode_data = {
            "id": episode_id,
            "title": f"Test Performance {episode_id}",
            "status": EpisodeStatus.READY.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        await EpisodeRepository.create(episode_data)
        
        media_dir = temp_data_dir / "media" / episode_id
        media_dir.mkdir(parents=True, exist_ok=True)
        
        transcript_data = {
            "episode_id": episode_id,
            "language": "en",
            "segments": [
                {"id": f"seg1_{episode_id}", "start_ms": 0, "end_ms": 5000, 
                 "text_original": "Sentence one."},
                {"id": f"seg2_{episode_id}", "start_ms": 5000, "end_ms": 10000, 
                 "text_original": "Sentence two."},
            ]
        }
        
        with open(media_dir / "transcript.json", "w") as f:
            json.dump(transcript_data, f)
    
    # Act
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": episode_ids
    })
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    
    assert data["total"] == 10
    assert len(data["successful"]) == 10
    assert len(data["failed"]) == 0
    
    # 验证性能 - 10个节目应该在合理时间内完成（LLM处理需要更多时间）
    # 使用LLM分段时，10个外部API调用需要15-20秒
    assert data["duration_ms"] < 20000


@pytest.mark.asyncio
async def test_batch_sync_subtitles_idempotent(temp_db, temp_data_dir) -> None:
    """测试批量字幕同步 - 幂等性"""
    # Arrange - 创建节目和字幕（使用ep_前缀）
    episode_id = "ep_test_idempotent"
    episode_data = {
        "id": episode_id,
        "title": "Test Idempotent",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)

    media_dir = temp_data_dir / "media" / episode_id
    media_dir.mkdir(parents=True, exist_ok=True)

    transcript_data = {
        "episode_id": episode_id,
        "language": "en",
        "segments": [
            {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "First."},
            {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "Second."},
        ]
    }

    with open(media_dir / "transcript.json", "w") as f:
        json.dump(transcript_data, f)

    # Act - 调用两次
    from app.main import app
    client = TestClient(app)

    response1 = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": [episode_id]
    })

    response2 = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": [episode_id]
    })

    # Assert - 两次都成功
    assert response1.status_code == 200
    assert response2.status_code == 200

    data1 = response1.json()
    data2 = response2.json()

    # 两次的结果应该一致
    assert data1["successful"] == data2["successful"]
    assert data1["total"] == data2["total"]
    
    # 验证数据库 - paragraph_mappings应该被更新，但内容应该一致
    episode = await EpisodeRepository.get_by_id(episode_id)
    assert episode["paragraph_mappings"] is not None
