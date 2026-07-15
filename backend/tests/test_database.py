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


@pytest.mark.unit
class TestSyncDbBusyTimeout:
    """同步连接必须设 busy_timeout —— 否则 async pipeline 收尾时
    save_episode_bundle 与并发写冲突必 'database is locked'
    (ep_1783264218536 全 pipeline 跑完却 rollback 的根因)。"""

    def test_sync_db_sets_busy_timeout(self, tmp_path, monkeypatch):
        import app.database
        from app.database import _sync_db

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        db = _sync_db()
        try:
            assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        finally:
            db.close()

    def test_update_status_sync_writes_without_lock(self, tmp_path, monkeypatch):
        """端到端: update_status_sync 经 _sync_db() 写入, 不再 lock。"""
        import app.database
        from app.database import EpisodeRepositorySync, _sync_db

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        # 建表 + 插一行
        with _sync_db() as db:
            db.execute(
                "CREATE TABLE episode (id TEXT PRIMARY KEY, status TEXT, "
                "error_msg TEXT, updated_at TEXT)"
            )
            db.execute("INSERT INTO episode (id, status) VALUES ('ep1', 'pending')")
            db.commit()
        # 收尾写 — 之前这里会 lock, 现在走 _sync_db (busy_timeout)
        EpisodeRepositorySync.update_status_sync("ep1", "ready")
        with _sync_db() as db:
            row = db.execute("SELECT status FROM episode WHERE id='ep1'").fetchone()
        assert row[0] == "ready"


@pytest.mark.unit
@pytest.mark.database
class TestAsyncConnectionPragmas:
    """异步连接必须套 busy_timeout、且 init_db 切 WAL —— 否则 pipeline 收尾
    的并发 async 写（product_insights 等）与 ASR/LLM 写冲突必 'database is
    locked'（ep_1784027010762 六件产物齐全却被 rollback 的根因）。

    WAL 是文件级持久属性（init_db 一次性切换）；busy_timeout 是每连接属性，
    由 _connect() 统一注入。复现写锁竞争本身是 flaky 的，这里用确定的 PRAGMA
    断言锁住契约。"""

    async def test_connect_applies_busy_timeout(self, tmp_path, monkeypatch):
        """_connect() 进 async-with 后必须带 busy_timeout=30000。"""
        import app.database
        from app.database import _connect

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        async with _connect() as db:
            bt = (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0]
        assert bt == 30000

    async def test_init_db_sets_wal_mode(self, tmp_path, monkeypatch):
        """init_db 必须把新库切到 WAL（持久、文件级）。"""
        import app.database
        from app.database import init_db, _connect

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        await init_db()
        async with _connect() as db:
            jm = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
        assert jm == "wal"
