"""
Repository层单元测试

测试EpisodeRepository、UsageLogRepository等数据访问层
"""
import pytest
from datetime import datetime

from app.database import EpisodeRepository, UsageLogRepository
from app.models import EpisodeStatus
from tests.conftest import assert_valid_episode


@pytest.mark.unit
@pytest.mark.database
class TestEpisodeRepository:
    """EpisodeRepository测试"""

    async def test_create_episode(self, temp_db):
        """测试创建episode"""
        episode_data = {
            "id": "test_ep_001",
            "title": "Test Episode",
            "status": EpisodeStatus.PENDING.value,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

        await EpisodeRepository.create(episode_data)

        # 验证创建成功
        retrieved = await EpisodeRepository.get_by_id("test_ep_001")
        assert retrieved is not None
        assert retrieved["id"] == "test_ep_001"
        assert retrieved["title"] == "Test Episode"

    async def test_get_episode_by_id(self, temp_db, sample_episode):
        """测试根据ID获取episode"""
        episode = await EpisodeRepository.get_by_id(sample_episode["id"])
        assert episode is not None
        assert episode["id"] == sample_episode["id"]
        assert episode["title"] == sample_episode["title"]

    async def test_get_nonexistent_episode(self, temp_db):
        """测试获取不存在的episode"""
        episode = await EpisodeRepository.get_by_id("nonexistent_id")
        assert episode is None

    async def test_update_episode(self, temp_db, sample_episode):
        """测试更新episode"""
        updated = await EpisodeRepository.update(
            sample_episode["id"],
            title="Updated Title",
            status=EpisodeStatus.READY.value
        )

        assert updated is True

        # 验证更新
        episode = await EpisodeRepository.get_by_id(sample_episode["id"])
        assert episode["title"] == "Updated Title"
        assert episode["status"] == EpisodeStatus.READY.value

    async def test_update_last_activity(self, temp_db, sample_episode):
        """测试更新最后活动时间"""
        await EpisodeRepository.update_last_activity(sample_episode["id"])

        episode = await EpisodeRepository.get_by_id(sample_episode["id"])
        assert episode["last_activity_ts"] is not None

    async def test_delete_episode(self, temp_db, sample_episode):
        """测试删除episode"""
        deleted = await EpisodeRepository.delete(sample_episode["id"])
        assert deleted is True

        # 验证删除
        episode = await EpisodeRepository.get_by_id(sample_episode["id"])
        assert episode is None

    async def test_list_all_episodes(self, temp_db):
        """测试列出所有episodes"""
        # 创建多个episodes
        episodes_to_create = [
            {
                "id": f"test_ep_{i:03d}",
                "title": f"Test Episode {i}",
                "status": EpisodeStatus.READY.value,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
            for i in range(5)
        ]

        for ep_data in episodes_to_create:
            await EpisodeRepository.create(ep_data)

        # 获取列表
        episodes = await EpisodeRepository.list_all()
        assert len(episodes) >= 5


@pytest.mark.unit
@pytest.mark.database
class TestUsageLogRepository:
    """UsageLogRepository测试"""

    async def test_log_event(self, temp_db):
        """测试记录事件日志"""
        await UsageLogRepository.log({
            "event_type": "paste",
            "episode_id": "test_ep_001",
            "payload_json": '{"url": "https://example.com"}'
        })

        # 验证日志已记录
        logs = await UsageLogRepository.get_by_episode("test_ep_001")
        assert len(logs) == 1
        assert logs[0]["event_type"] == "paste"

    async def test_get_logs_by_episode(self, temp_db):
        """测试获取episode的所有日志"""
        episode_id = "test_ep_001"

        # 创建多条日志
        for i in range(3):
            await UsageLogRepository.log({
                "event_type": f"event_{i}",
                "episode_id": episode_id,
            })

        logs = await UsageLogRepository.get_by_episode(episode_id)
        assert len(logs) == 3


@pytest.mark.unit
@pytest.mark.database
class TestIngestJobRepository:
    """IngestJobRepository测试"""

    async def test_create_ingest_job(self, temp_db):
        """测试创建ingest任务"""
        from app.database import IngestJobRepository

        episode_id = "test_ep_001"
        await IngestJobRepository.create(episode_id)

        job = await IngestJobRepository.get_by_id(episode_id)
        assert job is not None
        assert job["episode_id"] == episode_id
        assert job["current_stage"] == "pending"

    async def test_update_stages(self, temp_db):
        """测试更新任务阶段"""
        from app.database import IngestJobRepository

        episode_id = "test_ep_001"
        await IngestJobRepository.create(episode_id)

        stages = [
            {"name": "downloading", "status": "downloading", "progress": 0.5,
             "started_at": "2024-01-01T00:00:00"}
        ]

        await IngestJobRepository.update_stages(episode_id, stages, "downloading")

        job = await IngestJobRepository.get_by_id(episode_id)
        assert job["current_stage"] == "downloading"
        assert len(job["stages"]) > 0
