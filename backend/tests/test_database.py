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


@pytest.mark.database
async def test_init_db_creates_app_setting_table(temp_db):
    """init_db 必须建出 app_setting 表（运行时配置覆写用）。"""
    import aiosqlite
    from app import database as _db
    async with aiosqlite.connect(str(_db.DB_PATH)) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_setting'"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "app_setting"


@pytest.mark.database
async def test_init_db_enables_wal_mode(temp_db):
    """init_db 必须启用 WAL 模式以提升并发性能。"""
    import aiosqlite
    from app import database as _db
    async with aiosqlite.connect(str(_db.DB_PATH)) as db:
        mode = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
    assert mode.lower() == "wal"


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

    def test_update_status_sync_retries_on_locked(self, monkeypatch):
        """对 'database is locked' 指数退避重试，最终成功（不再因偶发锁冲突炸掉）。

        真实事故：busy_timeout=30s 仍可能被超长持锁（>30s）的并发连接击败，
        update_status_sync("ready") 单次失败即 rollback 整集。重试让偶发锁冲突
        可自愈。
        """
        import sqlite3
        import app.database
        from app.database import EpisodeRepositorySync

        # 共享状态：前 2 次 execute 抛 locked，第 3 次成功。每次 with 新建 fake db。
        state = {"fails_remaining": 2, "dbs_created": 0, "execs": 0}

        class _FakeDb:
            def __init__(self):
                state["dbs_created"] += 1

            def execute(self, sql, params=()):
                state["execs"] += 1
                if state["fails_remaining"] > 0:
                    state["fails_remaining"] -= 1
                    raise sqlite3.OperationalError("database is locked")

            def commit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(app.database, "_sync_db", lambda: _FakeDb())
        # 退避不真实等待
        monkeypatch.setattr(app.database.time, "sleep", lambda *_a, **_kw: None)

        # 前 2 次 execute 抛 locked → 重试 → 第 3 次成功（不抛）
        EpisodeRepositorySync.update_status_sync("ep_x", "ready")

        assert state["execs"] == 3, f"应重试到第 3 次，实际 execute {state['execs']} 次"
        assert state["dbs_created"] == 3, "每次重试应新建连接"

    def test_update_status_sync_raises_non_lock_error(self, monkeypatch):
        """非锁错误（如 'no such table'）不重试，直接抛。"""
        import sqlite3
        import app.database
        from app.database import EpisodeRepositorySync

        class _FakeDb:
            def execute(self, sql, params=()):
                raise sqlite3.OperationalError("no such table: episode")

            def commit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(app.database, "_sync_db", lambda: _FakeDb())
        sleeps = []
        monkeypatch.setattr(app.database.time, "sleep", lambda s: sleeps.append(s))

        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            EpisodeRepositorySync.update_status_sync("ep_x", "ready")
        assert sleeps == [], "非锁错误不应触发重试退避"


@pytest.mark.unit
class TestSyncGetByIdDecodesJson:
    """get_by_id_sync 必须和 async get_by_id 一样 json.loads(paragraph_mappings)。

    episode 表把 paragraph_mappings 存成 JSON 字符串（TEXT）。async get_by_id /
    list_all / search 都解码成 list，唯独 sync get_by_id_sync 历史上返回裸 dict(row)
    → EpisodeManager.get_bundle → Episode(**data) 因 paragraph_mappings 是 str 而非
    list 抛 ValidationError（Pydantic Optional[List[Dict]]）。离线/同步调用方拿不到
    bundle。修在源头（sync getter），所有同步调用方一次性修复。
    """

    def test_get_by_id_sync_decodes_paragraph_mappings(self, monkeypatch, tmp_path):
        import json
        import app.database
        from app.database import EpisodeRepositorySync, _sync_db

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        payload = [{"id": 0, "start_ms": 120, "end_ms": 109200, "text": "hi"}]
        with _sync_db() as db:
            db.execute(
                "CREATE TABLE episode (id TEXT PRIMARY KEY, paragraph_mappings TEXT)"
            )
            db.execute(
                "INSERT INTO episode (id, paragraph_mappings) VALUES (?, ?)",
                ("ep1", json.dumps(payload)),
            )
            db.commit()

        data = EpisodeRepositorySync.get_by_id_sync("ep1")

        assert data is not None
        assert isinstance(data["paragraph_mappings"], list), (
            "sync getter 应把 paragraph_mappings JSON 字符串解码成 list"
        )
        assert data["paragraph_mappings"] == payload

    def test_get_by_id_sync_bad_paragraph_mappings_becomes_none(self, monkeypatch, tmp_path):
        """损坏的 JSON 不抛错，降级为 None（与 async get_by_id 的 except 分支一致）。"""
        import app.database
        from app.database import EpisodeRepositorySync, _sync_db

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        with _sync_db() as db:
            db.execute(
                "CREATE TABLE episode (id TEXT PRIMARY KEY, paragraph_mappings TEXT)"
            )
            db.execute(
                "INSERT INTO episode (id, paragraph_mappings) VALUES (?, ?)",
                ("ep1", "{not valid json"),
            )
            db.commit()

        data = EpisodeRepositorySync.get_by_id_sync("ep1")

        assert data is not None
        assert data["paragraph_mappings"] is None, (
            "损坏的 paragraph_mappings 应降级为 None，不让整次读取炸掉"
        )

    def test_get_by_id_sync_null_paragraph_mappings_stays_none(self, monkeypatch, tmp_path):
        """NULL / 空 paragraph_mappings 保持 None，不误触发解码。"""
        import app.database
        from app.database import EpisodeRepositorySync, _sync_db

        monkeypatch.setattr(app.database, "DB_PATH", tmp_path / "t.db")
        with _sync_db() as db:
            db.execute(
                "CREATE TABLE episode (id TEXT PRIMARY KEY, paragraph_mappings TEXT)"
            )
            db.execute(
                "INSERT INTO episode (id, paragraph_mappings) VALUES (?, ?)",
                ("ep1", None),
            )
            db.commit()

        data = EpisodeRepositorySync.get_by_id_sync("ep1")

        assert data is not None
        assert data["paragraph_mappings"] is None
